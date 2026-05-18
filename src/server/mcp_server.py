"""
Pattern Vault — MCP Server.

Exposes the pattern store as MCP tools for Claude Code and claude.ai.
Tools: search_patterns, get_pattern, add_pattern, save_insight,
       list_tags, list_categories, get_stats, reindex.
"""

import json
import sys
from pathlib import Path
from typing import Optional

from mcp.server.fastmcp import FastMCP

# Add project root to path so imports work when run standalone
_project_root = Path(__file__).resolve().parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from src.store.db import (  # noqa: E402
    get_connection,
    init_db,
    insert_pattern,
    insert_insight,
    get_pattern as db_get_pattern,
    search_fts,
    list_tags as db_list_tags,
    list_categories as db_list_categories,
    get_stats as db_get_stats,
    resolve_db_path,
)

# ── Server setup ─────────────────────────────────────────────

DB_PATH = resolve_db_path()

mcp = FastMCP("pattern_vault_mcp")


def _get_conn():
    conn = get_connection(DB_PATH)
    init_db(conn)
    return conn


# ── Tools ────────────────────────────────────────────────────

@mcp.tool(
    name="search_patterns",
    annotations={
        "title": "Search code patterns",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def search_patterns(
    query: str,
    category: Optional[str] = None,
    language: Optional[str] = None,
    limit: int = 10,
) -> str:
    """Search the pattern vault for reusable code patterns.

    Uses full-text search with BM25 ranking over pattern names, summaries, and tags.
    Returns compact results — use get_pattern for full code.

    Args:
        query: Natural language search query (e.g. "retry with backoff", "auth middleware")
        category: Filter by category (resilience, api_pattern, design_pattern, etc.)
        language: Filter by language (python, javascript, typescript, etc.)
        limit: Max results (default 10)

    Returns:
        JSON array of matching patterns with id, name, category, language, tags, summary
    """
    conn = _get_conn()
    try:
        results = search_fts(conn, query, category=category, language=language, limit=limit)
        # Return compact summaries (no full code)
        compact = []
        for r in results:
            compact.append({
                "id": r["id"],
                "name": r["name"],
                "category": r["category"],
                "language": r["language"],
                "tags": r["tags"],
                "summary": r["summary"],
                "source_file": r.get("source_file"),
            })
        if not compact:
            return json.dumps({"message": f"No patterns found matching '{query}'", "results": []})
        return json.dumps({"count": len(compact), "results": compact}, indent=2)
    finally:
        conn.close()


@mcp.tool(
    name="get_pattern",
    annotations={
        "title": "Get full pattern details",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def get_pattern_tool(pattern_id: int) -> str:
    """Get full details of a specific pattern including all code chunks.

    Use search_patterns first to find pattern IDs, then this to get the full code.

    Args:
        pattern_id: The numeric ID of the pattern to retrieve

    Returns:
        Full pattern details including code, metadata, and source info
    """
    conn = _get_conn()
    try:
        pattern = db_get_pattern(conn, pattern_id)
        if not pattern:
            return json.dumps({"error": f"Pattern {pattern_id} not found"})
        return json.dumps(pattern, indent=2, default=str)
    finally:
        conn.close()


@mcp.tool(
    name="add_pattern",
    annotations={
        "title": "Add a code pattern",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def add_pattern(
    name: str,
    summary: str,
    code_text: str,
    category: str = "general",
    language: str = "unknown",
    tags: Optional[str] = None,
    quality_signal: Optional[str] = None,
    source_repo: Optional[str] = None,
    source_file: Optional[str] = None,
) -> str:
    """Manually add a code pattern to the vault.

    Use this when you discover a pattern during conversation or code review
    that should be saved for future reference.

    Args:
        name: Short descriptive name (e.g. "Exponential backoff retry")
        summary: One paragraph explaining what this pattern does and when to use it
        code_text: The actual code implementing the pattern
        category: One of: design_pattern, resilience, api_pattern, data_access, async_pattern, config, testing, utility, security, general
        language: Programming language (python, javascript, typescript, go, rust, etc.)
        tags: Comma-separated tags (e.g. "retry,async,backoff")
        quality_signal: Brief quality note (e.g. "handles edge cases well")
        source_repo: Source repository URL or name
        source_file: Source file path within the repo

    Returns:
        Confirmation with the pattern ID
    """
    conn = _get_conn()
    try:
        tag_list = [t.strip() for t in (tags or "").split(",") if t.strip()]
        pattern_id = insert_pattern(
            conn,
            name=name,
            summary=summary,
            code_text=code_text,
            category=category,
            language=language,
            tags=tag_list,
            quality_signal=quality_signal,
            source_repo=source_repo,
            source_file=source_file,
        )
        return json.dumps({
            "status": "stored",
            "pattern_id": pattern_id,
            "name": name,
            "category": category,
        })
    finally:
        conn.close()


@mcp.tool(
    name="save_insight",
    annotations={
        "title": "Save a repo insight",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
async def save_insight(
    repo_path: str,
    insight_text: str,
    tags: Optional[str] = None,
) -> str:
    """Save an architectural observation or insight about a repository.

    Use this for high-level observations that aren't tied to a single code pattern,
    like "this repo uses excellent error boundaries" or "monorepo with shared types".

    Args:
        repo_path: Repository path or name
        insight_text: The observation or insight to save
        tags: Comma-separated tags (e.g. "architecture,resilience")

    Returns:
        Confirmation with the insight ID
    """
    conn = _get_conn()
    try:
        tag_list = [t.strip() for t in (tags or "").split(",") if t.strip()]
        insight_id = insert_insight(conn, repo_path, insight_text, tag_list)
        return json.dumps({
            "status": "saved",
            "insight_id": insight_id,
            "repo": repo_path,
        })
    finally:
        conn.close()


@mcp.tool(
    name="list_tags",
    annotations={
        "title": "List available tags",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def list_tags_tool(category: Optional[str] = None) -> str:
    """List all tags in the pattern vault, optionally filtered by category.

    Useful for discovery — see what kinds of patterns are indexed.

    Args:
        category: Optional category filter

    Returns:
        Sorted list of tags
    """
    conn = _get_conn()
    try:
        tags = db_list_tags(conn, category)
        return json.dumps({"tags": tags, "count": len(tags)})
    finally:
        conn.close()


@mcp.tool(
    name="list_categories",
    annotations={
        "title": "List pattern categories",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def list_categories_tool() -> str:
    """List all pattern categories in the vault.

    Returns:
        List of categories like design_pattern, resilience, api_pattern, etc.
    """
    conn = _get_conn()
    try:
        cats = db_list_categories(conn)
        return json.dumps({"categories": cats, "count": len(cats)})
    finally:
        conn.close()


@mcp.tool(
    name="vault_stats",
    annotations={
        "title": "Pattern vault statistics",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def vault_stats() -> str:
    """Get statistics about the pattern vault — counts, categories, languages.

    Returns:
        Summary statistics of the pattern vault contents
    """
    conn = _get_conn()
    try:
        stats = db_get_stats(conn)
        return json.dumps(stats, indent=2)
    finally:
        conn.close()


@mcp.tool(
    name="reindex",
    annotations={
        "title": "Index a directory for patterns",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def reindex(
    path: str,
    repo_name: Optional[str] = None,
    dry_run: bool = False,
    profile: str = "curated",
) -> str:
    """Scan a directory, extract code patterns using Claude, and store them.

    This runs the full indexing pipeline: scan → chunk (tree-sitter) → extract (Claude) → store.
    Skips files whose content hasn't changed since last index.

    Args:
        path: Absolute path to the directory to index
        repo_name: Optional name for the source repo (defaults to directory name)
        dry_run: If true, scan and chunk but don't call Claude API or store
        profile: Indexing volume profile: curated, balanced, or comprehensive

    Returns:
        Indexing statistics: files scanned, chunks extracted, patterns found/stored
    """
    from src.indexer.batch import index_directory

    logs = []
    stats = index_directory(
        directory=path,
        db_path=DB_PATH,
        repo_name=repo_name,
        dry_run=dry_run,
        profile=profile,
        on_progress=lambda msg: logs.append(msg),
    )

    return json.dumps({
        "files_scanned": stats.files_scanned,
        "files_skipped": stats.files_skipped,
        "chunks_extracted": stats.chunks_extracted,
        "patterns_found": stats.patterns_found,
        "patterns_stored": stats.patterns_stored,
        "patterns_rejected": stats.patterns_rejected,
        "errors": stats.errors,
        "log": logs,
    }, indent=2)


# ── Entry point ──────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run()
