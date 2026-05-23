"""FastAPI application for Pattern Vault frontend."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from pattern_vault.api.deps import DB_PATH
from pattern_vault.api.routes import chat, history, insights, mcp_monitor, patterns, stats, usage, workspace
from pattern_vault.api.routes.mcp_monitor import MCPServerMonitor
from pattern_vault.api.routes.workspace import WorkspaceIndexManager
from pattern_vault.store.db import get_connection, init_db


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


app = FastAPI(title="Pattern Vault", version="0.1.0", lifespan=lifespan)

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
