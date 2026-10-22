"""
Pattern Vault — CLI entry point.

Usage (also available as `pv`):
    pattern-vault serve [--host HOST] [--port PORT]     # API + UI on one port
    pattern-vault setup [--yes]                         # model backend, code folders
    pattern-vault index <directory> [--dry-run] [--repo-name NAME]
    pattern-vault search <query> [--category CAT] [--language LANG]
    pattern-vault stats
    pattern-vault chat
    pattern-vault mcp [--transport stdio|http] [--port PORT]
    pattern-vault --version
"""

import argparse
import json
import socket
import sys
from importlib.metadata import PackageNotFoundError, version

LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
ALL_INTERFACES = {"0.0.0.0", "::"}


def cmd_index(args):
    from .indexer.batch import index_directory

    stats = index_directory(
        directory=args.directory,
        repo_name=args.repo_name,
        dry_run=args.dry_run,
        profile=args.profile,
        on_progress=lambda msg: print(f"  {msg}"),
    )

    print("\nResults:")
    print(f"  Files scanned: {stats.files_scanned}")
    print(f"  Chunks extracted: {stats.chunks_extracted}")
    print(f"  Patterns found: {stats.patterns_found}")
    print(f"  Patterns stored: {stats.patterns_stored}")
    if stats.errors:
        print(f"  Errors: {len(stats.errors)}")
        for e in stats.errors:
            print(f"    {e}")


def cmd_search(args):
    from .store.db import get_connection, init_db, search_fts, get_pattern

    conn = get_connection()
    init_db(conn)

    results = search_fts(conn, args.query, category=args.category, language=args.language, limit=args.limit)

    if not results:
        print(f"No patterns found matching '{args.query}'")
        return

    print(f"Found {len(results)} patterns:\n")
    for r in results:
        tags = ", ".join(r["tags"]) if r["tags"] else "none"
        print(f"  [{r['id']}] {r['name']}")
        print(f"      Category: {r['category']} | Language: {r['language']} | Tags: {tags}")
        print(f"      {r['summary'][:120]}{'...' if len(r['summary']) > 120 else ''}")
        if r.get("source_file"):
            print(f"      Source: {r['source_file']}")
        print()

    if args.full and results:
        pid = results[0]["id"]
        pattern = get_pattern(conn, pid)
        if pattern and pattern["chunks"]:
            print(f"--- Full code for [{pid}] {pattern['name']} ---\n")
            for chunk in pattern["chunks"]:
                print(chunk["code_text"])
                print()

    conn.close()


def cmd_stats(args):
    from .store.db import get_connection, init_db, get_stats

    conn = get_connection()
    init_db(conn)
    stats = get_stats(conn)
    conn.close()

    print("Pattern Vault Statistics")
    print(f"  Patterns: {stats['patterns']}")
    print(f"  Code chunks: {stats['chunks']}")
    print(f"  Repo insights: {stats['insights']}")
    print(f"  Categories: {', '.join(stats['categories']) or 'none'}")
    print(f"  Languages: {', '.join(stats['languages']) or 'none'}")


def cmd_chat(args):
    """Interactive chat with the agent using the configured model backend."""
    from .agent.orchestrator import run_agent_turn

    print("Pattern Vault — Interactive Analysis")
    print("Type a message to analyse repos, find patterns, or ask questions.")
    print("Type 'quit' to exit.\n")

    messages = []

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye!")
            break

        if user_input.lower() in ("quit", "exit", "q"):
            break
        if not user_input:
            continue

        messages.append({"role": "user", "content": user_input})

        print("\nAssistant: ", end="", flush=True)
        assistant_text = []
        for event in run_agent_turn(messages):
            if event["type"] == "text":
                print(event["content"], end="", flush=True)
                assistant_text.append(event["content"])
            elif event["type"] == "tool_call":
                print(f"\n  🔧 {event['name']}({json.dumps(event['input'])[:80]}...)", flush=True)
            elif event["type"] == "tool_result":
                print(f"  ✓ {event['name']} returned", flush=True)
            elif event["type"] == "error":
                print(f"\n  ❌ {event['message']}", flush=True)
            elif event["type"] == "done":
                pass

        print("\n")
        if assistant_text:
            messages.append({"role": "assistant", "content": "\n".join(assistant_text)})


def port_available(host: str, port: int) -> bool:
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as sock:
        # Match uvicorn: TIME_WAIT leftovers from a just-stopped server don't make a port busy
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def cmd_serve(args):
    """Run the API and the built UI on one port."""
    import uvicorn

    from . import settings
    from .api.main import create_app, default_web_dist

    host = args.host
    port = args.port or settings.get("server.port")
    if not port_available(host, port):
        print(f"Port {port} is already in use. Try: pattern-vault serve --port {port + 1}", file=sys.stderr)
        sys.exit(1)

    allow_any_host = host in ALL_INTERFACES
    if host not in LOOPBACK_HOSTS:
        print(f"Warning: listening on {host} makes Settings and your API keys reachable from the network.")
    web_dist = default_web_dist()
    if web_dist is None:
        print("UI not built — run: cd web && npm run build (or use the Vite dev server)")
    print(f"Pattern Vault → http://localhost:{port}")

    extra_hosts = [] if host in LOOPBACK_HOSTS or allow_any_host else [host]
    app = create_app(web_dist=web_dist, extra_hosts=extra_hosts, allow_any_host=allow_any_host)
    uvicorn.run(app, host=host, port=port)


def cmd_setup(args):
    """Ask the setup questions and write the config file."""
    from . import setup_wizard
    from .settings import ConfigError

    try:
        setup_wizard.run_setup(assume_yes=args.yes)
    except ConfigError as exc:
        print(f"Your config file has an error, so setup didn't change it: {exc}", file=sys.stderr)
        sys.exit(1)
    except (KeyboardInterrupt, EOFError):
        print("\nSetup cancelled; nothing was saved.", file=sys.stderr)
        sys.exit(1)


def cmd_mcp(args):
    """Run the MCP server."""
    from .server.mcp_server import mcp

    print("Starting Pattern Vault MCP server...")
    if args.transport == "http":
        mcp.settings.host = args.host
        mcp.settings.port = args.port
        mcp.run(transport="streamable-http")
    else:
        mcp.run()


def _package_version() -> str:
    try:
        return version("pattern-vault")
    except PackageNotFoundError:
        return "unknown"


def main(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(
        prog="pattern-vault", description="Pattern Vault — code pattern indexer and retriever"
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {_package_version()}")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # index
    p_index = subparsers.add_parser("index", help="Index a directory for patterns")
    p_index.add_argument("directory", help="Path to the directory to index")
    p_index.add_argument("--dry-run", action="store_true", help="Scan and chunk without calling Claude")
    p_index.add_argument("--repo-name", help="Name for the source repo")
    p_index.add_argument(
        "--profile",
        choices=["curated", "balanced", "comprehensive"],
        default="curated",
        help="Indexing volume profile",
    )

    # search
    p_search = subparsers.add_parser("search", help="Search for patterns")
    p_search.add_argument("query", help="Search query")
    p_search.add_argument("--category", help="Filter by category")
    p_search.add_argument("--language", help="Filter by language")
    p_search.add_argument("--limit", type=int, default=10, help="Max results")
    p_search.add_argument("--full", action="store_true", help="Show full code of top result")

    # stats
    subparsers.add_parser("stats", help="Show vault statistics")

    # chat
    subparsers.add_parser("chat", help="Interactive agent chat")

    # serve
    p_serve = subparsers.add_parser("serve", help="Run the API and UI on one port")
    p_serve.add_argument("--host", default="127.0.0.1", help="Host to listen on (default: 127.0.0.1)")
    p_serve.add_argument("--port", type=int, default=None, help="Port (default: server.port in config, 8001)")

    # setup
    p_setup = subparsers.add_parser("setup", help="Choose a model backend and code folders")
    p_setup.add_argument("--yes", action="store_true", help="Accept the defaults without asking")

    # mcp
    p_mcp = subparsers.add_parser("mcp", help="Run the MCP server")
    p_mcp.add_argument("--host", default="127.0.0.1", help="HTTP host")
    p_mcp.add_argument("--port", type=int, default=8000, help="HTTP port")
    p_mcp.add_argument("--transport", choices=["stdio", "http"], default="stdio", help="Transport type")

    args = parser.parse_args(argv)

    if args.command == "index":
        cmd_index(args)
    elif args.command == "search":
        cmd_search(args)
    elif args.command == "stats":
        cmd_stats(args)
    elif args.command == "chat":
        cmd_chat(args)
    elif args.command == "serve":
        cmd_serve(args)
    elif args.command == "setup":
        cmd_setup(args)
    elif args.command == "mcp":
        cmd_mcp(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
