"""Token usage aggregation endpoints."""

import sqlite3

from fastapi import APIRouter, Depends, Query

from src.api.deps import get_db
from src.store.db import get_daily_token_usage

router = APIRouter(prefix="/usage", tags=["usage"])


@router.get("/daily")
def daily_usage(
    days: int = Query(14, ge=1, le=90),
    conn: sqlite3.Connection = Depends(get_db),
):
    return get_daily_token_usage(conn, days=days)
