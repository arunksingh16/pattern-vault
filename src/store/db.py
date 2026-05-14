"""
Pattern Vault — SQLite storage layer.

Schema: patterns, chunks, repo_insights tables + FTS5 virtual table.
Uses sqlite-vec for vector search when available, falls back to FTS-only.
"""

import sqlite3
import json
import hashlib
import os
import time
from pathlib import Path
from typing import Optional

DB_VERSION = 5
DEFAULT_DB_PATH = Path.home() / ".pattern-vault" / "patterns.db"
DB_PATH_ENV = "PATTERN_VAULT_DB"


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def resolve_db_path(db_path: Optional[str | Path] = None) -> Path:
    """Resolve the active vault database path.

    Explicit arguments win, then PATTERN_VAULT_DB, then the default local vault.
    """
    raw_path = db_path or os.environ.get(DB_PATH_ENV) or DEFAULT_DB_PATH
    return Path(raw_path).expanduser()


def get_connection(db_path: Optional[Path] = None) -> sqlite3.Connection:
    """Get a connection to the pattern vault database."""
    path = resolve_db_path(db_path)
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
            user_notes TEXT DEFAULT NULL,
            source_url TEXT DEFAULT NULL,
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

        CREATE TABLE IF NOT EXISTS chat_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS chat_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            tool_calls TEXT NOT NULL DEFAULT '[]',
            created_at REAL NOT NULL,
            FOREIGN KEY (session_id) REFERENCES chat_sessions(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_chat_messages_session ON chat_messages(session_id);

        CREATE TABLE IF NOT EXISTS cloned_repos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner TEXT NOT NULL,
            repo TEXT NOT NULL,
            local_path TEXT NOT NULL,
            source_url_base TEXT NOT NULL,
            branch TEXT NOT NULL DEFAULT 'main',
            cloned_at REAL NOT NULL,
            UNIQUE(owner, repo)
        );
    """)

    # FTS5 virtual table for full-text search
    # Check if it exists first (can't use IF NOT EXISTS with virtual tables in all versions)
    fts_cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='patterns_fts'"
    )
    if fts_cursor.fetchone() is None:
        _create_fts_and_triggers(conn)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS db_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)

    # Run incremental migrations based on stored version
    stored = conn.execute(
        "SELECT value FROM db_meta WHERE key = 'version'"
    ).fetchone()
    stored_version = int(stored["value"]) if stored else 1

    if stored_version < 3:
        _migrate_to_v3(conn)

    if stored_version < 4:
        _migrate_to_v4(conn)

    if stored_version < 5:
        _migrate_to_v5(conn)

    conn.execute(
        "INSERT OR REPLACE INTO db_meta (key, value) VALUES ('version', ?)",
        (str(DB_VERSION),),
    )
    conn.commit()


def _create_fts_and_triggers(conn: sqlite3.Connection) -> None:
    """Create the FTS5 virtual table and its sync triggers (includes user_notes)."""
    conn.execute("""
        CREATE VIRTUAL TABLE patterns_fts USING fts5(
            name, summary, tags, category, language, user_notes,
            content=patterns,
            content_rowid=id,
            tokenize='porter unicode61'
        )
    """)
    conn.executescript("""
        CREATE TRIGGER IF NOT EXISTS patterns_ai AFTER INSERT ON patterns BEGIN
            INSERT INTO patterns_fts(rowid, name, summary, tags, category, language, user_notes)
            VALUES (new.id, new.name, new.summary, new.tags, new.category, new.language, new.user_notes);
        END;

        CREATE TRIGGER IF NOT EXISTS patterns_ad AFTER DELETE ON patterns BEGIN
            INSERT INTO patterns_fts(patterns_fts, rowid, name, summary, tags, category, language, user_notes)
            VALUES ('delete', old.id, old.name, old.summary, old.tags, old.category, old.language, old.user_notes);
        END;

        CREATE TRIGGER IF NOT EXISTS patterns_au AFTER UPDATE ON patterns BEGIN
            INSERT INTO patterns_fts(patterns_fts, rowid, name, summary, tags, category, language, user_notes)
            VALUES ('delete', old.id, old.name, old.summary, old.tags, old.category, old.language, old.user_notes);
            INSERT INTO patterns_fts(rowid, name, summary, tags, category, language, user_notes)
            VALUES (new.id, new.name, new.summary, new.tags, new.category, new.language, new.user_notes);
        END;
    """)


def _migrate_to_v5(conn: sqlite3.Connection) -> None:
    """Migrate DB from v4 → v5: add source_repo to chat_sessions."""
    cols = [row[1] for row in conn.execute("PRAGMA table_info(chat_sessions)").fetchall()]
    if "source_repo" not in cols:
        conn.execute("ALTER TABLE chat_sessions ADD COLUMN source_repo TEXT DEFAULT NULL")
    conn.commit()


def _migrate_to_v4(conn: sqlite3.Connection) -> None:
    """Migrate DB from v3 → v4: add source_url to patterns + cloned_repos table."""
    cols = [row[1] for row in conn.execute("PRAGMA table_info(patterns)").fetchall()]
    if "source_url" not in cols:
        conn.execute("ALTER TABLE patterns ADD COLUMN source_url TEXT DEFAULT NULL")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS cloned_repos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner TEXT NOT NULL,
            repo TEXT NOT NULL,
            local_path TEXT NOT NULL,
            source_url_base TEXT NOT NULL,
            branch TEXT NOT NULL DEFAULT 'main',
            cloned_at REAL NOT NULL,
            UNIQUE(owner, repo)
        );
    """)
    conn.commit()


def _migrate_to_v3(conn: sqlite3.Connection) -> None:
    """Migrate DB from v2 → v3: add user_notes column + rebuild FTS to include it."""
    # Add column if it doesn't exist yet
    cols = [row[1] for row in conn.execute("PRAGMA table_info(patterns)").fetchall()]
    if "user_notes" not in cols:
        conn.execute("ALTER TABLE patterns ADD COLUMN user_notes TEXT DEFAULT NULL")

    # Rebuild FTS: drop triggers, drop table, recreate with user_notes, repopulate
    conn.executescript("""
        DROP TRIGGER IF EXISTS patterns_ai;
        DROP TRIGGER IF EXISTS patterns_ad;
        DROP TRIGGER IF EXISTS patterns_au;
        DROP TABLE IF EXISTS patterns_fts;
    """)
    _create_fts_and_triggers(conn)

    # Repopulate FTS from existing patterns
    conn.execute("""
        INSERT INTO patterns_fts(rowid, name, summary, tags, category, language, user_notes)
        SELECT id, name, summary, tags, category, language, user_notes FROM patterns
    """)
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
    source_url: Optional[str] = None,
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
            content_hash, source_url, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            name, category, language, tags_json, summary, quality_signal,
            source_repo, source_file, line_start, line_end,
            chash, source_url, now, now,
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


def list_insights(
    conn: sqlite3.Connection, limit: int = 50, offset: int = 0
) -> list[dict]:
    rows = conn.execute(
        "SELECT id, repo_path, insight_text, tags, created_at FROM repo_insights ORDER BY created_at DESC LIMIT ? OFFSET ?",
        (limit, offset),
    ).fetchall()
    results = []
    for row in rows:
        r = dict(row)
        r["tags"] = json.loads(r["tags"])
        results.append(r)
    return results


def get_insight(conn: sqlite3.Connection, insight_id: int) -> Optional[dict]:
    row = conn.execute(
        "SELECT id, repo_path, insight_text, tags, created_at FROM repo_insights WHERE id = ?",
        (insight_id,),
    ).fetchone()
    if not row:
        return None
    r = dict(row)
    r["tags"] = json.loads(r["tags"])
    return r


def delete_insight(conn: sqlite3.Connection, insight_id: int) -> bool:
    cursor = conn.execute("DELETE FROM repo_insights WHERE id = ?", (insight_id,))
    conn.commit()
    return cursor.rowcount > 0


# ── Cloned repos registry ─────────────────────────────────────

def upsert_cloned_repo(
    conn: sqlite3.Connection,
    owner: str,
    repo: str,
    local_path: str,
    source_url_base: str,
    branch: str = "main",
) -> None:
    """Insert or replace a cloned repo entry."""
    conn.execute(
        """INSERT INTO cloned_repos (owner, repo, local_path, source_url_base, branch, cloned_at)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(owner, repo) DO UPDATE SET
               local_path=excluded.local_path,
               source_url_base=excluded.source_url_base,
               branch=excluded.branch,
               cloned_at=excluded.cloned_at""",
        (owner, repo, local_path, source_url_base, branch, time.time()),
    )
    conn.commit()


def list_cloned_repos(conn: sqlite3.Connection) -> list[dict]:
    """Return all cloned repos ordered by most recently cloned."""
    rows = conn.execute(
        "SELECT id, owner, repo, local_path, source_url_base, branch, cloned_at FROM cloned_repos ORDER BY cloned_at DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def get_cloned_repo(conn: sqlite3.Connection, owner: str, repo: str) -> Optional[dict]:
    """Look up a specific cloned repo by owner/repo."""
    row = conn.execute(
        "SELECT id, owner, repo, local_path, source_url_base, branch, cloned_at FROM cloned_repos WHERE owner=? AND repo=?",
        (owner, repo),
    ).fetchone()
    return dict(row) if row else None


def get_pattern(conn: sqlite3.Connection, pattern_id: int) -> Optional[dict]:
    """Get a single pattern with its code chunks."""
    row = conn.execute(
        "SELECT * FROM patterns WHERE id = ?", (pattern_id,)
    ).fetchone()
    if not row:
        return None
    result = dict(row)
    result["tags"] = json.loads(result["tags"])
    result.setdefault("user_notes", None)
    result.setdefault("source_url", None)
    chunks = conn.execute(
        "SELECT id, code_text, chunk_type FROM chunks WHERE pattern_id = ?",
        (pattern_id,),
    ).fetchall()
    result["chunks"] = [dict(c) for c in chunks]
    return result


def update_pattern(
    conn: sqlite3.Connection,
    pattern_id: int,
    *,
    name: Optional[str] = None,
    summary: Optional[str] = None,
    category: Optional[str] = None,
    language: Optional[str] = None,
    tags: Optional[list[str]] = None,
    quality_signal: Optional[str] = None,
    source_repo: Optional[str] = None,
    source_file: Optional[str] = None,
    line_start: Optional[int] = None,
    line_end: Optional[int] = None,
    code_text: Optional[str] = None,
    user_notes: Optional[str] = None,
) -> bool:
    """Update pattern metadata and optionally replace its primary code chunk."""
    existing = conn.execute(
        "SELECT id FROM patterns WHERE id = ?", (pattern_id,)
    ).fetchone()
    if not existing:
        return False

    fields = {
        "name": name,
        "summary": summary,
        "category": category,
        "language": language,
        "tags": json.dumps(tags) if tags is not None else None,
        "quality_signal": quality_signal,
        "source_repo": source_repo,
        "source_file": source_file,
        "line_start": line_start,
        "line_end": line_end,
        "user_notes": user_notes,
    }
    updates = [(key, value) for key, value in fields.items() if value is not None]

    if code_text is not None:
        content_hash = _content_hash(code_text)
        duplicate = conn.execute(
            "SELECT id FROM patterns WHERE content_hash = ? AND id != ?",
            (content_hash, pattern_id),
        ).fetchone()
        if duplicate:
            raise ValueError(f"Code text duplicates existing pattern {duplicate['id']}")
        fields["content_hash"] = content_hash
        updates.append(("content_hash", content_hash))

    if updates:
        conn.execute(
            """
            UPDATE patterns
            SET name = COALESCE(?, name),
                summary = COALESCE(?, summary),
                category = COALESCE(?, category),
                language = COALESCE(?, language),
                tags = COALESCE(?, tags),
                quality_signal = COALESCE(?, quality_signal),
                source_repo = COALESCE(?, source_repo),
                source_file = COALESCE(?, source_file),
                line_start = COALESCE(?, line_start),
                line_end = COALESCE(?, line_end),
                content_hash = COALESCE(?, content_hash),
                user_notes = COALESCE(?, user_notes),
                updated_at = ?
            WHERE id = ?
            """,
            (
                fields["name"],
                fields["summary"],
                fields["category"],
                fields["language"],
                fields["tags"],
                fields["quality_signal"],
                fields["source_repo"],
                fields["source_file"],
                fields["line_start"],
                fields["line_end"],
                fields.get("content_hash"),
                fields["user_notes"],
                time.time(),
                pattern_id,
            ),
        )

    if code_text is not None:
        primary_chunk = conn.execute(
            "SELECT id FROM chunks WHERE pattern_id = ? ORDER BY id LIMIT 1",
            (pattern_id,),
        ).fetchone()
        if primary_chunk:
            conn.execute(
                "UPDATE chunks SET code_text = ? WHERE id = ?",
                (code_text, primary_chunk["id"]),
            )
        else:
            conn.execute(
                """INSERT INTO chunks (pattern_id, code_text, chunk_type)
                   VALUES (?, ?, 'implementation')""",
                (pattern_id, code_text),
            )

    conn.commit()
    return True


def delete_pattern(conn: sqlite3.Connection, pattern_id: int) -> bool:
    """Delete a pattern and its chunks. Returns True when a row was removed."""
    cursor = conn.execute("DELETE FROM patterns WHERE id = ?", (pattern_id,))
    conn.commit()
    return cursor.rowcount > 0


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


# ── Chat history ─────────────────────────────────────────────────

def create_session(
    conn: sqlite3.Connection,
    title: Optional[str] = None,
    source_repo: Optional[str] = None,
) -> int:
    now = time.time()
    cursor = conn.execute(
        "INSERT INTO chat_sessions (title, source_repo, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (title, source_repo, now, now),
    )
    conn.commit()
    return cursor.lastrowid


def append_message(
    conn: sqlite3.Connection,
    session_id: int,
    role: str,
    content: str,
    tool_calls: Optional[list] = None,
) -> int:
    now = time.time()
    cursor = conn.execute(
        "INSERT INTO chat_messages (session_id, role, content, tool_calls, created_at) VALUES (?, ?, ?, ?, ?)",
        (session_id, role, content, json.dumps(tool_calls or []), now),
    )
    conn.execute(
        "UPDATE chat_sessions SET updated_at = ? WHERE id = ?",
        (now, session_id),
    )
    conn.commit()
    return cursor.lastrowid


def list_sessions(conn: sqlite3.Connection, limit: int = 50) -> list[dict]:
    rows = conn.execute(
        "SELECT id, title, source_repo, created_at, updated_at FROM chat_sessions ORDER BY updated_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_latest_session_for_repo(conn: sqlite3.Connection, source_repo: str) -> Optional[dict]:
    row = conn.execute(
        "SELECT id, title, source_repo, created_at, updated_at FROM chat_sessions WHERE source_repo = ? ORDER BY updated_at DESC LIMIT 1",
        (source_repo,),
    ).fetchone()
    return dict(row) if row else None


def get_session_messages(conn: sqlite3.Connection, session_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT id, role, content, tool_calls, created_at FROM chat_messages WHERE session_id = ? ORDER BY created_at",
        (session_id,),
    ).fetchall()
    results = []
    for row in rows:
        r = dict(row)
        r["tool_calls"] = json.loads(r["tool_calls"])
        results.append(r)
    return results


def delete_session(conn: sqlite3.Connection, session_id: int) -> bool:
    cursor = conn.execute("DELETE FROM chat_sessions WHERE id = ?", (session_id,))
    conn.commit()
    return cursor.rowcount > 0
