"""Shared FastAPI dependencies."""

import sqlite3
from collections.abc import Generator

from pattern_vault.store.db import get_connection, init_db, resolve_db_path

DB_PATH = resolve_db_path()


def get_db() -> Generator[sqlite3.Connection, None, None]:
    conn = get_connection(DB_PATH)
    init_db(conn)
    try:
        yield conn
    finally:
        conn.close()
