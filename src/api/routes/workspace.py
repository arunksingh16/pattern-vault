"""Workspace file tree and GitHub clone endpoints for the Explorer panel."""

from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from src.agent.tools import get_workspace_roots, _tool_clone_github_repo
from src.api.deps import DB_PATH
from src.store.db import get_connection, init_db, list_cloned_repos

router = APIRouter(prefix="/workspace", tags=["workspace"])


@router.get("/roots")
def get_roots():
    roots = get_workspace_roots()
    return [{"path": str(r), "name": r.name} for r in roots]


@router.get("/tree")
def get_tree(path: str = Query(...)):
    target = Path(path).expanduser().resolve()
    roots = get_workspace_roots()

    if not any(target == r or r in target.parents or target in r.parents for r in roots):
        raise HTTPException(status_code=403, detail="Path outside workspace roots")

    if not target.is_dir():
        raise HTTPException(status_code=404, detail="Not a directory")

    entries = []
    try:
        for entry in sorted(target.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower())):
            if entry.name.startswith('.'):
                continue
            if entry.name in ('node_modules', '__pycache__', 'venv', '.git', 'dist', 'build'):
                continue
            entries.append({
                "name": entry.name,
                "path": str(entry),
                "is_dir": entry.is_dir(),
                "size": entry.stat().st_size if entry.is_file() else None,
            })
    except PermissionError:
        raise HTTPException(status_code=403, detail="Permission denied")

    return entries


class CloneRequest(BaseModel):
    url: str


@router.post("/clone")
def clone_repo(req: CloneRequest):
    """Clone a public GitHub repo and register it in the DB."""
    import json
    result_str = _tool_clone_github_repo(req.url, DB_PATH)
    result = json.loads(result_str)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.get("/cloned")
def list_cloned():
    """List all previously cloned repos."""
    conn = get_connection(DB_PATH)
    try:
        init_db(conn)
        return list_cloned_repos(conn)
    finally:
        conn.close()
