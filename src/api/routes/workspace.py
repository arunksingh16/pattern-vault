"""Workspace file tree, clone, and indexing endpoints for the Explorer panel."""

import asyncio
import json
import re
import time
from pathlib import Path
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from src.agent.tools import get_workspace_roots, _tool_clone_github_repo
from src.api.deps import DB_PATH
from src.indexer.batch import index_directory
from src.indexer.profiles import DEFAULT_INDEXING_PROFILE, get_indexing_profile
from src.store.db import (
    append_index_job_event,
    create_index_job,
    get_cloned_repo,
    get_connection,
    get_index_job,
    get_index_job_events,
    init_db,
    list_cloned_repos,
    list_index_jobs,
    update_index_job,
)

router = APIRouter(prefix="/workspace", tags=["workspace"])

_FOUND_RE = re.compile(r"^Found (\d+) files \((\d+) skipped\)$")
_EXTRACTED_RE = re.compile(r"^Extracted (\d+) chunks from (\d+) files$")
_BATCH_RE = re.compile(r"^Extracting patterns from chunks (\d+)-(\d+)\.\.\.$")
_STORED_RE = re.compile(r"^Stored: \[([^\]]+)\] (.+)$")
_DONE_RE = re.compile(r"^Done\. Found (\d+) patterns, stored (\d+)\.$")
TERMINAL_INDEX_STATUSES = {"completed", "completed_with_errors", "failed"}


def _job_summary_event(job_snapshot: dict) -> dict:
    return {
        "type": "job_summary",
        "job": job_snapshot,
        "status": job_snapshot.get("status"),
        "stats": dict(job_snapshot.get("stats") or {}),
    }


def _validate_workspace_dir(path: str | Path) -> Path:
    target = Path(path).expanduser().resolve()
    roots = get_workspace_roots()

    if not any(target == r or r in target.parents or target in r.parents for r in roots):
        raise HTTPException(status_code=403, detail="Path outside workspace roots")

    if not target.is_dir():
        raise HTTPException(status_code=404, detail="Not a directory")

    return target


class IndexTarget(BaseModel):
    owner: str
    repo: str


class IndexRequest(BaseModel):
    path: str | None = None
    repo: IndexTarget | None = None
    dry_run: bool = False
    profile: Literal["curated", "balanced", "comprehensive"] = DEFAULT_INDEXING_PROFILE
    include_languages: list[str] = []
    include_paths: list[str] = []
    exclude_paths: list[str] = []


def _summarize_index_errors(errors: list[str]) -> str:
    suffix = "" if len(errors) == 1 else "s"
    return f"Completed with {len(errors)} error{suffix}. First error: {errors[0]}"


class WorkspaceIndexJob:
    def __init__(
        self,
        job_id: str,
        title: str,
        source_kind: str,
        path: Path,
        repo_name: str | None,
        dry_run: bool,
        profile: str,
        include_languages: list[str] | None = None,
        include_paths: list[str] | None = None,
        exclude_paths: list[str] | None = None,
    ) -> None:
        self.job_id = job_id
        self.title = title
        self.source_kind = source_kind
        self.path = path
        self.repo_name = repo_name
        self.dry_run = dry_run
        self.profile = profile
        self.include_languages = include_languages or []
        self.include_paths = include_paths or []
        self.exclude_paths = exclude_paths or []
        self.status = "queued"
        self.created_at = time.time()
        self.updated_at = self.created_at
        self.started_at: float | None = None
        self.finished_at: float | None = None
        self.history: list[dict] = []
        self.subscribers: set[asyncio.Queue[dict]] = set()
        self.stats = {
            "files_discovered": 0,
            "files_skipped": 0,
            "files_scanned": 0,
            "chunks_extracted": 0,
            "patterns_found": 0,
            "patterns_stored": 0,
            "patterns_rejected": 0,
            "current_stage": "queued",
        }
        self.error: str | None = None
        self.task: asyncio.Task[None] | None = None

    def snapshot(self) -> dict:
        return {
            "job_id": self.job_id,
            "title": self.title,
            "source_kind": self.source_kind,
            "status": self.status,
            "path": str(self.path),
            "repo_name": self.repo_name,
            "dry_run": self.dry_run,
            "profile": self.profile,
            "include_languages": list(self.include_languages),
            "include_paths": list(self.include_paths),
            "exclude_paths": list(self.exclude_paths),
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "stats": dict(self.stats),
            "error": self.error,
        }

    def publish(self, event: dict) -> None:
        self.updated_at = time.time()
        self.history.append(event)
        conn = get_connection(DB_PATH)
        try:
            init_db(conn)
            append_index_job_event(conn, self.job_id, event)
        finally:
            conn.close()
        stale: list[asyncio.Queue[dict]] = []
        for queue in self.subscribers:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                stale.append(queue)
        for queue in stale:
            self.subscribers.discard(queue)

    def subscribe(self) -> asyncio.Queue[dict]:
        queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=200)
        self.subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict]) -> None:
        self.subscribers.discard(queue)

    def apply_progress_line(self, line: str) -> dict:
        clean_line = line.strip()
        event: dict = {"type": "log", "message": clean_line, "stats": dict(self.stats)}

        if clean_line.startswith("Scanning "):
            self.stats["current_stage"] = "scan"
            event["stage"] = "scan"
        elif match := _FOUND_RE.match(clean_line):
            self.stats["files_discovered"] = int(match.group(1))
            self.stats["files_skipped"] = int(match.group(2))
        elif match := _EXTRACTED_RE.match(clean_line):
            self.stats["chunks_extracted"] = int(match.group(1))
            self.stats["files_scanned"] = int(match.group(2))
        elif match := _BATCH_RE.match(clean_line):
            self.stats["current_stage"] = "extract"
            event["type"] = "batch"
            event["stage"] = "extract"
            event["range_start"] = int(match.group(1))
            event["range_end"] = int(match.group(2))
        elif match := _STORED_RE.match(clean_line):
            self.stats["current_stage"] = "store"
            self.stats["patterns_stored"] += 1
            event = {
                "type": "pattern_found",
                "category": match.group(1),
                "name": match.group(2).strip(),
                "message": clean_line,
                "stats": dict(self.stats),
                "stage": "store",
            }
        elif clean_line == "Dry run — skipping extraction and storage.":
            self.stats["current_stage"] = "dry-run"
            event["stage"] = "dry-run"
        elif clean_line == "No new chunks to process.":
            self.stats["current_stage"] = "complete"
            event["stage"] = "complete"
        elif match := _DONE_RE.match(clean_line):
            self.stats["current_stage"] = "complete"
            self.stats["patterns_found"] = int(match.group(1))
            self.stats["patterns_stored"] = int(match.group(2))
            event["stage"] = "complete"

        event["stats"] = dict(self.stats)
        return event


class WorkspaceIndexManager:
    def __init__(self) -> None:
        self.jobs: dict[str, WorkspaceIndexJob] = {}
        self._lock = asyncio.Lock()

    async def create_job(
        self,
        path: Path,
        title: str,
        source_kind: str,
        repo_name: str | None,
        dry_run: bool,
        profile: str = DEFAULT_INDEXING_PROFILE,
        include_languages: list[str] | None = None,
        include_paths: list[str] | None = None,
        exclude_paths: list[str] | None = None,
    ) -> WorkspaceIndexJob:
        async with self._lock:
            self.cleanup()
            job_id = uuid4().hex
            job = WorkspaceIndexJob(
                job_id,
                title,
                source_kind,
                path,
                repo_name,
                dry_run,
                profile,
                include_languages,
                include_paths,
                exclude_paths,
            )
            conn = get_connection(DB_PATH)
            try:
                init_db(conn)
                create_index_job(
                    conn,
                    job_id,
                    title,
                    source_kind,
                    str(path),
                    repo_name=repo_name,
                    dry_run=dry_run,
                    index_profile=profile,
                    include_languages=include_languages,
                    include_paths=include_paths,
                    exclude_paths=exclude_paths,
                    status=job.status,
                    stats=job.stats,
                )
            finally:
                conn.close()
            self.jobs[job_id] = job
            job.publish({
                "type": "status",
                "message": "Index job queued.",
                "stats": dict(job.stats),
            })
            job.task = asyncio.create_task(self._run_job(job))
            return job

    async def _run_job(self, job: WorkspaceIndexJob) -> None:
        loop = asyncio.get_running_loop()
        job.status = "running"
        job.started_at = time.time()
        job.stats["current_stage"] = "scan"
        conn = get_connection(DB_PATH)
        try:
            init_db(conn)
            update_index_job(
                conn,
                job.job_id,
                status=job.status,
                stats=job.stats,
                started_at=job.started_at,
            )
        finally:
            conn.close()
        job.publish({
            "type": "status",
            "message": "Index job started.",
            "stats": dict(job.stats),
        })

        def on_progress(message: str) -> None:
            event = job.apply_progress_line(message)
            loop.call_soon_threadsafe(job.publish, event)

        try:
            stats = await asyncio.to_thread(
                index_directory,
                job.path,
                DB_PATH,
                job.repo_name,
                None,
                on_progress,
                job.dry_run,
                job.profile,
                job.include_languages,
                job.include_paths,
                job.exclude_paths,
            )
            job.stats.update(
                {
                    "files_scanned": stats.files_scanned,
                    "files_skipped": stats.files_skipped,
                    "chunks_extracted": stats.chunks_extracted,
                    "patterns_found": stats.patterns_found,
                    "patterns_stored": stats.patterns_stored,
                    "patterns_rejected": stats.patterns_rejected,
                    "current_stage": "complete",
                }
            )
            if stats.errors:
                job.status = "completed_with_errors"
                job.error = _summarize_index_errors(stats.errors)
                for err in stats.errors:
                    job.publish({
                        "type": "error",
                        "message": err,
                        "recoverable": True,
                        "stats": dict(job.stats),
                    })
            else:
                job.status = "completed"

            job.finished_at = time.time()
            conn = get_connection(DB_PATH)
            try:
                init_db(conn)
                update_index_job(
                    conn,
                    job.job_id,
                    status=job.status,
                    stats=job.stats,
                    error=job.error,
                    finished_at=job.finished_at,
                )
            finally:
                conn.close()
            job.publish({
                "type": "done",
                "message": job.error or "Index job completed.",
                "status": job.status,
                "stats": dict(job.stats),
                "errors": list(stats.errors),
            })
        except Exception as exc:
            job.status = "failed"
            job.finished_at = time.time()
            job.error = str(exc)
            conn = get_connection(DB_PATH)
            try:
                init_db(conn)
                update_index_job(
                    conn,
                    job.job_id,
                    status=job.status,
                    stats=job.stats,
                    error=job.error,
                    finished_at=job.finished_at,
                )
            finally:
                conn.close()
            job.publish({
                "type": "error",
                "message": str(exc),
                "status": job.status,
                "recoverable": False,
                "stats": dict(job.stats),
            })

    def get_job(self, job_id: str) -> WorkspaceIndexJob | None:
        self.cleanup()
        return self.jobs.get(job_id)

    def cleanup(self) -> None:
        cutoff = time.time() - 3600
        stale = [
            job_id
            for job_id, job in self.jobs.items()
            if job.finished_at is not None and job.finished_at < cutoff
        ]
        for job_id in stale:
            self.jobs.pop(job_id, None)


def _get_index_manager(request: Request) -> WorkspaceIndexManager:
    manager = getattr(request.app.state, "workspace_index_manager", None)
    if manager is None:
        raise HTTPException(status_code=500, detail="Workspace index manager is not initialised")
    return manager


@router.get("/roots")
def get_roots():
    roots = get_workspace_roots()
    return [{"path": str(r), "name": r.name} for r in roots]


@router.get("/tree")
def get_tree(path: str = Query(...)):
    target = _validate_workspace_dir(path)

    entries = []
    try:
        for entry in sorted(target.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower())):
            if entry.name.startswith('.'):
                continue
            if entry.name in ('node_modules', '__pycache__', 'venv', '.git', 'dist', 'build'):
                continue
            entries.append({
                "name": entry.name,
                "path": str(entry),
                "is_dir": entry.is_dir(),
                "size": entry.stat().st_size if entry.is_file() else None,
            })
    except PermissionError:
        raise HTTPException(status_code=403, detail="Permission denied")

    return entries


class CloneRequest(BaseModel):
    url: str


@router.post("/clone")
def clone_repo(req: CloneRequest):
    """Clone a public GitHub repo and register it in the DB."""
    import json
    result_str = _tool_clone_github_repo(req.url, DB_PATH)
    result = json.loads(result_str)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.get("/cloned")
def list_cloned():
    """List all previously cloned repos."""
    conn = get_connection(DB_PATH)
    try:
        init_db(conn)
        return list_cloned_repos(conn)
    finally:
        conn.close()


@router.post("/index")
async def start_index(request: Request, req: IndexRequest):
    if bool(req.path) == bool(req.repo):
        raise HTTPException(status_code=400, detail="Provide exactly one of path or repo")
    try:
        profile = get_indexing_profile(req.profile).name
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    repo_name: str | None = None
    source_kind = "path"
    title: str
    if req.path:
        target = _validate_workspace_dir(req.path)
        repo_name = target.name
        title = repo_name
    else:
        conn = get_connection(DB_PATH)
        try:
            init_db(conn)
            record = get_cloned_repo(conn, req.repo.owner, req.repo.repo)
        finally:
            conn.close()

        if not record:
            raise HTTPException(status_code=404, detail="Cloned repo not found")
        target = Path(record["local_path"]).resolve()
        if not target.is_dir():
            raise HTTPException(status_code=404, detail="Cloned repo path not found on disk")
        repo_name = f"{req.repo.owner}/{req.repo.repo}"
        title = repo_name
        source_kind = "repo"

    job = await _get_index_manager(request).create_job(
        target,
        title,
        source_kind,
        repo_name,
        req.dry_run,
        profile,
        req.include_languages,
        req.include_paths,
        req.exclude_paths,
    )
    return job.snapshot()


@router.get("/index-jobs")
def get_recent_index_jobs(limit: int = Query(20, ge=1, le=100)):
    conn = get_connection(DB_PATH)
    try:
        init_db(conn)
        return list_index_jobs(conn, limit=limit)
    finally:
        conn.close()


@router.get("/index/{job_id}")
async def get_index_status(job_id: str, request: Request):
    job = _get_index_manager(request).get_job(job_id)
    if job:
        return job.snapshot()

    conn = get_connection(DB_PATH)
    try:
        init_db(conn)
        record = get_index_job(conn, job_id)
    finally:
        conn.close()
    if not record:
        raise HTTPException(status_code=404, detail="Index job not found")
    return record


@router.get("/index/{job_id}/stream")
async def stream_index(job_id: str, request: Request):
    job = _get_index_manager(request).get_job(job_id)
    db_job: dict | None = None
    db_events: list[dict] = []
    if not job:
        conn = get_connection(DB_PATH)
        try:
            init_db(conn)
            db_job = get_index_job(conn, job_id)
            if db_job:
                db_events = get_index_job_events(conn, job_id)
        finally:
            conn.close()
        if not db_job:
            raise HTTPException(status_code=404, detail="Index job not found")

    async def event_stream():
        if not job:
            yield f"data: {json.dumps(_job_summary_event(db_job))}\n\n"
            for event in db_events:
                yield f"data: {json.dumps(event)}\n\n"
            return

        queue = job.subscribe()
        try:
            yield f"data: {json.dumps(_job_summary_event(job.snapshot()))}\n\n"
            for event in job.history:
                yield f"data: {json.dumps(event)}\n\n"

            while True:
                if await request.is_disconnected():
                    break

                if job.status in TERMINAL_INDEX_STATUSES and queue.empty():
                    break

                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                    yield f"data: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            job.unsubscribe(queue)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
