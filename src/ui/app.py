"""
Pattern Vault — Chainlit Chat UI.

Run with: chainlit run src/ui/app.py

Provides:
- Interactive repo analysis via Claude tool-use loop
- Step-by-step visualization of tool calls
- Pattern search and browsing
- Manual pattern saving

Requires: a configured model backend (Anthropic, Bedrock, Bifrost, or Ollama).
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
from src.agent.tools import TOOL_DEFINITIONS, execute_tool, get_workspace_roots  # noqa: E402
from src.agent.orchestrator import SYSTEM_PROMPT  # noqa: E402
from src.server.mcp_server import mcp as pattern_vault_mcp  # noqa: E402
from src.store.db import (  # noqa: E402
    delete_pattern,
    get_connection,
    get_pattern,
    get_stats,
    init_db,
    list_categories,
    list_tags,
    resolve_db_path,
    search_fts,
    update_pattern,
)

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
EDITABLE_PATTERN_FIELDS = {
    "name",
    "summary",
    "category",
    "language",
    "tags",
    "quality_signal",
    "source_repo",
    "source_file",
    "line_start",
    "line_end",
    "code_text",
}


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


def _load_recent_insights(limit: int = 8) -> list[dict]:
    """Load recent repo insights for the admin dashboard."""
    conn = get_connection(DB_PATH)
    init_db(conn)
    rows = conn.execute(
        """SELECT id, repo_path, insight_text, tags, created_at
           FROM repo_insights
           ORDER BY created_at DESC, id DESC
           LIMIT ?""",
        (limit,),
    ).fetchall()
    conn.close()

    insights = []
    for row in rows:
        insight = dict(row)
        insight["tags"] = json.loads(insight["tags"])
        insights.append(insight)
    return insights


def _load_dashboard() -> dict:
    """Load compact vault state for the first screen."""
    conn = get_connection(DB_PATH)
    init_db(conn)
    try:
        return {
            "stats": get_stats(conn),
            "categories": list_categories(conn),
            "tags": list_tags(conn),
            "patterns": _load_patterns(limit=5),
            "insights": _load_recent_insights(limit=4),
        }
    finally:
        conn.close()


def _parse_pattern_edit_payload(raw_payload: str) -> dict:
    """Parse and normalize a JSON edit payload from the admin UI."""
    try:
        payload = json.loads(raw_payload)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON: {exc.msg}") from exc

    if not isinstance(payload, dict):
        raise ValueError("Edit payload must be a JSON object.")

    unknown = sorted(set(payload) - EDITABLE_PATTERN_FIELDS)
    if unknown:
        raise ValueError(f"Unsupported field(s): {', '.join(unknown)}")

    normalized = {}
    for key, value in payload.items():
        if key == "tags":
            if isinstance(value, str):
                normalized[key] = [tag.strip() for tag in value.split(",") if tag.strip()]
            elif isinstance(value, list) and all(isinstance(tag, str) for tag in value):
                normalized[key] = [tag.strip() for tag in value if tag.strip()]
            else:
                raise ValueError("tags must be a string or a list of strings.")
        elif key in {"line_start", "line_end"}:
            if value is None:
                continue
            try:
                normalized[key] = int(value)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{key} must be an integer.") from exc
        elif value is not None:
            normalized[key] = value
    return normalized


def _format_tags(tags: list[str], limit: int = 6) -> str:
    visible = tags[:limit]
    return ", ".join(f"`{tag}`" for tag in visible) or "-"


def _format_workspace_stats(stats: dict) -> str:
    return "\n".join([
        "| Vault | Count |",
        "|------|------:|",
        f"| Patterns | **{stats['patterns']}** |",
        f"| Code chunks | **{stats['chunks']}** |",
        f"| Repo insights | **{stats['insights']}** |",
    ])


def _format_active_system(stats: dict) -> str:
    try:
        backend_desc = describe_backend()
    except Exception as exc:  # noqa: BLE001
        backend_desc = f"not configured ({exc})"

    roots = ", ".join(f"`{root}`" for root in get_workspace_roots())
    languages = _format_tags(stats["languages"][:8], limit=8)
    return "\n".join([
        "**Active System**",
        "",
        f"- Backend: **{backend_desc}**",
        f"- Database: `{DB_PATH}`",
        f"- History: `{_history_path()}`",
        f"- Workspace roots: {roots or '-'}",
        f"- Languages indexed: {languages}",
    ])


def _format_recent_patterns(patterns: list[dict]) -> str:
    if not patterns:
        return "\n".join([
            "**Recent Patterns**",
            "",
            "No saved patterns yet. Scan a repo or save a pattern from chat to seed the vault.",
        ])

    lines = ["**Recent Patterns**", ""]
    for pattern in patterns:
        source = pattern.get("source_file") or pattern.get("source_repo") or "manual"
        tags = _format_tags(pattern["tags"], limit=3)
        lines.append(
            f"- **#{pattern['id']} {pattern['name']}** "
            f"`{pattern['category']}` `{pattern['language']}` {tags} "
            f"- `{source}`"
        )
    return "\n".join(lines)


def _format_recent_insights(insights: list[dict]) -> str:
    if not insights:
        return "\n".join([
            "**Recent Insights**",
            "",
            "No repo insights saved yet. Ask the copilot to summarize architecture or risks.",
        ])

    lines = ["**Recent Insights**", ""]
    for insight in insights:
        text = insight["insight_text"].replace("\n", " ")
        if len(text) > 120:
            text = text[:117] + "..."
        lines.append(f"- `{insight['repo_path']}` - {text}")
    return "\n".join(lines)


def _format_suggested_actions(dashboard: dict) -> str:
    categories = _format_tags(dashboard["categories"][:8], limit=8)
    tags = _format_tags(dashboard["tags"][:12], limit=12)
    return "\n".join([
        "**Next Moves**",
        "",
        "- Scan a repository and ask the copilot to save reusable patterns.",
        "- Search the vault before writing new code.",
        "- Open system status when backend, database, MCP, or workspace roots look wrong.",
        "",
        f"Categories: {categories}",
        f"Top tags: {tags}",
    ])


def _format_dashboard() -> str:
    dashboard = _load_dashboard()
    stats = dashboard["stats"]
    return "\n\n".join([
        "**Pattern Vault Workspace**",
        _format_workspace_stats(stats),
        _format_active_system(stats),
        _format_recent_patterns(dashboard["patterns"]),
        _format_recent_insights(dashboard["insights"]),
        _format_suggested_actions(dashboard),
    ])


def _format_pattern_list(patterns: list[dict]) -> str:
    if not patterns:
        return (
            "**Saved Patterns**\n\n"
            "No patterns are saved yet. Ask me to scan a repo or save a pattern."
        )

    lines = [
        f"**Pattern Browser** — latest {len(patterns)}",
        "",
        "| ID | Name | Category | Language | Tags | Source |",
        "|---:|------|----------|----------|------|--------|",
    ]
    for pattern in patterns:
        source = pattern.get("source_file") or pattern.get("source_repo") or "-"
        tags = ", ".join(pattern["tags"][:4])
        name = pattern["name"]
        lines.append(
            f"| {pattern['id']} | {name} | {pattern['category']} | "
            f"{pattern['language']} | {tags or '-'} | {source} |"
        )
    lines.extend([
        "",
        "Open a pattern to review, edit metadata, or delete it from the vault.",
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


def _search_patterns(query: str, limit: int = PATTERN_ACTION_LIMIT) -> list[dict]:
    """Search saved patterns for the direct UI search action."""
    conn = get_connection(DB_PATH)
    init_db(conn)
    try:
        return search_fts(conn, query, limit=limit)
    finally:
        conn.close()


async def _send_pattern_search(query: str) -> None:
    patterns = _search_patterns(query)
    actions = [
        cl.Action(
            name="search_patterns_ui",
            label="Search again",
            icon="search",
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

    if patterns:
        content = f"**Search Results** - `{query}`\n\n{_format_pattern_list(patterns)}"
    else:
        content = "\n".join([
            "**Search Results**",
            "",
            f"No saved patterns matched `{query}`.",
            "Scan a repo or ask the copilot to save a pattern, then search again.",
        ])
    await cl.Message(content=content, actions=actions).send()


def _format_insight_list(insights: list[dict]) -> str:
    if not insights:
        return "**Repo Insights**\n\nNo repo insights are saved yet."

    lines = [
        f"**Repo Insights** — latest {len(insights)}",
        "",
        "| ID | Repo | Tags | Insight |",
        "|---:|------|------|---------|",
    ]
    for insight in insights:
        tags = ", ".join(insight["tags"][:4]) or "-"
        text = insight["insight_text"].replace("\n", " ")
        if len(text) > 140:
            text = text[:137] + "..."
        lines.append(f"| {insight['id']} | `{insight['repo_path']}` | {tags} | {text} |")
    return "\n".join(lines)


async def _send_insight_list() -> None:
    await cl.Message(
        content=_format_insight_list(_load_recent_insights()),
        actions=[
            cl.Action(
                name="refresh_insights",
                label="Refresh",
                icon="refresh-cw",
                payload={},
            )
        ],
    ).send()


async def _send_admin_help() -> None:
    await cl.Message(
        content="\n".join([
            "**Vault Admin**",
            "",
            "Pattern records can be reviewed and managed from the browser actions.",
            "",
            "Supported chat commands:",
            "- `view patterns`",
            "- `open pattern #12`",
            "- `edit pattern #12`",
            "- `delete pattern #12`",
            "- `repo insights`",
            "- `mcp status`",
            "",
            "Edit accepts a JSON object with fields like `name`, `summary`, `category`, "
            "`language`, `tags`, `quality_signal`, `source_repo`, `source_file`, "
            "`line_start`, `line_end`, and `code_text`.",
        ]),
    ).send()


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


def _format_system_status() -> str:
    dashboard = _load_dashboard()
    stats = dashboard["stats"]
    roots = "\n".join(f"- `{root}`" for root in get_workspace_roots()) or "- none"

    try:
        backend_desc = describe_backend()
        backend_status = f"ready - **{backend_desc}**"
    except Exception as exc:  # noqa: BLE001
        backend_status = f"not configured - {exc}"

    http_status, http_detail = _mcp_http_status()
    return "\n".join([
        "**System Status**",
        "",
        f"Backend: {backend_status}",
        f"Database: `ready` (`{DB_PATH}`)",
        f"Vault: **{stats['patterns']}** patterns, "
        f"**{stats['chunks']}** chunks, **{stats['insights']}** insights",
        f"Chat history: `{_history_path()}`",
        f"MCP transport: `{MCP_TRANSPORT}`",
        f"MCP HTTP endpoint: `{http_status}` - {http_detail}",
        "",
        "**Workspace Roots**",
        "",
        roots,
    ])


async def _send_system_status() -> None:
    await cl.Message(
        content=_format_system_status(),
        actions=[
            cl.Action(
                name="show_mcp_status",
                label="MCP details",
                icon="server",
                payload={},
            ),
            cl.Action(
                name="open_system_status",
                label="Refresh",
                icon="refresh-cw",
                payload={},
            ),
        ],
    ).send()


# ── Lifecycle ────────────────────────────────────────────

@cl.on_chat_start
async def on_chat_start():
    """Initialize session state and show welcome message."""
    cl.user_session.set("messages", [])
    cl.user_session.set("history_path", str(_history_path()))
    _save_history_event("system", "chat_started", history_path=str(_history_path()))

    await cl.Message(
        content=_format_dashboard(),
        actions=[
            cl.Action(
                name="scan_repo",
                label="Scan repo",
                icon="folder-search",
                payload={},
            ),
            cl.Action(
                name="search_patterns_ui",
                label="Search patterns",
                icon="search",
                payload={},
            ),
            cl.Action(
                name="show_patterns",
                label="View saved patterns",
                icon="library",
                payload={},
            ),
            cl.Action(
                name="show_insights",
                label="Repo insights",
                icon="list-tree",
                payload={},
            ),
            cl.Action(
                name="show_admin_help",
                label="Admin",
                icon="settings",
                payload={},
            ),
            cl.Action(
                name="show_history_path",
                label="History file",
                icon="file-clock",
                payload={},
            ),
            cl.Action(
                name="open_system_status",
                label="System status",
                icon="activity",
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


@cl.action_callback("search_patterns_ui")
async def search_patterns_ui(action: cl.Action):
    """Ask for a vault search query and show matching saved patterns."""
    _save_history_event("ui_action", "search_patterns_ui", payload=action.payload)
    response = await cl.AskUserMessage(
        content="Search saved patterns by topic, tag, category, language, or source.",
        timeout=120,
    ).send()
    if not response:
        await cl.Message(content="Search cancelled.").send()
        return

    query = response["output"].strip()
    if not query:
        await cl.Message(content="Search cancelled.").send()
        return

    _save_history_event("ui_action", "pattern_search", query=query)
    await _send_pattern_search(query)


@cl.action_callback("scan_repo")
async def scan_repo(action: cl.Action):
    """Start a repo scan through the existing copilot/tool loop."""
    _save_history_event("ui_action", "scan_repo", payload=action.payload)
    response = await cl.AskUserMessage(
        content=(
            "Enter the absolute path of the repository to scan. "
            "It must be inside `PATTERN_VAULT_WORKSPACE_ROOTS`."
        ),
        timeout=180,
    ).send()
    if not response:
        await cl.Message(content="Repo scan cancelled.").send()
        return

    repo_path = response["output"].strip()
    if not repo_path:
        await cl.Message(content="Repo scan cancelled.").send()
        return

    prompt = (
        f"Scan repository `{repo_path}` for reusable engineering patterns. "
        "Start with a directory scan, inspect the most relevant source files, "
        "save high-confidence reusable patterns, and summarize what changed."
    )
    await cl.Message(content=f"Starting repo scan for `{repo_path}`.").send()
    await on_message(cl.Message(content=prompt))


@cl.action_callback("show_insights")
async def show_insights(action: cl.Action):
    """Show saved repo insights from the vault."""
    _save_history_event("ui_action", "show_insights", payload=action.payload)
    await _send_insight_list()


@cl.action_callback("refresh_insights")
async def refresh_insights(action: cl.Action):
    """Refresh the repo insight list."""
    _save_history_event("ui_action", "refresh_insights", payload=action.payload)
    await _send_insight_list()


@cl.action_callback("show_admin_help")
async def show_admin_help(action: cl.Action):
    """Show UI/admin operations."""
    _save_history_event("ui_action", "show_admin_help", payload=action.payload)
    await _send_admin_help()


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
                name="edit_pattern",
                label="Edit metadata",
                icon="pencil",
                payload={"pattern_id": pattern_id},
            ),
            cl.Action(
                name="delete_pattern",
                label="Delete",
                icon="trash-2",
                payload={"pattern_id": pattern_id},
            ),
            cl.Action(
                name="show_patterns",
                label="Back to patterns",
                icon="arrow-left",
                payload={},
            )
        ],
    ).send()


@cl.action_callback("edit_pattern")
async def edit_pattern(action: cl.Action):
    """Prompt for a JSON metadata patch and apply it to a pattern."""
    pattern_id = int(action.payload["pattern_id"])
    conn = get_connection(DB_PATH)
    init_db(conn)
    pattern = get_pattern(conn, pattern_id)
    conn.close()

    _save_history_event("ui_action", "edit_pattern", pattern_id=pattern_id)

    if not pattern:
        await cl.Message(content=f"Pattern #{pattern_id} was not found.").send()
        return

    template = {
        "name": pattern["name"],
        "category": pattern["category"],
        "language": pattern["language"],
        "tags": pattern["tags"],
        "summary": pattern["summary"],
        "quality_signal": pattern.get("quality_signal") or "",
    }
    response = await cl.AskUserMessage(
        content=(
            f"Send a JSON object with the fields to update for pattern #{pattern_id}.\n\n"
            f"Current editable metadata:\n```json\n{json.dumps(template, indent=2)}\n```"
        ),
        timeout=180,
    ).send()
    if not response:
        await cl.Message(content="Edit cancelled.").send()
        return

    try:
        updates = _parse_pattern_edit_payload(response["output"])
        conn = get_connection(DB_PATH)
        init_db(conn)
        try:
            updated = update_pattern(conn, pattern_id, **updates)
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001
        _save_history_event("error", str(exc), stage="edit_pattern", pattern_id=pattern_id)
        await cl.Message(content=f"Could not update pattern #{pattern_id}: {exc}").send()
        return

    if not updated:
        await cl.Message(content=f"Pattern #{pattern_id} was not found.").send()
        return

    _save_history_event("ui_action", "pattern_updated", pattern_id=pattern_id, updates=updates)
    await cl.Message(content=f"Pattern #{pattern_id} updated.").send()
    await open_pattern(
        cl.Action(
            name="open_pattern",
            label="Open pattern",
            payload={"pattern_id": pattern_id},
        )
    )


@cl.action_callback("delete_pattern")
async def delete_pattern_action(action: cl.Action):
    """Confirm and delete a pattern from the vault."""
    pattern_id = int(action.payload["pattern_id"])
    response = await cl.AskActionMessage(
        content=f"Delete pattern #{pattern_id}? This removes the pattern and stored chunks.",
        actions=[
            cl.Action(name="confirm_delete_pattern", label="Delete", icon="trash-2", payload={"confirm": True}),
            cl.Action(name="cancel_delete_pattern", label="Cancel", icon="x", payload={"confirm": False}),
        ],
        timeout=90,
    ).send()

    _save_history_event("ui_action", "delete_pattern", pattern_id=pattern_id)
    if not response or not response.get("payload", {}).get("confirm"):
        await cl.Message(content="Delete cancelled.").send()
        return

    conn = get_connection(DB_PATH)
    init_db(conn)
    deleted = delete_pattern(conn, pattern_id)
    conn.close()

    if deleted:
        _save_history_event("ui_action", "pattern_deleted", pattern_id=pattern_id)
        await cl.Message(content=f"Pattern #{pattern_id} deleted.").send()
        await _send_pattern_list()
    else:
        await cl.Message(content=f"Pattern #{pattern_id} was not found.").send()


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


@cl.action_callback("open_system_status")
async def open_system_status(action: cl.Action):
    """Show backend, database, history, workspace, and MCP summary."""
    _save_history_event("ui_action", "open_system_status", payload=action.payload)
    await _send_system_status()


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

    edit_match = re.search(r"edit\s+pattern\s+#?(\d+)", normalized_message)
    if edit_match:
        await edit_pattern(
            cl.Action(
                name="edit_pattern",
                label="Edit pattern",
                payload={"pattern_id": int(edit_match.group(1))},
            )
        )
        return

    delete_match = re.search(r"delete\s+pattern\s+#?(\d+)", normalized_message)
    if delete_match:
        await delete_pattern_action(
            cl.Action(
                name="delete_pattern",
                label="Delete pattern",
                payload={"pattern_id": int(delete_match.group(1))},
            )
        )
        return

    if (
        "saved patterns" in normalized_message
        or normalized_message in {"patterns", "show patterns", "view patterns", "list patterns"}
    ):
        await _send_pattern_list()
        return

    search_match = re.search(r"^(?:search|find)\s+patterns?\s+(.+)$", message.content.strip(), re.IGNORECASE)
    if search_match:
        await _send_pattern_search(search_match.group(1).strip())
        return

    scan_match = re.search(r"^scan\s+repo\s+(.+)$", message.content.strip(), re.IGNORECASE)
    if scan_match:
        scan_path = scan_match.group(1).strip()
        message.content = (
            f"Scan repository `{scan_path}` for reusable engineering patterns. "
            "Start with a directory scan, inspect the most relevant source files, "
            "save high-confidence reusable patterns, and summarize what changed."
        )
        messages[-1]["content"] = message.content

    if normalized_message in {"admin", "admin help", "vault admin", "help admin"}:
        await _send_admin_help()
        return

    if normalized_message in {"insights", "repo insights", "show insights", "view insights"}:
        await _send_insight_list()
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

    if normalized_message in {"system", "system status", "status", "workspace status"}:
        await _send_system_status()
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
