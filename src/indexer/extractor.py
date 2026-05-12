"""
Pattern Vault — Claude-powered pattern extractor.

Takes code chunks and uses Claude to classify, summarise, and decide
whether each chunk contains a reusable pattern worth indexing.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

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
  "quality_signal": "brief note on quality — e.g. 'clean implementation' or 'handles edge cases well'"
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

    def __post_init__(self):
        if self.tags is None:
            self.tags = []


def _build_extraction_message(chunks: list[dict]) -> str:
    """Build the user message with code chunks for extraction."""
    parts = []
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


def extract_patterns_sync(
    chunks: list[dict],
    api_key: Optional[str] = None,
    model: Optional[str] = None,
) -> list[ExtractionResult]:
    """
    Extract patterns from a batch of code chunks using Claude.
    """
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    from src.client import make_client, get_model as _get_model

    try:
        client = make_client()
    except RuntimeError as e:
        raise RuntimeError(str(e))

    model = model or _get_model()
    user_message = _build_extraction_message(chunks)

    response = client.messages.create(
        model=model,
        max_tokens=2000,
        system=EXTRACTION_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    # Parse the JSON response
    text = response.content[0].text.strip()
    # Strip markdown fences if present
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

    try:
        results_raw = json.loads(text)
    except json.JSONDecodeError:
        # If Claude didn't return valid JSON, return empty
        return []

    results = []
    for item in results_raw:
        results.append(ExtractionResult(
            chunk_index=item.get("chunk_index", 0),
            is_pattern=item.get("is_pattern", False),
            name=item.get("name", ""),
            category=item.get("category", "general"),
            tags=item.get("tags", []),
            summary=item.get("summary", ""),
            quality_signal=item.get("quality_signal", ""),
        ))
    return results


async def extract_patterns_async(
    chunks: list[dict],
    api_key: Optional[str] = None,
    model: Optional[str] = None,
) -> list[ExtractionResult]:
    """Async version of extract_patterns_sync."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    from src.client import make_async_client, get_model as _get_model

    try:
        client = make_async_client()
    except RuntimeError as e:
        raise RuntimeError(str(e))

    model = model or _get_model()
    user_message = _build_extraction_message(chunks)

    response = await client.messages.create(
        model=model,
        max_tokens=2000,
        system=EXTRACTION_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    text = response.content[0].text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

    try:
        results_raw = json.loads(text)
    except json.JSONDecodeError:
        return []

    results = []
    for item in results_raw:
        results.append(ExtractionResult(
            chunk_index=item.get("chunk_index", 0),
            is_pattern=item.get("is_pattern", False),
            name=item.get("name", ""),
            category=item.get("category", "general"),
            tags=item.get("tags", []),
            summary=item.get("summary", ""),
            quality_signal=item.get("quality_signal", ""),
        ))
    return results
