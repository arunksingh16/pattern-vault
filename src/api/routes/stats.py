"""Vault statistics, health, and taxonomy endpoints."""

import sqlite3
from typing import Optional

from fastapi import APIRouter, Depends, Query

from src.api.deps import DB_PATH, get_db
from src.client import describe_backend
from src.store.db import get_stats, list_categories, list_tags

router = APIRouter(tags=["stats"])


@router.get("/health")
def health():
    try:
        backend = describe_backend()
    except Exception as e:
        backend = f"not configured: {e}"
    return {
        "status": "ok",
        "backend": backend,
        "db_path": str(DB_PATH),
    }


@router.get("/stats")
def vault_stats(conn: sqlite3.Connection = Depends(get_db)):
    return get_stats(conn)


@router.get("/categories")
def categories(conn: sqlite3.Connection = Depends(get_db)):
    return list_categories(conn)


@router.get("/tags")
def tags(
    category: Optional[str] = Query(None),
    conn: sqlite3.Connection = Depends(get_db),
):
    return list_tags(conn, category=category)
