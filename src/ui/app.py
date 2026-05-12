"""
Pattern Vault — Chainlit Chat UI.

Run with: chainlit run src/ui/app.py

Provides:
- Interactive repo analysis via Claude tool-use loop
- Step-by-step visualization of tool calls
- Pattern search and browsing
- Manual pattern saving

Requires: ANTHROPIC_API_KEY environment variable.
"""

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import chainlit as cl

# Ensure project root is importable
_project_root = Path(__file__).resolve().parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from src.client import make_async_client, get_model, describe_backend  # noqa: E402
from src.agent.tools import TOOL_DEFINITIONS, execute_tool  # noqa: E402
from src.agent.orchestrator import SYSTEM_PROMPT  # noqa: E402
from src.server.mcp_server import mcp as pattern_vault_mcp  # noqa: E402
from src.store.db import get_connection, init_db, get_stats, get_pattern, resolve_db_path  # noqa: E402

DB_PATH = resolve_db_path()
HISTORY_DIR = Path(os.environ.get(
    "PATTERN_VAULT_HISTORY_DIR",
    str(DB_PATH.parent / "chat-history"),
))
MCP_TRANSPORT = os.environ.get("PATTERN_VAULT_MCP_TRANSPORT", "stdio")
MCP_HTTP_URL = os.environ.get("PATTERN_VAULT_MCP_URL")

MAX_TOOL_ROUNDS = 15
PATTERN_LIST_LIMIT = 25
PATTERN_ACTION_LIMIT = 10


def _history_path() -> Path:
    """Return the JSONL transcript path for this Chainlit session."""
    session_id = str(cl.user_session.get("id", "unknown"))
    safe_session_id = "".join(
        char if char.isalnum() or char in ("-", "_") else "_"
        for char in session_id
    )
    return HISTORY_DIR / f"{safe_session_id}.jsonl"


def _save_history_event(role: str, content, **metadata) -> None:
    """Persist a chat event as JSONL without blocking the chat flow on failures."""
    try:
        HISTORY_DIR.mkdir(parents=True, exist_ok=True)
        payload = {
            "timestamp": time.time(),
            "session_id": cl.user_session.get("id"),
            "role": role,
            "content": content,
            **metadata,
        }
        with _history_path().open("a", encoding="utf-8") as file:
            file.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception as exc:  # noqa: BLE001
        # History logging is best-effort; never let it crash the UI
        import logging
        logging.getLogger(__name__).warning("Failed to write chat history: %s", exc)


def _load_patterns(limit: int = PATTERN_LIST_LIMIT) -> list[dict]:
    """Load recently updated saved patterns for UI browsing."""
    conn = get_connection(DB_PATH)
    init_db(conn)
    rows = conn.execute(
        """SELECT id, name, category, language, tags, summary, source_repo,
                  source_file, line_start, line_end, updated_at
           FROM patterns
           ORDER BY updated_at DESC, id DESC
           LIMIT ?""",
        (limit,),
    ).fetchall()
    conn.close()

    patterns = []
    for row in rows:
        pattern = dict(row)
        pattern["tags"] = json.loads(pattern["tags"])
        patterns.append(pattern)
    return patterns


def _format_pattern_list(patterns: list[dict]) -> str:
    if not patterns:
        return (
            "**Saved Patterns**\n\n"
            "No patterns are saved yet. Ask me to scan a repo or save a pattern."
        )

    lines = [
        f"**Saved Patterns** — showing latest {len(patterns)}",
        "",
        "| ID | Name | Category | Language | Source |",
        "|---:|------|----------|----------|--------|",
    ]
    for pattern in patterns:
        source = pattern.get("source_file") or pattern.get("source_repo") or "-"
        tags = ", ".join(pattern["tags"][:4])
        name = pattern["name"]
        if tags:
            name = f"{name}<br><sub>{tags}</sub>"
        lines.append(
            f"| {pattern['id']} | {name} | {pattern['category']} | "
            f"{pattern['language']} | {source} |"
        )
    lines.extend([
        "",
        "Use the buttons below to open a recent pattern, or ask me for a specific ID.",
    ])
    return "\n".join(lines)


def _format_pattern_detail(pattern: dict) -> str:
    tags = ", ".join(pattern["tags"]) or "-"
    source = pattern.get("source_file") or pattern.get("source_repo") or "-"
    location = source
    if pattern.get("line_start") and pattern.get("line_end"):
        location = f"{source}:{pattern['line_start']}-{pattern['line_end']}"

    chunks = pattern.get("chunks", [])
    code_blocks = []
    for chunk in chunks:
        language = pattern.get("language") or ""
        code_blocks.append(f"```{language}\n{chunk['code_text']}\n```")

    return "\n".join([
        f"**Pattern #{pattern['id']}: {pattern['name']}**",
        "",
        f"Category: `{pattern['category']}`",
        f"Language: `{pattern['language']}`",
        f"Tags: {tags}",
        f"Source: `{location}`",
        "",
        pattern["summary"],
        "",
        pattern.get("quality_signal") or "",
        "",
        "\n".join(code_blocks) if code_blocks else "_No code chunk stored._",
    ]).strip()


async def _send_pattern_list() -> None:
    patterns = _load_patterns()
    actions = [
        cl.Action(
            name="refresh_patterns",
            label="Refresh",
            icon="refresh-cw",
            payload={},
        )
    ]
    for pattern in patterns[:PATTERN_ACTION_LIMIT]:
        actions.append(
            cl.Action(
                name="open_pattern",
                label=f"Open #{pattern['id']}",
                icon="book-open",
                payload={"pattern_id": pattern["id"]},
            )
        )
    await cl.Message(content=_format_pattern_list(patterns), actions=actions).send()


def _mcp_http_status() -> tuple[str, str]:
    """Best-effort status for an optional HTTP MCP endpoint."""
    if not MCP_HTTP_URL:
        return "not configured", "Set `PATTERN_VAULT_MCP_URL` to check an HTTP MCP server."

    try:
        request = urllib.request.Request(MCP_HTTP_URL, method="GET")
        with urllib.request.urlopen(request, timeout=1.5) as response:  # nosec B310 – health-check to user-configured internal MCP server only
            return "reachable", f"HTTP {response.status} from `{MCP_HTTP_URL}`"
    except urllib.error.HTTPError as exc:
        return "reachable", f"HTTP {exc.code} from `{MCP_HTTP_URL}`"
    except Exception as exc:
        return "not reachable", f"`{MCP_HTTP_URL}` did not respond: {exc}"


def _mcp_tool_rows() -> list[dict]:
    """Return metadata for tools registered on the local FastMCP instance."""
    tools = []
    for tool in pattern_vault_mcp._tool_manager._tools.values():
        annotations = tool.annotations
        parameters = tool.parameters or {}
        required = set(parameters.get("required", []))
        properties = parameters.get("properties", {})
        args = []
        for name, schema in properties.items():
            marker = "*" if name in required else ""
            default = schema.get("default")
            if default is not None:
                args.append(f"{name}={default!r}")
            else:
                args.append(f"{name}{marker}")

        tools.append({
            "name": tool.name,
            "title": annotations.title if annotations else tool.title,
            "read_only": bool(getattr(annotations, "readOnlyHint", False)),
            "idempotent": bool(getattr(annotations, "idempotentHint", False)),
            "args": ", ".join(args) or "-",
            "description": (tool.description or "").strip().splitlines()[0],
        })
    return tools


def _format_mcp_status() -> str:
    tool_rows = _mcp_tool_rows()
    http_status, http_detail = _mcp_http_status()

    conn = get_connection(DB_PATH)
    try:
        init_db(conn)
        stats = get_stats(conn)
        db_status = "ready"
    except Exception as exc:
        stats = {"patterns": "?", "insights": "?", "categories": [], "languages": []}
        db_status = f"error: {exc}"
    finally:
        conn.close()

    command = "python src/server/mcp_server.py"
    http_command = "python -m src.cli serve --transport http --port 8000"

    lines = [
        "**MCP Server**",
        "",
        "Local registration: `ready`",
        f"Configured transport: `{MCP_TRANSPORT}`",
        f"HTTP endpoint: `{http_status}`",
        f"HTTP detail: {http_detail}",
        f"Database: `{db_status}` (`{DB_PATH}`)",
        f"Vault contents: **{stats['patterns']}** patterns, **{stats['insights']}** insights",
        "",
        "**Run Commands**",
        "",
        f"- Stdio: `{command}`",
        f"- HTTP: `{http_command}`",
        "",
        "**Exposed Tools**",
        "",
        "| Tool | Purpose | Args | Read-only | Idempotent |",
        "|------|---------|------|-----------|------------|",
    ]
    for tool in tool_rows:
        lines.append(
            f"| `{tool['name']}` | {tool['title'] or tool['description']} | "
            f"`{tool['args']}` | {tool['read_only']} | {tool['idempotent']} |"
        )
    lines.extend([
        "",
        "`*` marks required arguments. The Chainlit app is not the MCP server process; "
        "this panel shows local registration and optional HTTP reachability.",
    ])
    return "\n".join(lines)


async def _send_mcp_status() -> None:
    await cl.Message(
        content=_format_mcp_status(),
        actions=[
            cl.Action(
                name="refresh_mcp_status",
                label="Refresh MCP status",
                icon="refresh-cw",
                payload={},
            )
        ],
    ).send()


# ── Lifecycle ────────────────────────────────────────────

@cl.on_chat_start
async def on_chat_start():
    """Initialize session state and show welcome message."""
    cl.user_session.set("messages", [])
    cl.user_session.set("history_path", str(_history_path()))
    _save_history_event("system", "chat_started", history_path=str(_history_path()))

    # Show vault stats and active backend
    conn = get_connection(DB_PATH)
    init_db(conn)
    stats = get_stats(conn)
    conn.close()

    try:
        backend_desc = describe_backend()
        backend_line = f"Backend: **{backend_desc}**"
    except Exception:
        backend_line = "Backend: not configured (set env vars)"

    welcome = (
        "**Pattern Vault** — your code pattern knowledge base.\n\n"
        f"Currently indexed: **{stats['patterns']}** patterns, "
        f"**{stats['insights']}** insights across "
        f"**{', '.join(stats['languages']) or 'no languages yet'}**.\n\n"
        f"{backend_line}\n\n"
        "I can:\n"
        "- Analyse a repo — point me at a folder path\n"
        "- Search patterns — ask me for retry logic, auth middleware, etc.\n"
        "- Save patterns you find during our conversation\n\n"
        f"Chat history: `{_history_path()}`\n\n"
        "Try: *\"Scan /path/to/repo and tell me what's interesting\"*"
    )
    await cl.Message(
        content=welcome,
        actions=[
            cl.Action(
                name="show_patterns",
                label="View saved patterns",
                icon="library",
                payload={},
            ),
            cl.Action(
                name="show_history_path",
                label="History file",
                icon="file-clock",
                payload={},
            ),
            cl.Action(
                name="show_mcp_status",
                label="MCP server",
                icon="server",
                payload={},
            ),
        ],
    ).send()


@cl.action_callback("show_patterns")
async def show_patterns(action: cl.Action):
    """Show saved patterns from the vault."""
    _save_history_event("ui_action", "show_patterns", payload=action.payload)
    await _send_pattern_list()


@cl.action_callback("refresh_patterns")
async def refresh_patterns(action: cl.Action):
    """Refresh the saved patterns list."""
    _save_history_event("ui_action", "refresh_patterns", payload=action.payload)
    await _send_pattern_list()


@cl.action_callback("open_pattern")
async def open_pattern(action: cl.Action):
    """Open a saved pattern by ID."""
    pattern_id = int(action.payload["pattern_id"])
    conn = get_connection(DB_PATH)
    init_db(conn)
    pattern = get_pattern(conn, pattern_id)
    conn.close()

    _save_history_event("ui_action", "open_pattern", pattern_id=pattern_id)

    if not pattern:
        await cl.Message(content=f"Pattern #{pattern_id} was not found.").send()
        return

    await cl.Message(
        content=_format_pattern_detail(pattern),
        actions=[
            cl.Action(
                name="show_patterns",
                label="Back to patterns",
                icon="arrow-left",
                payload={},
            )
        ],
    ).send()


@cl.action_callback("show_history_path")
async def show_history_path(action: cl.Action):
    """Show where chat history is persisted."""
    _save_history_event("ui_action", "show_history_path", payload=action.payload)
    await cl.Message(
        content=(
            "**Chat History**\n\n"
            f"This session is being saved to:\n\n`{_history_path()}`\n\n"
            "Each line is one JSON event, so the file can be searched, parsed, "
            "or imported later without a migration."
        )
    ).send()


@cl.action_callback("show_mcp_status")
async def show_mcp_status(action: cl.Action):
    """Show MCP server status and exposed tools."""
    _save_history_event("ui_action", "show_mcp_status", payload=action.payload)
    await _send_mcp_status()


@cl.action_callback("refresh_mcp_status")
async def refresh_mcp_status(action: cl.Action):
    """Refresh MCP server status and exposed tools."""
    _save_history_event("ui_action", "refresh_mcp_status", payload=action.payload)
    await _send_mcp_status()


# ── Message handler ──────────────────────────────────────

@cl.on_message
async def on_message(message: cl.Message):
    """Handle user messages with Claude tool-use agentic loop."""
    # Maintain conversation history
    messages = cl.user_session.get("messages", [])
    messages.append({"role": "user", "content": message.content})
    _save_history_event("user", message.content)

    normalized_message = message.content.strip().lower()
    pattern_match = re.search(r"(?:open|show|view)\s+pattern\s+#?(\d+)", normalized_message)
    if pattern_match:
        await open_pattern(
            cl.Action(
                name="open_pattern",
                label="Open pattern",
                payload={"pattern_id": int(pattern_match.group(1))},
            )
        )
        return

    if (
        "saved patterns" in normalized_message
        or normalized_message in {"patterns", "show patterns", "view patterns", "list patterns"}
    ):
        await _send_pattern_list()
        return

    if normalized_message in {
        "mcp",
        "mcp status",
        "show mcp",
        "show mcp status",
        "mcp server",
        "mcp tools",
        "show mcp tools",
    }:
        await _send_mcp_status()
        return

    try:
        client = make_async_client()
    except RuntimeError as e:
        _save_history_event("error", str(e), stage="make_client")
        await cl.Message(content=f"**Backend not configured:** {e}").send()
        return

    model = get_model()

    tools = [
        {
            "name": t["name"],
            "description": t["description"],
            "input_schema": t["input_schema"],
        }
        for t in TOOL_DEFINITIONS
    ]

    current_messages = list(messages)
    rounds = 0

    # The final text we'll save to history
    final_text_parts = []

    while rounds < MAX_TOOL_ROUNDS:
        rounds += 1

        try:
            response = await client.messages.create(
                model=model,
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                tools=tools,
                messages=current_messages,
            )
        except Exception as e:
            _save_history_event("error", str(e), stage="api_call")
            await cl.Message(content=f"API error: {e}").send()
            return

        assistant_content = response.content
        tool_use_blocks = []

        # Process text blocks — stream as a message
        text_parts = []
        for block in assistant_content:
            if block.type == "text" and block.text.strip():
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_use_blocks.append(block)

        # Send any text from this round
        if text_parts:
            combined = "\n".join(text_parts)
            final_text_parts.append(combined)
            _save_history_event("assistant", combined)
            msg = cl.Message(content=combined)
            await msg.send()

        # If no tool calls, we're done
        if response.stop_reason == "end_turn" or not tool_use_blocks:
            break

        # Execute tool calls with Chainlit Step visualization
        current_messages.append({"role": "assistant", "content": assistant_content})

        tool_results = []
        for block in tool_use_blocks:
            _save_history_event(
                "tool_call",
                block.name,
                tool_input=block.input,
            )
            # Show tool call as a step
            async with cl.Step(
                name=block.name,
                type="tool",
                show_input=True,
            ) as step:
                # Show input
                step.input = json.dumps(block.input, indent=2)

                # Execute
                result = execute_tool(block.name, block.input, db_path=DB_PATH)

                # Show output (truncated for display)
                display_result = result
                if len(result) > 2000:
                    display_result = result[:2000] + "\n... (truncated)"
                step.output = f"```json\n{display_result}\n```"

            _save_history_event(
                "tool_result",
                result[:4000] if len(result) > 4000 else result,
                tool_name=block.name,
                truncated=len(result) > 4000,
            )
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": result,
            })

        current_messages.append({"role": "user", "content": tool_results})

    # Save assistant response to history
    if final_text_parts:
        messages.append({"role": "assistant", "content": "\n".join(final_text_parts)})
    cl.user_session.set("messages", messages)
