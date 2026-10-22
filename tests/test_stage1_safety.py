import json

from pattern_vault.agent.tools import _tool_read_file, _tool_scan_directory
from pattern_vault.api.routes import stats as stats_routes
from pattern_vault.indexer import chunker
from pattern_vault.indexer.batch import index_directory
from pattern_vault.indexer.chunker import chunk_file, scan_directory
from pattern_vault.store.db import (
    DEFAULT_DB_PATH,
    delete_pattern,
    get_connection,
    get_pattern,
    init_db,
    insert_pattern,
    resolve_db_path,
    search_fts,
    update_pattern,
)


def test_resolve_db_path_prefers_explicit_then_env(monkeypatch, tmp_path):
    env_db = tmp_path / "env" / "patterns.db"
    explicit_db = tmp_path / "explicit" / "patterns.db"

    monkeypatch.setenv("PATTERN_VAULT_DB", str(env_db))

    assert resolve_db_path() == env_db
    assert resolve_db_path(explicit_db) == explicit_db

    monkeypatch.delenv("PATTERN_VAULT_DB")
    assert resolve_db_path() == DEFAULT_DB_PATH


def test_get_connection_creates_configured_db(monkeypatch, tmp_path):
    db_path = tmp_path / "vault" / "patterns.db"
    monkeypatch.setenv("PATTERN_VAULT_DB", str(db_path))

    conn = get_connection()
    try:
        init_db(conn)
    finally:
        conn.close()

    assert db_path.exists()


def test_insert_and_search_pattern(tmp_path):
    conn = get_connection(tmp_path / "patterns.db")
    try:
        init_db(conn)
        pattern_id = insert_pattern(
            conn,
            name="Exponential retry helper",
            summary="Retries transient failures with exponential backoff.",
            code_text="def retry():\n    pass\n",
            category="resilience",
            language="python",
            tags=["retry", "backoff"],
        )

        results = search_fts(conn, "retry", limit=5)
    finally:
        conn.close()

    assert pattern_id > 0
    assert [result["name"] for result in results] == ["Exponential retry helper"]


def test_update_and_delete_pattern(tmp_path):
    conn = get_connection(tmp_path / "patterns.db")
    try:
        init_db(conn)
        pattern_id = insert_pattern(
            conn,
            name="Retry helper",
            summary="Retries transient failures.",
            code_text="def retry():\n    pass\n",
            category="resilience",
            language="python",
            tags=["retry"],
        )

        updated = update_pattern(
            conn,
            pattern_id,
            name="Backoff retry helper",
            tags=["retry", "backoff"],
            code_text="def retry_with_backoff():\n    pass\n",
        )
        pattern = get_pattern(conn, pattern_id)
        search_results = search_fts(conn, "backoff", limit=5)
        deleted = delete_pattern(conn, pattern_id)
        missing = get_pattern(conn, pattern_id)
    finally:
        conn.close()

    assert updated is True
    assert pattern["name"] == "Backoff retry helper"
    assert pattern["tags"] == ["retry", "backoff"]
    assert "retry_with_backoff" in pattern["chunks"][0]["code_text"]
    assert [result["id"] for result in search_results] == [pattern_id]
    assert deleted is True
    assert missing is None


def test_chunking_and_dry_run_index(tmp_path):
    source = tmp_path / "service.py"
    source.write_text(
        "def useful_retry(value):\n"
        "    if not value:\n"
        "        return 'fallback'\n"
        "    return value\n",
        encoding="utf-8",
    )

    manifest = scan_directory(tmp_path)
    chunks = chunk_file(source, "python")
    stats = index_directory(tmp_path, db_path=tmp_path / "patterns.db", dry_run=True)

    assert manifest.total_files == 1
    assert chunks
    assert any("useful_retry" in chunk.code for chunk in chunks)
    assert stats.files_scanned == 1
    assert stats.chunks_extracted >= 1
    assert stats.patterns_found == 0
    assert stats.patterns_stored == 0


def test_init_db_adds_quality_score_to_existing_v9_vault(tmp_path):
    # Existing vaults are at v9; upgrading must add the column without losing patterns.
    db_path = tmp_path / "patterns.db"
    conn = get_connection(db_path)
    init_db(conn)
    pattern_id = insert_pattern(conn, name="Old", summary="Saved before v10", code_text="x = 1")
    conn.execute("ALTER TABLE patterns DROP COLUMN quality_score")
    conn.execute("UPDATE db_meta SET value = '9' WHERE key = 'version'")
    conn.commit()

    init_db(conn)
    pattern = get_pattern(conn, pattern_id)
    conn.close()

    assert pattern["name"] == "Old"
    assert pattern["quality_score"] is None


def test_typescript_files_chunk_by_symbol_not_blank_lines(tmp_path):
    # tree-sitter-typescript is a declared dependency; a silent fallback to blank-line
    # blocks hands the extractor fragments instead of whole functions.
    ts_source = tmp_path / "retry.ts"
    ts_source.write_text(
        "export function retry<T>(fn: () => T, attempts: number): T {\n"
        "  for (let i = 0; i < attempts - 1; i++) {\n"
        "    try { return fn() } catch {}\n"
        "\n"
        "  }\n"
        "  return fn()\n"
        "}\n",
        encoding="utf-8",
    )
    tsx_source = tmp_path / "Button.tsx"
    tsx_source.write_text(
        "export function Button({ label }: { label: string }) {\n"
        "  const text = label.trim()\n"
        "\n"
        "  return <button>{text}</button>\n"
        "}\n",
        encoding="utf-8",
    )

    for source in (ts_source, tsx_source):
        chunks = chunk_file(source)
        assert len(chunks) == 1
        assert chunks[0].symbol_type != "block"
        assert chunks[0].line_start == 1


def test_deeply_nested_file_chunks_without_recursion_error(tmp_path):
    # Real headers (ggml-common.h) nest deeper than Python's recursion limit; the AST
    # walk must not crash, or every symbol after the deep expression is lost.
    source = tmp_path / "deep.py"
    source.write_text(
        "value = " + "(" * 3000 + "1" + ")" * 3000 + "\n"
        "\n"
        "def after_deep_expression():\n"
        "    return value\n",
        encoding="utf-8",
    )

    chunks = chunk_file(source)

    assert [chunk.symbol_name for chunk in chunks] == ["after_deep_expression"]


def test_health_lists_only_languages_with_an_installed_grammar(monkeypatch):
    # The portal warns about languages missing from this list. Listing a language
    # without a grammar would hide that its files are split on blank lines.
    monkeypatch.setitem(chunker.GRAMMAR_MODULES, "go", "tree_sitter_not_installed")

    ast_languages = stats_routes.health()["ast_languages"]

    assert {"python", "javascript", "typescript"} <= set(ast_languages)
    assert "go" not in ast_languages


def test_agent_file_tools_require_allowed_workspace(monkeypatch, tmp_path):
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()
    allowed_file = allowed / "service.py"
    outside_file = outside / "secret.py"
    allowed_file.write_text("def visible():\n    return True\n", encoding="utf-8")
    outside_file.write_text("def hidden():\n    return True\n", encoding="utf-8")

    monkeypatch.setenv("PATTERN_VAULT_WORKSPACE_ROOTS", str(allowed))

    allowed_result = json.loads(_tool_read_file(str(allowed_file)))
    outside_result = json.loads(_tool_read_file(str(outside_file)))
    scan_result = json.loads(_tool_scan_directory(str(outside)))

    assert "visible" in allowed_result["content"]
    assert "outside allowed workspace roots" in outside_result["error"]
    assert "outside allowed workspace roots" in scan_result["error"]


def test_agent_file_tools_block_sensitive_and_large_files(monkeypatch, tmp_path):
    monkeypatch.setenv("PATTERN_VAULT_WORKSPACE_ROOTS", str(tmp_path))

    secret = tmp_path / ".env"
    large = tmp_path / "large.py"
    secret.write_text("TOKEN=secret\n", encoding="utf-8")
    large.write_text("x = 'too large'\n" * 20_000, encoding="utf-8")

    secret_result = json.loads(_tool_read_file(str(secret)))
    large_result = json.loads(_tool_read_file(str(large)))

    assert "Blocked sensitive path" in secret_result["error"]
    assert "too large" in large_result["error"]
