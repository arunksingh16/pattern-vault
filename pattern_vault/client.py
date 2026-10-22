"""
Pattern Vault client factory.

Supports four backends, selected by environment variables:

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

  PATTERN_VAULT_BACKEND=ollama
    Optional: OLLAMA_BASE_URL (default: http://localhost:11434/v1)
    Optional: OLLAMA_API_KEY (default: "ollama")
    Model: PATTERN_VAULT_MODEL or qwen2.5-coder:7b

Usage:
    from pattern_vault.client import make_client, make_async_client, get_model

    client = make_client()          # sync
    client = make_async_client()    # async
    model  = get_model()            # correct model ID for the backend
"""

from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass
from math import ceil
from collections.abc import Iterable, Mapping
from typing import Any

from pattern_vault import settings


# ── Anthropic-compatible response blocks for Ollama ───────────

@dataclass
class _CompatTextBlock:
    type: str
    text: str


@dataclass
class _CompatToolUseBlock:
    type: str
    id: str
    name: str
    input: dict[str, Any]


@dataclass
class _CompatMessageResponse:
    content: list[Any]
    stop_reason: str
    usage: dict[str, Any] | None = None


def _extract_block_attr(block: Any, name: str, default: Any = None) -> Any:
    if isinstance(block, dict):
        return block.get(name, default)
    return getattr(block, name, default)


def _normalize_ollama_base_url(url: str) -> str:
    normalized = url.rstrip("/")
    if normalized.endswith("/v1"):
        return normalized
    return f"{normalized}/v1"


def _build_ollama_client_kwargs(overrides: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return {
        "base_url": _normalize_ollama_base_url(settings.get("ollama.base_url", overrides)),
        "api_key": settings.get("ollama.api_key", overrides),
    }


def get_provider_name() -> str:
    """Return the normalized provider label used for token usage tracking."""
    return get_backend()


def _safe_jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _safe_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe_jsonable(v) for v in value]
    if hasattr(value, "model_dump"):
        try:
            return _safe_jsonable(value.model_dump())
        except Exception:  # nosec B110 – intentional fallback, try next serialiser
            pass
    if hasattr(value, "to_dict"):
        try:
            return _safe_jsonable(value.to_dict())
        except Exception:  # nosec B110 – intentional fallback, try next serialiser
            pass
    if hasattr(value, "__dict__"):
        return _safe_jsonable(vars(value))
    return str(value)


def _estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, ceil(len(text) / 4))


def _serialize_message_payload(system: str | None, messages: list[dict[str, Any]]) -> str:
    return json.dumps({"system": system, "messages": _safe_jsonable(messages)}, sort_keys=True)


def _serialize_response_content(response: Any) -> str:
    parts: list[str] = []
    for block in getattr(response, "content", []) or []:
        block_type = _extract_block_attr(block, "type")
        if block_type == "text":
            text = _extract_block_attr(block, "text", "")
            if text:
                parts.append(text)
        elif block_type == "tool_use":
            parts.append(json.dumps(_extract_block_attr(block, "input", {}), sort_keys=True))
    return "\n".join(parts)


def extract_usage_snapshot(
    response: Any,
    *,
    system: str | None,
    messages: list[dict[str, Any]],
) -> dict[str, Any]:
    """Return normalized token usage for a model response, estimating if needed."""
    usage = _safe_jsonable(getattr(response, "usage", None)) or {}

    input_tokens = usage.get("input_tokens")
    if input_tokens is None:
        input_tokens = usage.get("prompt_tokens")
    cache_creation = usage.get("cache_creation_input_tokens", 0) or 0
    cache_read = usage.get("cache_read_input_tokens", 0) or 0
    if input_tokens is not None:
        input_tokens = int(input_tokens) + int(cache_creation) + int(cache_read)

    output_tokens = usage.get("output_tokens")
    if output_tokens is None:
        output_tokens = usage.get("completion_tokens")
    if output_tokens is not None:
        output_tokens = int(output_tokens)

    total_tokens = usage.get("total_tokens")
    if total_tokens is not None:
        total_tokens = int(total_tokens)

    estimated = False
    if input_tokens is None or output_tokens is None:
        estimated = True
        input_tokens = _estimate_tokens(_serialize_message_payload(system, messages))
        output_tokens = _estimate_tokens(_serialize_response_content(response))
        total_tokens = input_tokens + output_tokens
    elif total_tokens is None:
        total_tokens = input_tokens + output_tokens

    return {
        "input_tokens": int(input_tokens),
        "output_tokens": int(output_tokens),
        "total_tokens": int(total_tokens),
        "estimated": estimated,
        "usage": usage,
    }


def _anthropic_tools_to_openai(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
    if not tools:
        return None

    converted = []
    for tool in tools:
        converted.append(
            {
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "parameters": tool.get("input_schema", {"type": "object", "properties": {}}),
                },
            }
        )
    return converted


def _anthropic_messages_to_openai(
    *,
    system: str | None,
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    converted: list[dict[str, Any]] = []
    if system:
        converted.append({"role": "system", "content": system})

    for message in messages:
        role = message["role"]
        content = message["content"]

        if isinstance(content, str):
            converted.append({"role": role, "content": content})
            continue

        if role == "assistant" and isinstance(content, list):
            text_parts: list[str] = []
            tool_calls: list[dict[str, Any]] = []

            for block in content:
                block_type = _extract_block_attr(block, "type")
                if block_type == "text":
                    text = _extract_block_attr(block, "text", "")
                    if text:
                        text_parts.append(text)
                elif block_type == "tool_use":
                    tool_calls.append(
                        {
                            "id": _extract_block_attr(block, "id"),
                            "type": "function",
                            "function": {
                                "name": _extract_block_attr(block, "name", ""),
                                "arguments": json.dumps(_extract_block_attr(block, "input", {})),
                            },
                        }
                    )

            assistant_message: dict[str, Any] = {
                "role": "assistant",
                "content": "\n".join(text_parts),
            }
            if tool_calls:
                assistant_message["tool_calls"] = tool_calls
            converted.append(assistant_message)
            continue

        if role == "user" and isinstance(content, list):
            for item in content:
                item_type = item.get("type") if isinstance(item, dict) else None
                if item_type == "tool_result":
                    converted.append(
                        {
                            "role": "tool",
                            "tool_call_id": item["tool_use_id"],
                            "content": str(item.get("content", "")),
                        }
                    )
                else:
                    converted.append({"role": "user", "content": str(item)})
            continue

        converted.append({"role": role, "content": str(content)})

    return converted


def _openai_response_to_anthropic_compat(response: Any) -> _CompatMessageResponse:
    choice = response.choices[0]
    message = choice.message
    content: list[Any] = []

    text = getattr(message, "content", None)
    if text:
        content.append(_CompatTextBlock(type="text", text=text))

    for tool_call in getattr(message, "tool_calls", []) or []:
        raw_arguments = getattr(tool_call.function, "arguments", "{}") or "{}"
        try:
            parsed_arguments = json.loads(raw_arguments)
        except json.JSONDecodeError:
            parsed_arguments = {}

        content.append(
            _CompatToolUseBlock(
                type="tool_use",
                id=tool_call.id,
                name=tool_call.function.name,
                input=parsed_arguments,
            )
        )

    stop_reason = "end_turn"
    if choice.finish_reason == "tool_calls":
        stop_reason = "tool_use"

    usage = _safe_jsonable(getattr(response, "usage", None))
    return _CompatMessageResponse(content=content, stop_reason=stop_reason, usage=usage)


class _OllamaMessagesAPI:
    def __init__(self, client: Any):
        self._client = client

    def create(
        self,
        *,
        model: str,
        max_tokens: int,
        system: str | None,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> _CompatMessageResponse:
        response = self._client.chat.completions.create(
            model=model,
            messages=_anthropic_messages_to_openai(system=system, messages=messages),
            tools=_anthropic_tools_to_openai(tools),
            max_tokens=max_tokens,
        )
        return _openai_response_to_anthropic_compat(response)


class _AsyncOllamaMessagesAPI:
    def __init__(self, client: Any):
        self._client = client

    async def create(
        self,
        *,
        model: str,
        max_tokens: int,
        system: str | None,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> _CompatMessageResponse:
        response = await self._client.chat.completions.create(
            model=model,
            messages=_anthropic_messages_to_openai(system=system, messages=messages),
            tools=_anthropic_tools_to_openai(tools),
            max_tokens=max_tokens,
        )
        return _openai_response_to_anthropic_compat(response)


class _OllamaCompatClient:
    def __init__(self, client: Any):
        self.messages = _OllamaMessagesAPI(client)


class _AsyncOllamaCompatClient:
    def __init__(self, client: Any):
        self.messages = _AsyncOllamaMessagesAPI(client)


# ── Backend detection ──────────────────────────────────────────


def get_backend(overrides: Mapping[str, Any] | None = None) -> str:
    return str(settings.get("model.backend", overrides)).lower()


def get_model(overrides: Mapping[str, Any] | None = None) -> str:
    """Return the configured model ID, or the default for the active backend."""
    configured = settings.get("model.model", overrides)
    if configured:
        return configured
    backend = get_backend(overrides)
    if backend == "bedrock":
        return "anthropic.claude-sonnet-4-5-20250929-v1:0"
    if backend == "ollama":
        return "qwen2.5-coder:7b"
    return "claude-opus-5-5"


# ── Sync clients ───────────────────────────────────────────────


def make_client(overrides: Mapping[str, Any] | None = None):
    """Return a synchronous model client for the active backend.

    overrides lets Settings test unsaved form values; they win over env and config.
    """
    backend = get_backend(overrides)

    if backend == "bedrock":
        try:
            from anthropic import AnthropicBedrock
        except ImportError:
            raise RuntimeError(
                "Bedrock support requires: pip install 'anthropic[bedrock]'"
            )
        return AnthropicBedrock(
            aws_access_key=settings.get("bedrock.access_key_id", overrides),
            aws_secret_key=settings.get("bedrock.secret_access_key", overrides),
            aws_session_token=settings.get("bedrock.session_token", overrides),
            aws_region=settings.get("bedrock.region", overrides),
        )

    if backend == "bifrost":
        import anthropic

        bifrost_url = settings.get("bifrost.url", overrides)
        if not bifrost_url:
            raise RuntimeError("BIFROST_URL must be set (e.g. http://localhost:8080/anthropic)")
        return anthropic.Anthropic(
            api_key=settings.get("bifrost.api_key", overrides),
            base_url=bifrost_url,
        )

    if backend == "ollama":
        try:
            from openai import OpenAI
        except ImportError:
            raise RuntimeError("Ollama support requires: pip install openai")
        return _OllamaCompatClient(OpenAI(**_build_ollama_client_kwargs(overrides)))

    import anthropic

    api_key = settings.get("anthropic.api_key", overrides)
    if not api_key:
        raise RuntimeError(
            "No Anthropic API key. Paste one in Settings, run `pattern-vault setup`,\n"
            "or set ANTHROPIC_API_KEY.\n"
            "Alternatives:\n"
            "  Bedrock: PATTERN_VAULT_BACKEND=bedrock + AWS credentials\n"
            "  Bifrost: PATTERN_VAULT_BACKEND=bifrost + BIFROST_URL\n"
            "  Ollama: PATTERN_VAULT_BACKEND=ollama + local Ollama server"
        )
    return anthropic.Anthropic(api_key=api_key)


# ── Async clients ──────────────────────────────────────────────


def make_async_client(overrides: Mapping[str, Any] | None = None):
    """Return an async model client for the active backend."""
    backend = get_backend(overrides)

    if backend == "bedrock":
        try:
            from anthropic import AsyncAnthropicBedrock
        except ImportError:
            raise RuntimeError(
                "Bedrock support requires: pip install 'anthropic[bedrock]'"
            )
        return AsyncAnthropicBedrock(
            aws_access_key=settings.get("bedrock.access_key_id", overrides),
            aws_secret_key=settings.get("bedrock.secret_access_key", overrides),
            aws_session_token=settings.get("bedrock.session_token", overrides),
            aws_region=settings.get("bedrock.region", overrides),
        )

    if backend == "bifrost":
        import anthropic

        bifrost_url = settings.get("bifrost.url", overrides)
        if not bifrost_url:
            raise RuntimeError("BIFROST_URL must be set")
        return anthropic.AsyncAnthropic(
            api_key=settings.get("bifrost.api_key", overrides),
            base_url=bifrost_url,
        )

    if backend == "ollama":
        try:
            from openai import AsyncOpenAI
        except ImportError:
            raise RuntimeError("Ollama support requires: pip install openai")
        return _AsyncOllamaCompatClient(AsyncOpenAI(**_build_ollama_client_kwargs(overrides)))

    import anthropic

    api_key = settings.get("anthropic.api_key", overrides)
    if not api_key:
        raise RuntimeError(
            "No Anthropic API key. Paste one in Settings, run `pattern-vault setup`,\n"
            "or set ANTHROPIC_API_KEY.\n"
            "Alternatives:\n"
            "  Bedrock: export PATTERN_VAULT_BACKEND=bedrock\n"
            "           export AWS_ACCESS_KEY_ID=...\n"
            "           export AWS_SECRET_ACCESS_KEY=...\n"
            "  Bifrost: export PATTERN_VAULT_BACKEND=bifrost\n"
            "           export BIFROST_URL=http://localhost:8080/anthropic\n"
            "  Ollama: export PATTERN_VAULT_BACKEND=ollama\n"
            "          export OLLAMA_BASE_URL=http://localhost:11434/v1\n"
            "          export PATTERN_VAULT_MODEL=qwen2.5-coder:7b"
        )
    return anthropic.AsyncAnthropic(api_key=api_key)


def describe_backend(overrides: Mapping[str, Any] | None = None) -> str:
    """Return a human-readable description of the active backend."""
    backend = get_backend(overrides)
    model = get_model(overrides)
    if backend == "bedrock":
        region = settings.get("bedrock.region", overrides)
        return f"AWS Bedrock ({region}) — {model}"
    if backend == "bifrost":
        url = settings.get("bifrost.url", overrides) or "not set"
        return f"Bifrost → {url} — {model}"
    if backend == "ollama":
        url = _build_ollama_client_kwargs(overrides)["base_url"]
        return f"Ollama → {url} — {model}"
    return f"Anthropic direct — {model}"


# ── Settings page helpers ──────────────────────────────────────


def list_ollama_models(base_url: str, timeout: float = 1.0) -> list[str] | None:
    """Return the models pulled into Ollama, or None when Ollama isn't reachable."""
    native = base_url.strip().rstrip("/")
    if native.endswith("/v1"):
        native = native[: -len("/v1")]
    if not native.startswith(("http://", "https://")):
        return None
    try:
        with urllib.request.urlopen(f"{native}/api/tags", timeout=timeout) as response:  # nosec B310
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError):
        return None
    return [
        model["name"]
        for model in payload.get("models", [])
        if isinstance(model, dict) and model.get("name")
    ]


def redact(text: str, secrets: Iterable[str | None]) -> str:
    """Replace any secret appearing in text with its mask."""
    for secret in secrets:
        if secret and len(secret) >= 4:
            text = text.replace(secret, settings.mask(secret) or "")
    return text


def check_connection(overrides: Mapping[str, Any]) -> tuple[bool, str]:
    """Make the cheapest real call with these values (saved or not); never raises."""
    secrets = [settings.get(key, overrides) for key, spec in settings.SETTINGS.items() if spec.secret]
    try:
        client = make_client(overrides)
        client.messages.create(
            model=get_model(overrides),
            max_tokens=16,
            messages=[{"role": "user", "content": "ping"}],
        )
    except Exception as exc:  # every backend failure is reported to the page, not raised
        return False, redact(str(exc), secrets)
    return True, f"Connected to {describe_backend(overrides)}"
