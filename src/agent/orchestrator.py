"""
Pattern Vault — Agent orchestrator.

Runs a Claude tool-use loop for interactive repo analysis.
Claude decides which tools to call based on the conversation.
"""

from pathlib import Path
from typing import Optional, Generator

from ..client import extract_usage_snapshot, get_model, get_provider_name, make_async_client, make_client
from ..store.db import get_connection, init_db, record_token_usage
from .tools import TOOL_DEFINITIONS, execute_tool

SYSTEM_PROMPT = """\
You are Pattern Vault — an expert code analyst that helps discover, classify, and index reusable code patterns from repositories.

You have access to tools for scanning directories, reading files, parsing ASTs, and saving patterns/insights to a searchable database. Use them proactively.

When analysing code:
1. Start by scanning the directory structure to understand the project layout
2. Read key files (README, main entry points, config) to understand purpose and architecture
3. Use parse_symbols for deeper AST-level analysis when needed
4. Identify reusable patterns — look for: retry logic, middleware, auth patterns, error handling, caching, design patterns, API patterns, config management, DI, etc.
5. Save valuable patterns with clear names, summaries, and tags
6. Save high-level architectural insights about the repo

Be opinionated about quality. Not every function is a pattern. Save only genuinely reusable, well-implemented code.

When the user asks questions about the code, answer conversationally while using tools to ground your answers in actual code.

Always explain what you're finding and ask the user if they want specific patterns saved.
"""

MAX_TOOL_ROUNDS = 15  # safety limit on tool-use loops


def _record_usage(
    *,
    db_path: Optional[Path],
    model: str,
    response,
    messages: list[dict],
    system: str,
    session_id: Optional[int] = None,
) -> None:
    usage = extract_usage_snapshot(response, system=system, messages=messages)
    conn = get_connection(db_path)
    try:
        init_db(conn)
        record_token_usage(
            conn,
            provider=get_provider_name(),
            model=model,
            flow="chat",
            operation="agent_turn",
            input_tokens=usage["input_tokens"],
            output_tokens=usage["output_tokens"],
            total_tokens=usage["total_tokens"],
            estimated=usage["estimated"],
            usage=usage["usage"],
            session_id=session_id,
        )
    finally:
        conn.close()


def run_agent_turn(
    messages: list[dict],
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    db_path: Optional[Path] = None,
    session_id: Optional[int] = None,
) -> Generator[dict, None, None]:
    """
    Run one agent turn: send messages to Claude, handle tool calls in a loop.

    Yields events:
        {"type": "text", "content": "..."} — text from Claude
        {"type": "tool_call", "name": "...", "input": {...}} — tool being called
        {"type": "tool_result", "name": "...", "result": "..."} — tool result
        {"type": "done"} — turn complete
        {"type": "error", "message": "..."} — error
    """
    try:
        client = make_client()
    except RuntimeError as e:
        yield {"type": "error", "message": str(e)}
        return

    model = model or get_model()

    # Build tool definitions for the API
    tools = [
        {"name": t["name"], "description": t["description"], "input_schema": t["input_schema"]}
        for t in TOOL_DEFINITIONS
    ]

    current_messages = list(messages)
    rounds = 0

    while rounds < MAX_TOOL_ROUNDS:
        rounds += 1

        try:
            response = client.messages.create(
                model=model,
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                tools=tools,
                messages=current_messages,
            )
        except Exception as e:
            yield {"type": "error", "message": f"API error: {e}"}
            return

        _record_usage(
            db_path=db_path,
            model=model,
            response=response,
            messages=current_messages,
            system=SYSTEM_PROMPT,
            session_id=session_id,
        )

        # Process response content blocks
        assistant_content = response.content
        tool_use_blocks = []

        for block in assistant_content:
            if block.type == "text" and block.text.strip():
                yield {"type": "text", "content": block.text}
            elif block.type == "tool_use":
                tool_use_blocks.append(block)
                yield {"type": "tool_call", "name": block.name, "input": block.input}

        # If no tool calls, we're done
        if response.stop_reason == "end_turn" or not tool_use_blocks:
            yield {"type": "done"}
            return

        # Execute tools and build tool results
        current_messages.append({"role": "assistant", "content": assistant_content})

        tool_results = []
        for block in tool_use_blocks:
            result = execute_tool(block.name, block.input, db_path=db_path)
            yield {"type": "tool_result", "name": block.name, "result": result[:500] + "..." if len(result) > 500 else result}
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": result,
            })

        current_messages.append({"role": "user", "content": tool_results})

    yield {"type": "error", "message": "Max tool rounds exceeded"}


async def run_agent_turn_async(
    messages: list[dict],
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    db_path: Optional[Path] = None,
    extra_roots: Optional[list[Path]] = None,
    session_id: Optional[int] = None,
    repo_hint: Optional[str] = None,
):
    """
    Async version of run_agent_turn.

    Yields the same event types as the sync version.
    """
    try:
        client = make_async_client()
    except RuntimeError as e:
        yield {"type": "error", "message": str(e)}
        return

    model = model or get_model()

    tools = [
        {"name": t["name"], "description": t["description"], "input_schema": t["input_schema"]}
        for t in TOOL_DEFINITIONS
    ]

    effective_system = SYSTEM_PROMPT
    if repo_hint:
        effective_system = SYSTEM_PROMPT + f"\n\nREPO CONTEXT: The user is currently working with {repo_hint}. Treat it as the primary repository for all questions unless the user specifies otherwise. Use your tools to explore it proactively."

    current_messages = list(messages)
    rounds = 0

    while rounds < MAX_TOOL_ROUNDS:
        rounds += 1

        try:
            response = await client.messages.create(
                model=model,
                max_tokens=4096,
                system=effective_system,
                tools=tools,
                messages=current_messages,
            )
        except Exception as e:
            yield {"type": "error", "message": f"API error: {e}"}
            return

        _record_usage(
            db_path=db_path,
            model=model,
            response=response,
            messages=current_messages,
            system=effective_system,
            session_id=session_id,
        )

        assistant_content = response.content
        tool_use_blocks = []

        for block in assistant_content:
            if block.type == "text" and block.text.strip():
                yield {"type": "text", "content": block.text}
            elif block.type == "tool_use":
                tool_use_blocks.append(block)
                yield {"type": "tool_call", "name": block.name, "input": block.input}

        if response.stop_reason == "end_turn" or not tool_use_blocks:
            yield {"type": "done"}
            return

        current_messages.append({"role": "assistant", "content": assistant_content})

        tool_results = []
        for block in tool_use_blocks:
            result = execute_tool(block.name, block.input, db_path=db_path, extra_roots=extra_roots)
            yield {"type": "tool_result", "name": block.name, "result": result[:500] + "..." if len(result) > 500 else result}
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": result,
            })

        current_messages.append({"role": "user", "content": tool_results})

    yield {"type": "error", "message": "Max tool rounds exceeded"}
