from types import SimpleNamespace

from src.client import extract_usage_snapshot
from src.store.db import get_connection, get_daily_token_usage, init_db, record_token_usage


def test_extract_usage_snapshot_prefers_provider_counts():
    response = SimpleNamespace(
        usage={"input_tokens": 120, "output_tokens": 30, "cache_read_input_tokens": 10},
        content=[SimpleNamespace(type="text", text="hello")],
    )

    snapshot = extract_usage_snapshot(
        response,
        system="system prompt",
        messages=[{"role": "user", "content": "hi"}],
    )

    assert snapshot == {
        "input_tokens": 130,
        "output_tokens": 30,
        "total_tokens": 160,
        "estimated": False,
        "usage": {"input_tokens": 120, "output_tokens": 30, "cache_read_input_tokens": 10},
    }


def test_extract_usage_snapshot_estimates_when_provider_usage_missing():
    response = SimpleNamespace(
        usage=None,
        content=[SimpleNamespace(type="text", text="Generated answer")],
    )

    snapshot = extract_usage_snapshot(
        response,
        system="system prompt",
        messages=[{"role": "user", "content": "Tell me something useful"}],
    )

    assert snapshot["estimated"] is True
    assert snapshot["input_tokens"] > 0
    assert snapshot["output_tokens"] > 0
    assert snapshot["total_tokens"] == snapshot["input_tokens"] + snapshot["output_tokens"]


def test_daily_token_usage_groups_by_day_and_provider(tmp_path):
    conn = get_connection(tmp_path / "patterns.db")
    try:
        init_db(conn)
        record_token_usage(
            conn,
            provider="anthropic",
            model="claude-sonnet",
            flow="chat",
            operation="agent_turn",
            input_tokens=100,
            output_tokens=50,
            total_tokens=150,
            estimated=False,
            created_at=1_700_000_000,
        )
        record_token_usage(
            conn,
            provider="anthropic",
            model="claude-sonnet",
            flow="indexing",
            operation="extract_patterns",
            input_tokens=60,
            output_tokens=20,
            total_tokens=80,
            estimated=True,
            created_at=1_700_000_100,
        )
        record_token_usage(
            conn,
            provider="ollama",
            model="qwen2.5-coder:7b",
            flow="chat",
            operation="agent_turn",
            input_tokens=40,
            output_tokens=10,
            total_tokens=50,
            estimated=True,
            created_at=1_700_000_100,
        )

        rows = get_daily_token_usage(conn, days=10_000)
    finally:
        conn.close()

    anthropic_row = next(row for row in rows if row["provider"] == "anthropic")
    ollama_row = next(row for row in rows if row["provider"] == "ollama")

    assert anthropic_row["requests"] == 2
    assert anthropic_row["input_tokens"] == 160
    assert anthropic_row["output_tokens"] == 70
    assert anthropic_row["total_tokens"] == 230
    assert anthropic_row["estimated_requests"] == 1

    assert ollama_row["requests"] == 1
    assert ollama_row["total_tokens"] == 50
