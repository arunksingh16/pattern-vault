"""
Pattern Vault — CLI entry point.

Usage:
    python -m pattern_vault.cli index <directory> [--dry-run] [--repo-name NAME]
    python -m pattern_vault.cli search <query> [--category CAT] [--language LANG]
    python -m pattern_vault.cli stats
    python -m pattern_vault.cli chat
    python -m pattern_vault.cli serve [--port PORT]
"""

import argparse
import json


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


def cmd_serve(args):
    """Run the MCP server."""
    from .server.mcp_server import mcp

    print("Starting Pattern Vault MCP server...")
    if args.transport == "http":
        mcp.settings.host = args.host
        mcp.settings.port = args.port
        mcp.run(transport="streamable-http")
    else:
        mcp.run()


def main():
    parser = argparse.ArgumentParser(description="Pattern Vault — code pattern indexer and retriever")
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
    p_serve = subparsers.add_parser("serve", help="Run MCP server")
    p_serve.add_argument("--host", default="127.0.0.1", help="HTTP host")
    p_serve.add_argument("--port", type=int, default=8000, help="HTTP port")
    p_serve.add_argument("--transport", choices=["stdio", "http"], default="stdio", help="Transport type")

    args = parser.parse_args()

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
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
