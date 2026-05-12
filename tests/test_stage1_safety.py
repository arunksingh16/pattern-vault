import json

from src.agent.tools import _tool_read_file, _tool_scan_directory
from src.indexer.batch import index_directory
from src.indexer.chunker import chunk_file, scan_directory
from src.store.db import (
    DEFAULT_DB_PATH,
    get_connection,
    init_db,
    insert_pattern,
    resolve_db_path,
    search_fts,
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
