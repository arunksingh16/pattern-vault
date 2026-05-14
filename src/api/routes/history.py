"""Chat history endpoints — list sessions, get messages, delete."""

import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from src.api.deps import get_db
from src.store.db import list_sessions, get_session_messages, delete_session, get_latest_session_for_repo

router = APIRouter(prefix="/history", tags=["history"])


@router.get("")
def get_sessions(limit: int = 50, conn: sqlite3.Connection = Depends(get_db)):
    return list_sessions(conn, limit)


@router.get("/repo/{owner}/{repo}")
def get_session_for_repo(owner: str, repo: str, conn: sqlite3.Connection = Depends(get_db)):
    session = get_latest_session_for_repo(conn, f"{owner}/{repo}")
    if not session:
        raise HTTPException(status_code=404, detail="No session found for this repo")
    return session


@router.get("/{session_id}")
def get_session(session_id: int, conn: sqlite3.Connection = Depends(get_db)):
    messages = get_session_messages(conn, session_id)
    if not messages:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"session_id": session_id, "messages": messages}


@router.delete("/{session_id}")
def remove_session(session_id: int, conn: sqlite3.Connection = Depends(get_db)):
    if not delete_session(conn, session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    return {"status": "deleted"}
