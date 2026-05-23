"""
Pattern Vault — Claude-powered pattern extractor.

Takes code chunks and uses Claude to classify, summarise, and decide
whether each chunk contains a reusable pattern worth indexing.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from pattern_vault.store.db import get_connection, init_db, record_token_usage

EXTRACTION_SYSTEM_PROMPT = """\
You are a senior software engineer reviewing code to identify reusable patterns.

For each code chunk provided, determine:
1. Whether it contains a REUSABLE PATTERN worth saving (not all code is a pattern)
2. If yes, classify and describe it

A reusable pattern is code that:
- Solves a common problem in a generalizable way
- Could be adapted to other projects or contexts
- Demonstrates a well-known or novel design/engineering approach
- Has clear structure and intent

Categories (pick the best fit):
- design_pattern: Factory, Builder, Observer, Strategy, Singleton, Adapter, etc.
- resilience: Retry, circuit breaker, timeout, fallback, rate limiting, bulkhead
- api_pattern: Middleware, auth, pagination, validation, error handling, CORS
- data_access: Repository, query builder, caching, connection pooling, ORM patterns
- async_pattern: Queue consumer, pub/sub, event emitter, worker pool, debounce
- config: Feature flags, env config, dependency injection, service locator
- testing: Test fixtures, mocks, parameterized tests, test utilities
- utility: Generic helpers that solve common problems cleanly
- security: Input sanitization, CSRF, rate limiting, encryption helpers
- general: Anything else that is clearly a reusable pattern

Respond with ONLY valid JSON (no markdown, no explanation). Return a JSON array of pattern objects.
If NONE of the chunks contain a reusable pattern, return an empty array [].

Each pattern object must have:
{
  "chunk_index": 0,
  "is_pattern": true,
  "name": "short descriptive name",
  "category": "one of the categories above",
  "tags": ["tag1", "tag2", "tag3"],
  "summary": "one paragraph explaining what this pattern does and when to use it",
  "quality_signal": "brief note on quality — e.g. 'clean implementation' or 'handles edge cases well'",
  "quality_score": 0.0
}

For non-patterns, include: {"chunk_index": N, "is_pattern": false}
"""


@dataclass
class ExtractionResult:
    """Result of pattern extraction for a single chunk."""
    chunk_index: int
    is_pattern: bool
    name: str = ""
    category: str = "general"
    tags: list[str] = None
    summary: str = ""
    quality_signal: str = ""
    quality_score: float | None = None

    def __post_init__(self):
        if self.tags is None:
            self.tags = []


class ExtractionResponseError(RuntimeError):
    """Raised when a model response cannot be parsed as extraction output."""


def _get_block_value(block: Any, key: str, default: Any = None) -> Any:
    if isinstance(block, dict):
        return block.get(key, default)
    return getattr(block, key, default)


def _strip_json_fence(text: str) -> str:
    text = text.strip()
    if not text.startswith("```"):
        return text

    text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


def _extract_response_text(response: Any, *, provider: str, model: str) -> str:
    content = getattr(response, "content", None)
    if not content:
        raise ExtractionResponseError(
            f"Malformed extraction response from {provider}/{model}: no content blocks returned"
        )

    for block in content:
        block_type = _get_block_value(block, "type")
        text = _get_block_value(block, "text")
        if (block_type in {None, "text"}) and isinstance(text, str) and text.strip():
            return _strip_json_fence(text)

    block_types = [
        str(_get_block_value(block, "type", "unknown"))
        for block in content
    ]
    raise ExtractionResponseError(
        f"Malformed extraction response from {provider}/{model}: no non-empty text block "
        f"returned (content block types: {', '.join(block_types)})"
    )


def _parse_extraction_results(text: str, *, provider: str, model: str) -> list[ExtractionResult]:
    if not text.strip():
        raise ExtractionResponseError(
            f"Malformed extraction response from {provider}/{model}: empty text content"
        )

    try:
        results_raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ExtractionResponseError(
            f"Malformed extraction response from {provider}/{model}: invalid JSON "
            f"at line {exc.lineno} column {exc.colno}"
        ) from exc

    if not isinstance(results_raw, list):
        raise ExtractionResponseError(
            f"Malformed extraction response from {provider}/{model}: expected a JSON array"
        )

    results = []
    for item in results_raw:
        if not isinstance(item, dict):
            raise ExtractionResponseError(
                f"Malformed extraction response from {provider}/{model}: array item is not an object"
            )
        chunk_index = item.get("chunk_index", 0)
        if not isinstance(chunk_index, int):
            raise ExtractionResponseError(
                f"Malformed extraction response from {provider}/{model}: chunk_index is not an integer"
            )
        tags = item.get("tags", [])
        if not isinstance(tags, list):
            raise ExtractionResponseError(
                f"Malformed extraction response from {provider}/{model}: tags is not an array"
            )
        results.append(ExtractionResult(
            chunk_index=chunk_index,
            is_pattern=item.get("is_pattern", False),
            name=item.get("name", ""),
            category=item.get("category", "general"),
            tags=tags,
            summary=item.get("summary", ""),
            quality_signal=item.get("quality_signal", ""),
            quality_score=_coerce_quality_score(item.get("quality_score")),
        ))
    return results


def _coerce_quality_score(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return max(0.0, min(1.0, float(value)))
    return None


def _build_extraction_message(chunks: list[dict], *, profile_guidance: str | None = None) -> str:
    """Build the user message with code chunks for extraction."""
    parts = []
    if profile_guidance:
        parts.append("Indexing profile guidance:")
        parts.append(profile_guidance)
        parts.append(
            "For each saved pattern, include quality_score as a number from 0.0 to 1.0. "
            "Use 0.8+ only for patterns that are clearly reusable outside this repository."
        )
        parts.append("")
    for i, chunk in enumerate(chunks):
        parts.append(f"--- CHUNK {i} ---")
        parts.append(f"File: {chunk.get('file_path', 'unknown')}")
        parts.append(f"Language: {chunk.get('language', 'unknown')}")
        parts.append(f"Symbol: {chunk.get('symbol_name', 'unknown')} ({chunk.get('symbol_type', 'unknown')})")
        parts.append(f"Lines: {chunk.get('line_start', '?')}-{chunk.get('line_end', '?')}")
        parts.append("")
        parts.append(chunk["code"])
        parts.append("")
    return "\n".join(parts)


def _record_extraction_usage(
    *,
    db_path: Optional[Path],
    model: str,
    response,
    user_message: str,
) -> None:
    from pattern_vault.client import extract_usage_snapshot, get_provider_name

    usage = extract_usage_snapshot(
        response,
        system=EXTRACTION_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )
    conn = get_connection(db_path)
    try:
        init_db(conn)
        record_token_usage(
            conn,
            provider=get_provider_name(),
            model=model,
            flow="indexing",
            operation="extract_patterns",
            input_tokens=usage["input_tokens"],
            output_tokens=usage["output_tokens"],
            total_tokens=usage["total_tokens"],
            estimated=usage["estimated"],
            usage=usage["usage"],
        )
    finally:
        conn.close()


def extract_patterns_sync(
    chunks: list[dict],
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    db_path: Optional[Path] = None,
    profile_guidance: str | None = None,
) -> list[ExtractionResult]:
    """
    Extract patterns from a batch of code chunks using Claude.
    """
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    from pattern_vault.client import get_provider_name, make_client, get_model as _get_model

    try:
        client = make_client()
    except RuntimeError as e:
        raise RuntimeError(str(e))

    model = model or _get_model()
    provider = get_provider_name()
    user_message = _build_extraction_message(chunks, profile_guidance=profile_guidance)

    response = client.messages.create(
        model=model,
        max_tokens=2000,
        system=EXTRACTION_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    _record_extraction_usage(
        db_path=db_path,
        model=model,
        response=response,
        user_message=user_message,
    )

    text = _extract_response_text(response, provider=provider, model=model)
    return _parse_extraction_results(text, provider=provider, model=model)


async def extract_patterns_async(
    chunks: list[dict],
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    db_path: Optional[Path] = None,
    profile_guidance: str | None = None,
) -> list[ExtractionResult]:
    """Async version of extract_patterns_sync."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    from pattern_vault.client import get_provider_name, make_async_client, get_model as _get_model

    try:
        client = make_async_client()
    except RuntimeError as e:
        raise RuntimeError(str(e))

    model = model or _get_model()
    provider = get_provider_name()
    user_message = _build_extraction_message(chunks, profile_guidance=profile_guidance)

    response = await client.messages.create(
        model=model,
        max_tokens=2000,
        system=EXTRACTION_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    _record_extraction_usage(
        db_path=db_path,
        model=model,
        response=response,
        user_message=user_message,
    )

    text = _extract_response_text(response, provider=provider, model=model)
    return _parse_extraction_results(text, provider=provider, model=model)
