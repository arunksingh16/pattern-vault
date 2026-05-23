"""Insights CRUD endpoints."""

import sqlite3

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from pattern_vault.api.deps import get_db
from pattern_vault.store.db import insert_insight, list_insights, get_insight, delete_insight

router = APIRouter(prefix="/insights", tags=["insights"])


class InsightCreate(BaseModel):
    repo_path: str
    insight_text: str
    tags: list[str] = []


@router.get("")
def get_insights(
    limit: int = 50,
    offset: int = 0,
    conn: sqlite3.Connection = Depends(get_db),
):
    return list_insights(conn, limit, offset)


@router.get("/{insight_id}")
def get_one_insight(insight_id: int, conn: sqlite3.Connection = Depends(get_db)):
    result = get_insight(conn, insight_id)
    if not result:
        raise HTTPException(status_code=404, detail="Insight not found")
    return result


@router.post("")
def create_insight(body: InsightCreate, conn: sqlite3.Connection = Depends(get_db)):
    insight_id = insert_insight(conn, body.repo_path, body.insight_text, body.tags)
    return {"id": insight_id}


@router.delete("/{insight_id}")
def remove_insight(insight_id: int, conn: sqlite3.Connection = Depends(get_db)):
    if not delete_insight(conn, insight_id):
        raise HTTPException(status_code=404, detail="Insight not found")
    return {"status": "deleted"}
