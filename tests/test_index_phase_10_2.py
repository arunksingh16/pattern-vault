import asyncio
import json
from types import SimpleNamespace

from src.api.routes import workspace
from src.indexer import batch as batch_module
from src.indexer.batch import index_directory
from src.indexer.extractor import (
    ExtractionResponseError,
    ExtractionResult,
    extract_patterns_sync,
)
from src.indexer.profiles import INDEXING_PROFILES, IndexingProfile
from src.store.db import get_connection, get_index_job, init_db


class _FakeMessages:
    def __init__(self, response):
        self.response = response

    def create(self, **_kwargs):
        return self.response


class _FakeClient:
    def __init__(self, response):
        self.messages = _FakeMessages(response)


def test_extract_patterns_sync_rejects_empty_content(monkeypatch, tmp_path):
    response = SimpleNamespace(content=[], usage=None)
    monkeypatch.setattr("src.client.make_client", lambda: _FakeClient(response))

    try:
        extract_patterns_sync([_chunk_payload()], db_path=tmp_path / "patterns.db")
    except ExtractionResponseError as exc:
        assert "no content blocks returned" in str(exc)
        assert "anthropic/claude-sonnet" in str(exc)
    else:
        raise AssertionError("Expected empty extraction content to fail")


def test_extract_patterns_sync_uses_first_text_block(monkeypatch, tmp_path):
    response = SimpleNamespace(
        content=[
            SimpleNamespace(type="tool_use", input={}),
            SimpleNamespace(
                type="text",
                text='[{"chunk_index": 0, "is_pattern": true, "name": "Retry helper"}]',
            ),
        ],
        usage=None,
    )
    monkeypatch.setattr("src.client.make_client", lambda: _FakeClient(response))

    results = extract_patterns_sync([_chunk_payload()], db_path=tmp_path / "patterns.db")

    assert len(results) == 1
    assert results[0].is_pattern is True
    assert results[0].name == "Retry helper"


def test_extract_patterns_sync_rejects_invalid_json(monkeypatch, tmp_path):
    response = SimpleNamespace(
        content=[SimpleNamespace(type="text", text="not json")],
        usage=None,
    )
    monkeypatch.setattr("src.client.make_client", lambda: _FakeClient(response))

    try:
        extract_patterns_sync([_chunk_payload()], db_path=tmp_path / "patterns.db")
    except ExtractionResponseError as exc:
        assert "invalid JSON" in str(exc)
    else:
        raise AssertionError("Expected malformed extraction JSON to fail")


def test_extract_patterns_sync_rejects_malformed_result_shape(monkeypatch, tmp_path):
    response = SimpleNamespace(
        content=[SimpleNamespace(type="text", text='[{"chunk_index": "0", "is_pattern": true}]')],
        usage=None,
    )
    monkeypatch.setattr("src.client.make_client", lambda: _FakeClient(response))

    try:
        extract_patterns_sync([_chunk_payload()], db_path=tmp_path / "patterns.db")
    except ExtractionResponseError as exc:
        assert "chunk_index is not an integer" in str(exc)
    else:
        raise AssertionError("Expected malformed extraction result shape to fail")


def test_index_directory_retries_extraction_and_continues(monkeypatch, tmp_path):
    source = tmp_path / "service.py"
    source.write_text(
        "def useful_retry(value):\n"
        "    if not value:\n"
        "        return 'fallback'\n"
        "    return value\n",
        encoding="utf-8",
    )
    attempts = 0
    logs = []

    def flaky_extract(*_args, **_kwargs):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise RuntimeError("temporary provider failure")
        return []

    monkeypatch.setattr(batch_module, "extract_patterns_sync", flaky_extract)
    monkeypatch.setattr(batch_module, "EXTRACTION_BACKOFF_SECONDS", 0)

    stats = index_directory(
        tmp_path,
        db_path=tmp_path / "patterns.db",
        on_progress=logs.append,
    )

    assert attempts == 3
    assert stats.errors == []
    assert any("Retrying extraction for batch 1 (chunks 1-1)" in line for line in logs)


def test_index_directory_reports_human_batch_and_chunk_range(monkeypatch, tmp_path):
    source = tmp_path / "service.py"
    source.write_text(
        "def useful_retry(value):\n"
        "    if not value:\n"
        "        return 'fallback'\n"
        "    return value\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        batch_module,
        "extract_patterns_sync",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("bad response")),
    )
    monkeypatch.setattr(batch_module, "EXTRACTION_BACKOFF_SECONDS", 0)

    stats = index_directory(tmp_path, db_path=tmp_path / "patterns.db")

    assert stats.errors == [
        "Extraction error at batch 1 (chunks 1-1) after 3 attempts: bad response"
    ]


def test_index_directory_curated_profile_rejects_low_quality_pattern(monkeypatch, tmp_path):
    source = tmp_path / "service.py"
    source.write_text(
        "def useful_retry(value):\n"
        "    if not value:\n"
        "        return 'fallback'\n"
        "    return value\n",
        encoding="utf-8",
    )
    logs = []

    monkeypatch.setattr(
        batch_module,
        "extract_patterns_sync",
        lambda *_args, **_kwargs: [
            ExtractionResult(
                chunk_index=0,
                is_pattern=True,
                name="Small helper",
                category="utility",
                quality_score=0.6,
            )
        ],
    )

    stats = index_directory(
        tmp_path,
        db_path=tmp_path / "patterns.db",
        on_progress=logs.append,
        profile="curated",
    )

    assert stats.patterns_found == 1
    assert stats.patterns_stored == 0
    assert stats.patterns_rejected == 1
    assert any("Rejected: [utility] Small helper" in line for line in logs)


def test_index_directory_filters_manifest_before_chunking(tmp_path):
    src_dir = tmp_path / "src"
    tests_dir = tmp_path / "tests"
    src_dir.mkdir()
    tests_dir.mkdir()

    (src_dir / "service.py").write_text(
        "def useful_retry(value):\n"
        "    if not value:\n"
        "        return 'fallback'\n"
        "    return value\n",
        encoding="utf-8",
    )
    (src_dir / "ignored.ts").write_text(
        "export function ignored(value: string) {\n"
        "  return value\n"
        "}\n",
        encoding="utf-8",
    )
    (tests_dir / "test_service.py").write_text(
        "def test_retry():\n"
        "    assert True\n",
        encoding="utf-8",
    )

    stats = index_directory(
        tmp_path,
        db_path=tmp_path / "patterns.db",
        dry_run=True,
        include_languages=["python"],
        include_paths=["src/**"],
        exclude_paths=["tests/**"],
    )

    assert stats.files_scanned == 1
    assert stats.chunks_extracted == 1


def test_index_directory_profile_budget_stops_after_limit(monkeypatch, tmp_path):
    for index in range(6):
        source = tmp_path / f"service_{index}.py"
        source.write_text(
            f"def useful_retry_{index}(value):\n"
            "    if not value:\n"
            "        return 'fallback'\n"
            "    return value\n",
            encoding="utf-8",
        )

    monkeypatch.setattr(batch_module, "BATCH_SIZE", 2)
    monkeypatch.setattr(
        "src.indexer.profiles.INDEXING_PROFILES",
        {
            **INDEXING_PROFILES,
            "curated": IndexingProfile(
                name="curated",
                label="Curated",
                min_quality_score=0.8,
                small_repo_budget=1,
                medium_repo_budget=1,
                large_repo_budget=1,
                guidance="test guidance",
            ),
        },
    )
    calls = 0

    def fake_extract(chunks, **_kwargs):
        nonlocal calls
        calls += 1
        return [
            ExtractionResult(
                chunk_index=index,
                is_pattern=True,
                name=f"Pattern {index}",
                category="utility",
                quality_score=0.95,
            )
            for index, _chunk in enumerate(chunks)
        ]

    monkeypatch.setattr(batch_module, "extract_patterns_sync", fake_extract)

    stats = index_directory(
        tmp_path,
        db_path=tmp_path / "patterns.db",
        profile="curated",
    )

    assert calls == 1
    assert stats.patterns_stored == 1


def test_workspace_job_persists_completed_with_errors(monkeypatch, tmp_path):
    db_path = tmp_path / "patterns.db"
    monkeypatch.setattr(workspace, "DB_PATH", db_path)

    def fake_index_directory(
        _path,
        _db_path,
        _repo_name,
        _api_key,
        on_progress,
        _dry_run,
        _profile,
        _include_languages,
        _include_paths,
        _exclude_paths,
    ):
        on_progress("Done. Found 1 patterns, stored 1.")
        return batch_module.IndexStats(
            files_scanned=1,
            chunks_extracted=1,
            patterns_found=1,
            patterns_stored=1,
            patterns_rejected=0,
            errors=["Extraction error at batch 1 (chunks 1-1) after 3 attempts: bad response"],
        )

    monkeypatch.setattr(workspace, "index_directory", fake_index_directory)

    async def run_job():
        manager = workspace.WorkspaceIndexManager()
        job = await manager.create_job(tmp_path, "repo", "path", "repo", False, "curated")
        await job.task
        return job

    job = asyncio.run(run_job())

    conn = get_connection(db_path)
    try:
        init_db(conn)
        record = get_index_job(conn, job.job_id)
    finally:
        conn.close()

    assert job.status == "completed_with_errors"
    assert job.error.startswith("Completed with 1 error. First error:")
    assert record["status"] == "completed_with_errors"
    assert record["error"] == job.error
    assert record["profile"] == "curated"


def test_workspace_job_persists_filter_selections(monkeypatch, tmp_path):
    db_path = tmp_path / "patterns.db"
    monkeypatch.setattr(workspace, "DB_PATH", db_path)

    async def run_job():
        manager = workspace.WorkspaceIndexManager()
        job = await manager.create_job(
            tmp_path,
            "repo",
            "path",
            "repo",
            True,
            "balanced",
            ["python", "typescript"],
            ["src/**"],
            ["tests/**"],
        )
        await job.task
        return job

    job = asyncio.run(run_job())

    conn = get_connection(db_path)
    try:
        init_db(conn)
        record = get_index_job(conn, job.job_id)
    finally:
        conn.close()

    assert job.include_languages == ["python", "typescript"]
    assert job.include_paths == ["src/**"]
    assert job.exclude_paths == ["tests/**"]
    assert record["profile"] == "balanced"
    assert record["include_languages"] == ["python", "typescript"]
    assert record["include_paths"] == ["src/**"]
    assert record["exclude_paths"] == ["tests/**"]


def test_stream_index_replay_starts_with_job_summary(monkeypatch, tmp_path):
    db_path = tmp_path / "patterns.db"
    monkeypatch.setattr(workspace, "DB_PATH", db_path)

    conn = get_connection(db_path)
    try:
        init_db(conn)
        workspace_id = "job-1"
        stats = {
            "files_discovered": 2,
            "files_skipped": 1,
            "files_scanned": 1,
            "chunks_extracted": 3,
            "patterns_found": 0,
            "patterns_stored": 0,
            "patterns_rejected": 0,
            "current_stage": "scan",
        }
        from src.store.db import append_index_job_event, create_index_job

        create_index_job(
            conn,
            workspace_id,
            "repo",
            "path",
            str(tmp_path),
            repo_name="repo",
            dry_run=False,
            index_profile="balanced",
            include_languages=["python"],
            include_paths=["src/**"],
            exclude_paths=["tests/**"],
            status="running",
            stats=stats,
        )
        append_index_job_event(
            conn,
            workspace_id,
            {"type": "log", "message": "Scanning repo", "stats": stats},
        )
    finally:
        conn.close()

    class _Request:
        def __init__(self):
            self.app = SimpleNamespace(
                state=SimpleNamespace(workspace_index_manager=workspace.WorkspaceIndexManager())
            )

        async def is_disconnected(self):
            return False

    async def collect_chunks():
        response = await workspace.stream_index(workspace_id, _Request())
        chunks = []
        async for chunk in response.body_iterator:
            chunks.append(chunk)
        return chunks

    chunks = asyncio.run(collect_chunks())
    payloads = [
        json.loads(chunk.removeprefix("data: ").strip())
        for chunk in chunks
        if chunk.startswith("data: ")
    ]

    assert payloads[0]["type"] == "job_summary"
    assert payloads[0]["job"]["profile"] == "balanced"
    assert payloads[0]["job"]["include_languages"] == ["python"]
    assert payloads[0]["job"]["include_paths"] == ["src/**"]
    assert payloads[0]["job"]["exclude_paths"] == ["tests/**"]
    assert payloads[1]["type"] == "log"


def _chunk_payload() -> dict:
    return {
        "code": "def useful_retry(value):\n    return value\n",
        "file_path": "service.py",
        "language": "python",
        "symbol_name": "useful_retry",
        "symbol_type": "function",
        "line_start": 1,
        "line_end": 2,
    }
