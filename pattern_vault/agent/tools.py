"""
Pattern Vault — Agent tools.

These are the tools Claude uses in the interactive analysis loop.
Each tool is a simple Python function that the orchestrator can call.
"""

import json
import os
import re
import shutil
import subprocess  # nosec B404
from pathlib import Path
from typing import Optional

from ..indexer.chunker import scan_directory, chunk_file, LANG_MAP
from ..store.db import (
    get_connection,
    init_db,
    insert_pattern,
    insert_insight,
    search_fts,
    get_stats,
    upsert_cloned_repo,
)

WORKSPACE_ROOTS_ENV = "PATTERN_VAULT_WORKSPACE_ROOTS"
MAX_TOOL_FILE_SIZE = 200_000
MAX_TOOL_LINES = 1_000

BLOCKED_PATH_PARTS = {
    ".aws",
    ".azure",
    ".config",
    ".gnupg",
    ".ssh",
    ".git",
}

BLOCKED_FILENAMES = {
    ".env",
    ".env.local",
    ".env.production",
    ".npmrc",
    ".pypirc",
    "credentials",
    "credentials.json",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
    "id_rsa",
    "secrets.json",
}


def _get_conn(db_path: Optional[Path] = None):
    conn = get_connection(db_path)
    init_db(conn)
    return conn


# Strict GitHub URL pattern — only plain repo URLs, no subpaths
_GITHUB_URL_RE = re.compile(
    r'^https://github\.com/([a-zA-Z0-9_.-]+)/([a-zA-Z0-9_.-]+?)(\.git)?/?$'
)

# .temp/ lives next to pattern_vault/ in the project root
_PROJECT_ROOT = Path(__file__).parents[2]
CLONE_BASE_DIR = _PROJECT_ROOT / ".temp"


def get_workspace_roots() -> list[Path]:
    """Return configured roots that agent file tools are allowed to inspect."""
    raw_roots = os.environ.get(WORKSPACE_ROOTS_ENV)
    if raw_roots:
        roots = [
            Path(root).expanduser().resolve()
            for root in raw_roots.split(os.pathsep)
            if root.strip()
        ]
    else:
        roots = [Path.cwd().resolve()]
    return roots


def _is_under_root(path: Path, roots: list[Path]) -> bool:
    return any(path == root or root in path.parents for root in roots)


def _has_blocked_path_part(path: Path) -> bool:
    parts = {part.lower() for part in path.parts}
    return bool(parts & BLOCKED_PATH_PARTS) or path.name.lower() in BLOCKED_FILENAMES


def _json_error(message: str) -> str:
    return json.dumps({"error": message})


def _validate_tool_path(
    path: str,
    expect_file: bool,
    extra_roots: Optional[list[Path]] = None,
) -> tuple[Optional[Path], Optional[str]]:
    p = Path(path).expanduser().resolve()
    roots = get_workspace_roots() + (extra_roots or [])

    if not _is_under_root(p, roots):
        root_list = ", ".join(str(root) for root in roots)
        return None, (
            f"Path is outside allowed workspace roots: {p}. "
            f"Set {WORKSPACE_ROOTS_ENV} to allow additional roots. "
            f"Configured roots: {root_list}"
        )

    if _has_blocked_path_part(p):
        return None, f"Blocked sensitive path: {p}"

    if not p.exists():
        return None, f"Path not found: {path}"

    if expect_file and not p.is_file():
        return None, f"Not a file: {path}"

    if not expect_file and not p.is_dir():
        return None, f"Not a directory: {path}"

    return p, None


def _validate_source_file(
    path: str, extra_roots: Optional[list[Path]] = None
) -> tuple[Optional[Path], Optional[str]]:
    p, error = _validate_tool_path(path, expect_file=True, extra_roots=extra_roots)
    if error or p is None:
        return None, error

    if p.suffix not in LANG_MAP:
        return None, f"Unsupported source file type: {p.suffix or '<none>'}"

    size = p.stat().st_size
    if size > MAX_TOOL_FILE_SIZE:
        return None, f"File is too large for tool access: {size} bytes"

    with p.open("rb") as file:
        sample = file.read(4096)
    if b"\x00" in sample:
        return None, f"Refusing to read binary file: {p}"

    return p, None


# ── Tool definitions (for Claude tool-use API) ─────────────────

TOOL_DEFINITIONS = [
    {
        "name": "scan_directory",
        "description": "Scan a directory to see its structure — lists source files with languages and sizes. Does NOT read file contents.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute path to the directory to scan"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "read_file",
        "description": "Read the full content of a source file. Use after scan_directory to inspect specific files.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute path to the file"},
                "max_lines": {"type": "integer", "description": "Max lines to read (default: 200)", "default": 200},
            },
            "required": ["path"],
        },
    },
    {
        "name": "parse_symbols",
        "description": "Parse a file using tree-sitter AST to extract functions, classes, and methods with their code.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute path to the file"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "save_pattern",
        "description": "Save a code pattern to the vault. Use when you identify a reusable pattern during analysis.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Short descriptive name"},
                "summary": {"type": "string", "description": "What this pattern does and when to use it"},
                "code_text": {"type": "string", "description": "The actual code"},
                "category": {"type": "string", "description": "Category: design_pattern, resilience, api_pattern, data_access, async_pattern, config, testing, utility, security, general"},
                "language": {"type": "string", "description": "Programming language"},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "Tags for searchability"},
                "quality_signal": {"type": "string", "description": "Quality note"},
                "source_repo": {"type": "string", "description": "Source repository"},
                "source_file": {"type": "string", "description": "Source file path"},
            },
            "required": ["name", "summary", "code_text", "category", "language"],
        },
    },
    {
        "name": "save_insight",
        "description": "Save an architectural insight or observation about a repo that isn't tied to specific code.",
        "input_schema": {
            "type": "object",
            "properties": {
                "repo_path": {"type": "string", "description": "Repository path or name"},
                "insight_text": {"type": "string", "description": "The insight or observation"},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "Tags"},
            },
            "required": ["repo_path", "insight_text"],
        },
    },
    {
        "name": "search_patterns",
        "description": "Search the existing pattern vault for patterns matching a query.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "category": {"type": "string", "description": "Optional category filter"},
                "language": {"type": "string", "description": "Optional language filter"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "vault_stats",
        "description": "Get statistics about what's currently in the pattern vault.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "clone_github_repo",
        "description": "Clone a public GitHub repository to the local .temp/ directory for analysis. Only accepts plain https://github.com/<owner>/<repo> URLs. After cloning, use scan_directory on the returned local_path to explore the repo.",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "Public GitHub repo URL, e.g. https://github.com/owner/repo",
                },
            },
            "required": ["url"],
        },
    },
]


# ── Tool implementations ──────────────────────────────────────

def execute_tool(
    tool_name: str,
    tool_input: dict,
    db_path: Optional[Path] = None,
    extra_roots: Optional[list[Path]] = None,
) -> str:
    """Execute an agent tool and return the result as a string."""
    _extra = extra_roots or []
    try:
        if tool_name == "scan_directory":
            return _tool_scan_directory(tool_input["path"], _extra)
        elif tool_name == "read_file":
            return _tool_read_file(tool_input["path"], tool_input.get("max_lines", 200), _extra)
        elif tool_name == "parse_symbols":
            return _tool_parse_symbols(tool_input["path"], _extra)
        elif tool_name == "save_pattern":
            return _tool_save_pattern(tool_input, db_path)
        elif tool_name == "save_insight":
            return _tool_save_insight(tool_input, db_path)
        elif tool_name == "search_patterns":
            return _tool_search_patterns(tool_input, db_path)
        elif tool_name == "vault_stats":
            return _tool_vault_stats(db_path)
        elif tool_name == "clone_github_repo":
            return _tool_clone_github_repo(tool_input["url"], db_path)
        else:
            return json.dumps({"error": f"Unknown tool: {tool_name}"})
    except Exception as e:
        return json.dumps({"error": f"{tool_name} failed: {str(e)}"})


def _tool_scan_directory(path: str, extra_roots: Optional[list[Path]] = None) -> str:
    root, error = _validate_tool_path(path, expect_file=False, extra_roots=extra_roots)
    if error or root is None:
        return _json_error(error or "Invalid directory")

    manifest = scan_directory(root)
    return json.dumps({
        "total_files": manifest.total_files,
        "skipped": manifest.skipped,
        "languages": manifest.languages,
        "files": [
            {"relative": f["relative"], "language": f["language"], "size": f["size"]}
            for f in manifest.files[:50]  # Cap at 50 for context
        ],
        "truncated": manifest.total_files > 50,
    }, indent=2)


def _tool_read_file(path: str, max_lines: int = 200, extra_roots: Optional[list[Path]] = None) -> str:
    p, error = _validate_source_file(path, extra_roots=extra_roots)
    if error or p is None:
        return _json_error(error or "Invalid file")

    try:
        max_lines = max(1, min(int(max_lines), MAX_TOOL_LINES))
        text = p.read_text(errors="replace")
        lines = text.split("\n")
        truncated = len(lines) > max_lines
        if truncated:
            lines = lines[:max_lines]
        return json.dumps({
            "path": str(p),
            "language": LANG_MAP.get(p.suffix, "unknown"),
            "total_lines": len(text.split("\n")),
            "content": "\n".join(lines),
            "truncated": truncated,
        })
    except Exception as e:
        return json.dumps({"error": f"Failed to read {path}: {e}"})


def _tool_parse_symbols(path: str, extra_roots: Optional[list[Path]] = None) -> str:
    p, error = _validate_source_file(path, extra_roots=extra_roots)
    if error or p is None:
        return _json_error(error or "Invalid file")

    lang = LANG_MAP.get(p.suffix, "unknown")
    chunks = chunk_file(p, lang)
    return json.dumps({
        "file": str(p),
        "language": lang,
        "symbols_found": len(chunks),
        "symbols": [
            {
                "name": c.symbol_name,
                "type": c.symbol_type,
                "lines": f"{c.line_start}-{c.line_end}",
                "code": c.code,
            }
            for c in chunks
        ],
    }, indent=2)


def _tool_save_pattern(inp: dict, db_path: Optional[Path] = None) -> str:
    conn = _get_conn(db_path)
    try:
        pid = insert_pattern(
            conn,
            name=inp["name"],
            summary=inp["summary"],
            code_text=inp["code_text"],
            category=inp.get("category", "general"),
            language=inp.get("language", "unknown"),
            tags=inp.get("tags", []),
            quality_signal=inp.get("quality_signal"),
            source_repo=inp.get("source_repo"),
            source_file=inp.get("source_file"),
        )
        return json.dumps({"status": "saved", "pattern_id": pid, "name": inp["name"]})
    finally:
        conn.close()


def _tool_save_insight(inp: dict, db_path: Optional[Path] = None) -> str:
    conn = _get_conn(db_path)
    try:
        iid = insert_insight(conn, inp["repo_path"], inp["insight_text"], inp.get("tags", []))
        return json.dumps({"status": "saved", "insight_id": iid})
    finally:
        conn.close()


def _tool_search_patterns(inp: dict, db_path: Optional[Path] = None) -> str:
    conn = _get_conn(db_path)
    try:
        results = search_fts(conn, inp["query"], category=inp.get("category"), language=inp.get("language"))
        compact = [
            {"id": r["id"], "name": r["name"], "category": r["category"],
             "language": r["language"], "tags": r["tags"], "summary": r["summary"]}
            for r in results
        ]
        return json.dumps({"count": len(compact), "results": compact}, indent=2)
    finally:
        conn.close()


def _tool_vault_stats(db_path: Optional[Path] = None) -> str:
    conn = _get_conn(db_path)
    try:
        return json.dumps(get_stats(conn), indent=2)
    finally:
        conn.close()


def _tool_clone_github_repo(url: str, db_path: Optional[Path] = None) -> str:
    """Clone a public GitHub repo to .temp/<owner>/<repo>/, register in DB."""
    match = _GITHUB_URL_RE.match(url.strip())
    if not match:
        return _json_error(
            "Invalid GitHub URL. Only plain public repo URLs are accepted: "
            "https://github.com/<owner>/<repo>"
        )

    owner, repo = match.group(1), match.group(2)
    dest = CLONE_BASE_DIR / owner / repo

    # Always re-clone: remove existing clone
    if dest.exists():
        shutil.rmtree(dest)

    dest.parent.mkdir(parents=True, exist_ok=True)

    git_bin = shutil.which("git")
    if not git_bin:
        return _json_error("git executable not found on PATH")

    result = subprocess.run(  # nosec B603
        [git_bin, "clone", "--depth=1", url.strip(), str(dest)],
        capture_output=True,
        text=True,
        timeout=120,
    )

    if result.returncode != 0:
        return _json_error(f"git clone failed: {result.stderr.strip()}")

    # Detect default branch
    branch_result = subprocess.run(  # nosec B603
        [git_bin, "-C", str(dest), "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True,
        text=True,
    )
    branch = branch_result.stdout.strip() if branch_result.returncode == 0 else "main"

    source_url_base = f"https://github.com/{owner}/{repo}/blob/{branch}/"

    # Register in DB
    conn = _get_conn(db_path)
    try:
        upsert_cloned_repo(conn, owner, repo, str(dest), source_url_base, branch)
    finally:
        conn.close()

    return json.dumps({
        "status": "cloned",
        "owner": owner,
        "repo": repo,
        "branch": branch,
        "local_path": str(dest),
        "source_url_base": source_url_base,
        "message": f"Cloned to {dest}. Use scan_directory('{dest}') to explore.",
    }, indent=2)
