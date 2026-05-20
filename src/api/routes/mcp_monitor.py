"""MCP monitor endpoints for starting and observing an HTTP MCP server."""

import asyncio
import json
import os
import sys
import time
from collections import deque
from contextlib import suppress
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

router = APIRouter(prefix="/mcp", tags=["mcp"])

MCP_HTTP_HOST = os.getenv("PATTERN_VAULT_MCP_MONITOR_HOST", "127.0.0.1")
MCP_HTTP_PORT = int(os.getenv("PATTERN_VAULT_MCP_MONITOR_PORT", "8002"))
ROOT_DIR = Path(__file__).resolve().parents[3]
LOG_BUFFER_LINES = 500

MCP_TOOLS = [
    {
        "name": "search_patterns",
        "mode": "read",
        "description": "FTS5+BM25 search over stored patterns.",
    },
    {
        "name": "get_pattern",
        "mode": "read",
        "description": "Fetch one pattern with full code and metadata.",
    },
    {
        "name": "add_pattern",
        "mode": "write",
        "description": "Manually store a new pattern in the vault.",
    },
    {
        "name": "save_insight",
        "mode": "write",
        "description": "Store a repository-level insight.",
    },
    {
        "name": "list_tags",
        "mode": "read",
        "description": "List all known tags, optionally filtered by category.",
    },
    {
        "name": "list_categories",
        "mode": "read",
        "description": "List all pattern categories.",
    },
    {
        "name": "vault_stats",
        "mode": "read",
        "description": "Return current pattern, chunk, and insight counts.",
    },
    {
        "name": "reindex",
        "mode": "write",
        "description": "Run the full indexing pipeline for a target path.",
    },
]


class MCPServerMonitor:
    def __init__(self) -> None:
        self.process: asyncio.subprocess.Process | None = None
        self.started_at: float | None = None
        self.command: list[str] = []
        self._log_buffer: deque[str] = deque(maxlen=LOG_BUFFER_LINES)
        self._subscribers: set[asyncio.Queue[str]] = set()
        self._stream_tasks: list[asyncio.Task[None]] = []
        self._lock = asyncio.Lock()

    def _is_running(self) -> bool:
        return self.process is not None and self.process.returncode is None

    def _append_log(self, line: str) -> None:
        self._log_buffer.append(line)
        stale: list[asyncio.Queue[str]] = []
        for queue in self._subscribers:
            try:
                queue.put_nowait(line)
            except asyncio.QueueFull:
                stale.append(queue)
        for queue in stale:
            self._subscribers.discard(queue)

    async def _pump_stream(self, stream: asyncio.StreamReader | None, label: str) -> None:
        if stream is None:
            return
        while True:
            line = await stream.readline()
            if not line:
                break
            text = line.decode("utf-8", errors="replace").rstrip()
            if text:
                self._append_log(f"[{label}] {text}")

    async def _watch_process(self, process: asyncio.subprocess.Process) -> None:
        code = await process.wait()
        self._append_log(f"[monitor] MCP server exited with code {code}")

    async def start(self) -> dict:
        async with self._lock:
            if self._is_running():
                return self.status()

            if self.process is not None and self.process.returncode is not None:
                self.process = None
                self.started_at = None
                self.command = []

            command = [
                sys.executable,
                "-m",
                "src.cli",
                "serve",
                "--transport",
                "http",
                "--host",
                MCP_HTTP_HOST,
                "--port",
                str(MCP_HTTP_PORT),
            ]
            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"

            try:
                process = await asyncio.create_subprocess_exec(
                    *command,
                    cwd=str(ROOT_DIR),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=env,
                )
            except OSError as exc:
                raise HTTPException(status_code=500, detail=f"Failed to start MCP server: {exc}") from exc

            self.process = process
            self.started_at = time.time()
            self.command = command
            self._append_log(
                f"[monitor] Starting MCP HTTP server on {MCP_HTTP_HOST}:{MCP_HTTP_PORT}"
            )
            self._stream_tasks = [
                asyncio.create_task(self._pump_stream(process.stdout, "stdout")),
                asyncio.create_task(self._pump_stream(process.stderr, "stderr")),
                asyncio.create_task(self._watch_process(process)),
            ]

            await asyncio.sleep(0.2)
            if process.returncode is not None:
                detail = f"MCP server exited immediately with code {process.returncode}"
                raise HTTPException(status_code=409, detail=detail)

            return self.status()

    async def stop(self) -> dict:
        async with self._lock:
            if not self.process:
                return self.status()

            process = self.process
            if process.returncode is None:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=5)
                except asyncio.TimeoutError:
                    process.kill()
                    await process.wait()

            for task in self._stream_tasks:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
            self._stream_tasks = []
            self.process = None
            self.started_at = None
            self.command = []
            self._append_log("[monitor] MCP server stopped")

            return self.status()

    async def shutdown(self) -> None:
        await self.stop()

    def status(self) -> dict:
        running = self._is_running()
        return {
            "running": running,
            "pid": self.process.pid if running and self.process else None,
            "host": MCP_HTTP_HOST,
            "port": MCP_HTTP_PORT,
            "uptime_seconds": round(time.time() - self.started_at, 1) if running and self.started_at else None,
            "command": self.command,
        }

    def subscribe(self) -> asyncio.Queue[str]:
        queue: asyncio.Queue[str] = asyncio.Queue(maxsize=200)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[str]) -> None:
        self._subscribers.discard(queue)

    def snapshot_logs(self) -> list[str]:
        return list(self._log_buffer)


def _get_monitor(request: Request) -> MCPServerMonitor:
    monitor = getattr(request.app.state, "mcp_monitor", None)
    if monitor is None:
        raise HTTPException(status_code=500, detail="MCP monitor is not initialised")
    return monitor


@router.get("/status")
async def mcp_status(request: Request):
    return _get_monitor(request).status()


@router.post("/start")
async def start_mcp(request: Request):
    return await _get_monitor(request).start()


@router.post("/stop")
async def stop_mcp(request: Request):
    return await _get_monitor(request).stop()


@router.get("/tools")
async def mcp_tools():
    return {"tools": MCP_TOOLS}


@router.get("/logs/stream")
async def stream_logs(request: Request):
    monitor = _get_monitor(request)

    async def event_stream():
        queue = monitor.subscribe()
        try:
            for line in monitor.snapshot_logs():
                yield f"data: {json.dumps({'type': 'log', 'line': line})}\n\n"

            while True:
                if await request.is_disconnected():
                    break
                try:
                    line = await asyncio.wait_for(queue.get(), timeout=15)
                    yield f"data: {json.dumps({'type': 'log', 'line': line})}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            monitor.unsubscribe(queue)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
