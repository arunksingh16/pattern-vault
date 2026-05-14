"""FastAPI application for Pattern Vault frontend."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.deps import DB_PATH
from src.api.routes import chat, history, insights, patterns, stats, workspace
from src.store.db import get_connection, init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    conn = get_connection(DB_PATH)
    init_db(conn)
    conn.close()
    yield


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
app.include_router(workspace.router, prefix="/api")
