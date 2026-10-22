"""FastAPI application for Pattern Vault frontend."""

from collections.abc import Sequence
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from pattern_vault.api.deps import DB_PATH
from pattern_vault.api.routes import chat, history, insights, mcp_monitor, patterns, stats, usage, workspace
from pattern_vault.api.routes.mcp_monitor import MCPServerMonitor
from pattern_vault.api.routes.workspace import WorkspaceIndexManager
from pattern_vault.store.db import get_connection, init_db

# Built UI: inside the installed package, or web/dist in a source checkout
PACKAGE_WEB_DIST = Path(__file__).resolve().parents[1] / "web_dist"
CHECKOUT_WEB_DIST = Path(__file__).resolve().parents[2] / "web" / "dist"
LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.mcp_monitor = MCPServerMonitor()
    app.state.workspace_index_manager = WorkspaceIndexManager()
    conn = get_connection(DB_PATH)
    init_db(conn)
    conn.close()
    try:
        yield
    finally:
        await app.state.mcp_monitor.shutdown()


def default_web_dist() -> Path | None:
    for candidate in (PACKAGE_WEB_DIST, CHECKOUT_WEB_DIST):
        if (candidate / "index.html").is_file():
            return candidate
    return None


def host_allowed(host_header: str, allowed: set[str]) -> bool:
    """Check a Host header (with optional port, IPv6 in brackets) against allowed hostnames."""
    host = host_header.strip().lower()
    if host.startswith("["):
        host = host[1:].split("]", 1)[0]
    elif host.count(":") == 1:
        host = host.split(":", 1)[0]
    return bool(host) and host in allowed


def create_app(
    web_dist: Path | None = None,
    extra_hosts: Sequence[str] = (),
    allow_any_host: bool = False,
) -> FastAPI:
    app = FastAPI(title="Pattern Vault", version="0.2.0", lifespan=lifespan)
    allowed_hosts = LOOPBACK_HOSTS | {host.lower().strip("[]") for host in extra_hosts}

    # Rejecting unknown Host headers stops DNS-rebinding pages from reaching the API.
    @app.middleware("http")
    async def check_host(request: Request, call_next):
        if not allow_any_host and not host_allowed(request.headers.get("host", ""), allowed_hosts):
            return JSONResponse({"detail": "Invalid host header"}, status_code=400)
        return await call_next(request)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(chat.router, prefix="/api")
    app.include_router(history.router, prefix="/api")
    app.include_router(insights.router, prefix="/api")
    app.include_router(patterns.router, prefix="/api")
    app.include_router(stats.router, prefix="/api")
    app.include_router(usage.router, prefix="/api")
    app.include_router(workspace.router, prefix="/api")
    app.include_router(mcp_monitor.router, prefix="/api")

    if web_dist is not None:
        app.mount("/", StaticFiles(directory=web_dist, html=True), name="ui")

    return app


app = create_app(web_dist=default_web_dist())
