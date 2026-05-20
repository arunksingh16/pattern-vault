"""SSE streaming chat endpoint wrapping the agent orchestrator."""

import json
from pathlib import Path
from typing import AsyncGenerator, Optional

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from src.agent.orchestrator import run_agent_turn_async
from src.api.deps import DB_PATH
from src.store.db import get_connection, init_db, create_session, append_message, get_cloned_repo

router = APIRouter()


class RepoContext(BaseModel):
    owner: str
    repo: str


class ChatRequest(BaseModel):
    messages: list[dict]
    session_id: Optional[int] = None
    repo_context: Optional[RepoContext] = None


async def _event_stream(
    messages: list[dict],
    session_id: int,
    extra_roots: Optional[list[Path]] = None,
    repo_hint: Optional[str] = None,
) -> AsyncGenerator[str, None]:
    assistant_text = ""
    tool_calls: list[dict] = []

    async for event in run_agent_turn_async(
        messages,
        db_path=DB_PATH,
        extra_roots=extra_roots,
        session_id=session_id,
        repo_hint=repo_hint,
    ):
        if event.get("type") == "text":
            assistant_text += event.get("content", "")
        elif event.get("type") == "tool_call":
            tool_calls.append({"name": event["name"], "input": event.get("input", {})})
        elif event.get("type") == "tool_result":
            for tc in reversed(tool_calls):
                if tc["name"] == event["name"] and "result" not in tc:
                    tc["result"] = event.get("result", "")
                    break
        elif event.get("type") == "done":
            conn = get_connection(DB_PATH)
            try:
                append_message(conn, session_id, "assistant", assistant_text, tool_calls)
            finally:
                conn.close()

        yield f"data: {json.dumps(event)}\n\n"


@router.post("/chat")
async def chat(request: ChatRequest):
    conn = get_connection(DB_PATH)
    try:
        init_db(conn)

        if request.session_id:
            session_id = request.session_id
        else:
            first_user_msg = next(
                (m["content"] for m in request.messages if m.get("role") == "user"),
                "New conversation",
            )
            title = first_user_msg[:80]
            source_repo = (
                f"{request.repo_context.owner}/{request.repo_context.repo}"
                if request.repo_context
                else None
            )
            session_id = create_session(conn, title, source_repo=source_repo)

        last_user = next(
            (m for m in reversed(request.messages) if m.get("role") == "user"), None
        )
        if last_user:
            append_message(conn, session_id, "user", last_user["content"])
    finally:
        conn.close()

    extra_roots: list[Path] = []
    repo_hint: Optional[str] = None
    if request.repo_context:
        conn2 = get_connection(DB_PATH)
        try:
            rec = get_cloned_repo(conn2, request.repo_context.owner, request.repo_context.repo)
            if rec and rec.get("local_path"):
                extra_roots = [Path(rec["local_path"])]
                repo_hint = (
                    f"{request.repo_context.owner}/{request.repo_context.repo} "
                    f"(local path: {rec['local_path']})"
                )
        finally:
            conn2.close()

    response = StreamingResponse(
        _event_stream(request.messages, session_id, extra_roots=extra_roots or None, repo_hint=repo_hint),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
    response.headers["X-Session-Id"] = str(session_id)
    return response
