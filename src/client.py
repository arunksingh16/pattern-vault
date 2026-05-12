"""
Pattern Vault — Anthropic client factory.

Supports three backends, selected by environment variables:

  PATTERN_VAULT_BACKEND=anthropic  (default)
    Requires: ANTHROPIC_API_KEY
    Model: claude-sonnet-4-20250514

  PATTERN_VAULT_BACKEND=bedrock
    Requires: AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY (or ~/.aws/credentials)
    Optional: AWS_REGION (default: us-east-1)
    Model: anthropic.claude-sonnet-4-5-20250929-v1:0

  PATTERN_VAULT_BACKEND=bifrost
    Requires: BIFROST_URL (e.g. http://localhost:8080/anthropic)
    Optional: BIFROST_API_KEY (default: "dummy")
    Model: same as anthropic (bifrost translates)

Usage:
    from src.client import make_client, make_async_client, get_model

    client = make_client()          # sync
    client = make_async_client()    # async
    model  = get_model()            # correct model ID for the backend
"""

import os


# ── Backend detection ──────────────────────────────────────────

def get_backend() -> str:
    return os.environ.get("PATTERN_VAULT_BACKEND", "anthropic").lower()


def get_model() -> str:
    """Return the correct model ID for the active backend."""
    backend = get_backend()
    if backend == "bedrock":
        return os.environ.get(
            "PATTERN_VAULT_MODEL",
            "anthropic.claude-sonnet-4-5-20250929-v1:0",
        )
    # anthropic direct or bifrost (bifrost uses native Anthropic model IDs)
    return os.environ.get("PATTERN_VAULT_MODEL", "claude-sonnet-4-20250514")


# ── Sync clients ───────────────────────────────────────────────

def make_client():
    """Return a synchronous Anthropic-compatible client for the active backend."""
    backend = get_backend()

    if backend == "bedrock":
        try:
            from anthropic import AnthropicBedrock
        except ImportError:
            raise RuntimeError(
                "Bedrock support requires: pip install 'anthropic[bedrock]'"
            )
        return AnthropicBedrock(
            aws_access_key=os.environ.get("AWS_ACCESS_KEY_ID"),
            aws_secret_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
            aws_session_token=os.environ.get("AWS_SESSION_TOKEN"),
            aws_region=os.environ.get("AWS_REGION", "us-east-1"),
        )

    if backend == "bifrost":
        import anthropic
        bifrost_url = os.environ.get("BIFROST_URL")
        if not bifrost_url:
            raise RuntimeError("BIFROST_URL must be set (e.g. http://localhost:8080/anthropic)")
        return anthropic.Anthropic(
            api_key=os.environ.get("BIFROST_API_KEY", "dummy"),
            base_url=bifrost_url,
        )

    # Default: direct Anthropic
    import anthropic
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY not set.\n"
            "Alternatives:\n"
            "  Bedrock: PATTERN_VAULT_BACKEND=bedrock + AWS credentials\n"
            "  Bifrost: PATTERN_VAULT_BACKEND=bifrost + BIFROST_URL"
        )
    return anthropic.Anthropic(api_key=api_key)


# ── Async clients ──────────────────────────────────────────────

def make_async_client():
    """Return an async Anthropic-compatible client for the active backend."""
    backend = get_backend()

    if backend == "bedrock":
        try:
            from anthropic import AsyncAnthropicBedrock
        except ImportError:
            raise RuntimeError(
                "Bedrock support requires: pip install 'anthropic[bedrock]'"
            )
        return AsyncAnthropicBedrock(
            aws_access_key=os.environ.get("AWS_ACCESS_KEY_ID"),
            aws_secret_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
            aws_session_token=os.environ.get("AWS_SESSION_TOKEN"),
            aws_region=os.environ.get("AWS_REGION", "us-east-1"),
        )

    if backend == "bifrost":
        import anthropic
        bifrost_url = os.environ.get("BIFROST_URL")
        if not bifrost_url:
            raise RuntimeError("BIFROST_URL must be set")
        return anthropic.AsyncAnthropic(
            api_key=os.environ.get("BIFROST_API_KEY", "dummy"),
            base_url=bifrost_url,
        )

    # Default: direct Anthropic
    import anthropic
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY not set.\n"
            "Alternatives:\n"
            "  Bedrock: export PATTERN_VAULT_BACKEND=bedrock\n"
            "           export AWS_ACCESS_KEY_ID=...\n"
            "           export AWS_SECRET_ACCESS_KEY=...\n"
            "  Bifrost: export PATTERN_VAULT_BACKEND=bifrost\n"
            "           export BIFROST_URL=http://localhost:8080/anthropic"
        )
    return anthropic.AsyncAnthropic(api_key=api_key)


def describe_backend() -> str:
    """Return a human-readable description of the active backend."""
    backend = get_backend()
    model = get_model()
    if backend == "bedrock":
        region = os.environ.get("AWS_REGION", "us-east-1")
        return f"AWS Bedrock ({region}) — {model}"
    if backend == "bifrost":
        url = os.environ.get("BIFROST_URL", "not set")
        return f"Bifrost → {url} — {model}"
    return f"Anthropic direct — {model}"
