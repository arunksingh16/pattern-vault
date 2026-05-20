import json

from src.agent.tools import _tool_read_file, _tool_scan_directory
from src.indexer.batch import index_directory
from src.indexer.chunker import chunk_file, scan_directory
from src.store.db import (
    DEFAULT_DB_PATH,
    delete_pattern,
    get_connection,
    get_pattern,
    init_db,
    insert_insight,
    insert_pattern,
    resolve_db_path,
    search_fts,
    update_pattern,
)
from src.ui import app as ui_app
from src.ui.app import _parse_pattern_edit_payload


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


def test_parse_pattern_edit_payload_normalizes_tags_and_rejects_unknown_fields():
    payload = _parse_pattern_edit_payload('{"tags": "retry, backoff", "line_start": "10"}')

    assert payload == {"tags": ["retry", "backoff"], "line_start": 10}

    try:
        _parse_pattern_edit_payload('{"unsupported": true}')
    except ValueError as exc:
        assert "Unsupported field" in str(exc)
    else:
        raise AssertionError("Expected unsupported field to fail")


def test_workspace_dashboard_uses_current_vault_data(monkeypatch, tmp_path):
    db_path = tmp_path / "patterns.db"
    monkeypatch.setattr(ui_app, "DB_PATH", db_path)
    monkeypatch.setattr(ui_app, "_history_path", lambda: tmp_path / "history.jsonl")
    monkeypatch.setenv("PATTERN_VAULT_WORKSPACE_ROOTS", str(tmp_path))

    conn = get_connection(db_path)
    try:
        init_db(conn)
        insert_pattern(
            conn,
            name="Circuit breaker",
            summary="Stops calls after repeated failures.",
            code_text="class CircuitBreaker:\n    pass\n",
            category="resilience",
            language="python",
            tags=["reliability", "failure"],
            source_file="src/circuit.py",
        )
        insert_insight(
            conn,
            repo_path=str(tmp_path),
            insight_text="Service boundaries are explicit and easy to scan.",
            tags=["architecture"],
        )
    finally:
        conn.close()

    dashboard = ui_app._format_dashboard()

    assert "Pattern Vault Workspace" in dashboard
    assert "Circuit breaker" in dashboard
    assert "Service boundaries are explicit" in dashboard
    assert "resilience" in dashboard
    assert str(db_path) in dashboard


def test_workspace_dashboard_empty_state_is_actionable(monkeypatch, tmp_path):
    db_path = tmp_path / "patterns.db"
    monkeypatch.setattr(ui_app, "DB_PATH", db_path)
    monkeypatch.setattr(ui_app, "_history_path", lambda: tmp_path / "history.jsonl")

    dashboard = ui_app._format_dashboard()

    assert "No saved patterns yet" in dashboard
    assert "No repo insights saved yet" in dashboard
    assert "Scan a repository" in dashboard


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
