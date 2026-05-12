"""
Pattern Vault — SQLite storage layer.

Schema: patterns, chunks, repo_insights tables + FTS5 virtual table.
Uses sqlite-vec for vector search when available, falls back to FTS-only.
"""

import sqlite3
import json
import hashlib
import time
from pathlib import Path
from typing import Optional

DB_VERSION = 1
DEFAULT_DB_PATH = Path.home() / ".pattern-vault" / "patterns.db"


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def get_connection(db_path: Optional[Path] = None) -> sqlite3.Connection:
    """Get a connection to the pattern vault database."""
    path = db_path or DEFAULT_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Create tables if they don't exist."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS patterns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT 'general',
            language TEXT NOT NULL DEFAULT 'unknown',
            tags TEXT NOT NULL DEFAULT '[]',
            summary TEXT NOT NULL,
            quality_signal TEXT DEFAULT NULL,
            source_repo TEXT DEFAULT NULL,
            source_file TEXT DEFAULT NULL,
            line_start INTEGER DEFAULT NULL,
            line_end INTEGER DEFAULT NULL,
            content_hash TEXT NOT NULL,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pattern_id INTEGER NOT NULL,
            code_text TEXT NOT NULL,
            chunk_type TEXT NOT NULL DEFAULT 'implementation',
            embedding BLOB DEFAULT NULL,
            FOREIGN KEY (pattern_id) REFERENCES patterns(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS repo_insights (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            repo_path TEXT NOT NULL,
            insight_text TEXT NOT NULL,
            tags TEXT NOT NULL DEFAULT '[]',
            created_at REAL NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_patterns_category ON patterns(category);
        CREATE INDEX IF NOT EXISTS idx_patterns_language ON patterns(language);
        CREATE INDEX IF NOT EXISTS idx_patterns_hash ON patterns(content_hash);
        CREATE INDEX IF NOT EXISTS idx_chunks_pattern ON chunks(pattern_id);
        CREATE INDEX IF NOT EXISTS idx_insights_repo ON repo_insights(repo_path);
    """)

    # FTS5 virtual table for full-text search
    # Check if it exists first (can't use IF NOT EXISTS with virtual tables in all versions)
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='patterns_fts'"
    )
    if cursor.fetchone() is None:
        conn.execute("""
            CREATE VIRTUAL TABLE patterns_fts USING fts5(
                name, summary, tags, category, language,
                content=patterns,
                content_rowid=id,
                tokenize='porter unicode61'
            )
        """)
        # Triggers to keep FTS in sync
        conn.executescript("""
            CREATE TRIGGER IF NOT EXISTS patterns_ai AFTER INSERT ON patterns BEGIN
                INSERT INTO patterns_fts(rowid, name, summary, tags, category, language)
                VALUES (new.id, new.name, new.summary, new.tags, new.category, new.language);
            END;

            CREATE TRIGGER IF NOT EXISTS patterns_ad AFTER DELETE ON patterns BEGIN
                INSERT INTO patterns_fts(patterns_fts, rowid, name, summary, tags, category, language)
                VALUES ('delete', old.id, old.name, old.summary, old.tags, old.category, old.language);
            END;

            CREATE TRIGGER IF NOT EXISTS patterns_au AFTER UPDATE ON patterns BEGIN
                INSERT INTO patterns_fts(patterns_fts, rowid, name, summary, tags, category, language)
                VALUES ('delete', old.id, old.name, old.summary, old.tags, old.category, old.language);
                INSERT INTO patterns_fts(rowid, name, summary, tags, category, language)
                VALUES (new.id, new.name, new.summary, new.tags, new.category, new.language);
            END;
        """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS db_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)
    conn.execute(
        "INSERT OR REPLACE INTO db_meta (key, value) VALUES ('version', ?)",
        (str(DB_VERSION),),
    )
    conn.commit()


# ── CRUD operations ──────────────────────────────────────────────

def insert_pattern(
    conn: sqlite3.Connection,
    name: str,
    summary: str,
    code_text: str,
    category: str = "general",
    language: str = "unknown",
    tags: Optional[list[str]] = None,
    quality_signal: Optional[str] = None,
    source_repo: Optional[str] = None,
    source_file: Optional[str] = None,
    line_start: Optional[int] = None,
    line_end: Optional[int] = None,
    chunk_type: str = "implementation",
    embedding: Optional[bytes] = None,
) -> int:
    """Insert a pattern and its code chunk. Returns the pattern ID."""
    now = time.time()
    chash = _content_hash(code_text)
    tags_json = json.dumps(tags or [])

    # Check for existing pattern with same hash
    existing = conn.execute(
        "SELECT id FROM patterns WHERE content_hash = ?", (chash,)
    ).fetchone()
    if existing:
        return existing["id"]

    cursor = conn.execute(
        """INSERT INTO patterns
           (name, category, language, tags, summary, quality_signal,
            source_repo, source_file, line_start, line_end,
            content_hash, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            name, category, language, tags_json, summary, quality_signal,
            source_repo, source_file, line_start, line_end,
            chash, now, now,
        ),
    )
    pattern_id = cursor.lastrowid

    conn.execute(
        """INSERT INTO chunks (pattern_id, code_text, chunk_type, embedding)
           VALUES (?, ?, ?, ?)""",
        (pattern_id, code_text, chunk_type, embedding),
    )
    conn.commit()
    return pattern_id


def insert_insight(
    conn: sqlite3.Connection,
    repo_path: str,
    insight_text: str,
    tags: Optional[list[str]] = None,
) -> int:
    """Insert a repo insight. Returns the insight ID."""
    cursor = conn.execute(
        """INSERT INTO repo_insights (repo_path, insight_text, tags, created_at)
           VALUES (?, ?, ?, ?)""",
        (repo_path, insight_text, json.dumps(tags or []), time.time()),
    )
    conn.commit()
    return cursor.lastrowid


def get_pattern(conn: sqlite3.Connection, pattern_id: int) -> Optional[dict]:
    """Get a single pattern with its code chunks."""
    row = conn.execute(
        "SELECT * FROM patterns WHERE id = ?", (pattern_id,)
    ).fetchone()
    if not row:
        return None
    result = dict(row)
    result["tags"] = json.loads(result["tags"])
    chunks = conn.execute(
        "SELECT id, code_text, chunk_type FROM chunks WHERE pattern_id = ?",
        (pattern_id,),
    ).fetchall()
    result["chunks"] = [dict(c) for c in chunks]
    return result


def list_tags(conn: sqlite3.Connection, category: Optional[str] = None) -> list[str]:
    """List all unique tags, optionally filtered by category."""
    if category:
        rows = conn.execute(
            "SELECT tags FROM patterns WHERE category = ?", (category,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT tags FROM patterns").fetchall()
    all_tags = set()
    for row in rows:
        all_tags.update(json.loads(row["tags"]))
    return sorted(all_tags)


def list_categories(conn: sqlite3.Connection) -> list[str]:
    """List all unique categories."""
    rows = conn.execute(
        "SELECT DISTINCT category FROM patterns ORDER BY category"
    ).fetchall()
    return [r["category"] for r in rows]


def search_fts(
    conn: sqlite3.Connection,
    query: str,
    category: Optional[str] = None,
    language: Optional[str] = None,
    limit: int = 10,
) -> list[dict]:
    """Full-text search over patterns using FTS5 with BM25 ranking."""
    # Build the FTS query — wrap terms for safety
    fts_query = " OR ".join(
        f'"{term}"' for term in query.split() if term.strip()
    )
    if not fts_query:
        return []

    sql = """
        SELECT p.*, bm25(patterns_fts) as rank
        FROM patterns_fts fts
        JOIN patterns p ON p.id = fts.rowid
        WHERE patterns_fts MATCH ?
    """
    params: list = [fts_query]

    if category:
        sql += " AND p.category = ?"
        params.append(category)
    if language:
        sql += " AND p.language = ?"
        params.append(language)

    sql += " ORDER BY rank LIMIT ?"
    params.append(limit)

    rows = conn.execute(sql, params).fetchall()
    results = []
    for row in rows:
        r = dict(row)
        r["tags"] = json.loads(r["tags"])
        results.append(r)
    return results


def get_stats(conn: sqlite3.Connection) -> dict:
    """Get database statistics."""
    pattern_count = conn.execute("SELECT COUNT(*) FROM patterns").fetchone()[0]
    chunk_count = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    insight_count = conn.execute("SELECT COUNT(*) FROM repo_insights").fetchone()[0]
    categories = list_categories(conn)
    languages = [
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT language FROM patterns ORDER BY language"
        ).fetchall()
    ]
    return {
        "patterns": pattern_count,
        "chunks": chunk_count,
        "insights": insight_count,
        "categories": categories,
        "languages": languages,
    }
