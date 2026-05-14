"""Pattern CRUD and search endpoints."""

import sqlite3
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from src.api.deps import get_db
from src.store.db import (
    delete_pattern,
    get_pattern,
    insert_pattern,
    search_fts,
    update_pattern,
)

router = APIRouter(tags=["patterns"])


class PatternCreate(BaseModel):
    name: str
    summary: str
    code_text: str
    category: str = "general"
    language: str = "unknown"
    tags: list[str] = []
    quality_signal: Optional[str] = None
    source_repo: Optional[str] = None
    source_file: Optional[str] = None
    line_start: Optional[int] = None
    line_end: Optional[int] = None


class PatternUpdate(BaseModel):
    name: Optional[str] = None
    summary: Optional[str] = None
    category: Optional[str] = None
    language: Optional[str] = None
    tags: Optional[list[str]] = None
    quality_signal: Optional[str] = None
    source_repo: Optional[str] = None
    source_file: Optional[str] = None
    line_start: Optional[int] = None
    line_end: Optional[int] = None
    code_text: Optional[str] = None
    user_notes: Optional[str] = None


@router.get("/patterns")
def list_patterns(
    limit: int = Query(25, ge=1, le=100),
    conn: sqlite3.Connection = Depends(get_db),
):
    rows = conn.execute(
        """SELECT id, name, category, language, tags, summary, source_repo,
                  source_file, line_start, line_end, updated_at
           FROM patterns ORDER BY updated_at DESC, id DESC LIMIT ?""",
        (limit,),
    ).fetchall()
    import json
    return [
        {**dict(row), "tags": json.loads(row["tags"])} for row in rows
    ]


@router.get("/patterns/search")
def search_patterns(
    q: str = Query(..., min_length=1),
    category: Optional[str] = None,
    language: Optional[str] = None,
    limit: int = Query(10, ge=1, le=50),
    conn: sqlite3.Connection = Depends(get_db),
):
    return search_fts(conn, q, category=category, language=language, limit=limit)


@router.get("/patterns/{pattern_id}")
def get_pattern_detail(
    pattern_id: int,
    conn: sqlite3.Connection = Depends(get_db),
):
    pattern = get_pattern(conn, pattern_id)
    if not pattern:
        raise HTTPException(status_code=404, detail="Pattern not found")
    return pattern


@router.post("/patterns", status_code=201)
def create_pattern(
    body: PatternCreate,
    conn: sqlite3.Connection = Depends(get_db),
):
    pattern_id = insert_pattern(
        conn,
        name=body.name,
        summary=body.summary,
        code_text=body.code_text,
        category=body.category,
        language=body.language,
        tags=body.tags,
        quality_signal=body.quality_signal,
        source_repo=body.source_repo,
        source_file=body.source_file,
        line_start=body.line_start,
        line_end=body.line_end,
    )
    return {"id": pattern_id}


@router.patch("/patterns/{pattern_id}")
def patch_pattern(
    pattern_id: int,
    body: PatternUpdate,
    conn: sqlite3.Connection = Depends(get_db),
):
    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    try:
        ok = update_pattern(conn, pattern_id, **updates)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    if not ok:
        raise HTTPException(status_code=404, detail="Pattern not found")
    return {"status": "updated"}


@router.delete("/patterns/{pattern_id}")
def remove_pattern(
    pattern_id: int,
    conn: sqlite3.Connection = Depends(get_db),
):
    if not delete_pattern(conn, pattern_id):
        raise HTTPException(status_code=404, detail="Pattern not found")
    return {"status": "deleted"}
