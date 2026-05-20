from types import SimpleNamespace

from src.client import (
    _anthropic_messages_to_openai,
    _normalize_ollama_base_url,
    get_model,
    describe_backend,
    make_async_client,
    make_client,
)


class _FakeCompletions:
    def __init__(self):
        self.last_kwargs = None

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason="tool_calls",
                    message=SimpleNamespace(
                        content="Inspecting the repo.",
                        tool_calls=[
                            SimpleNamespace(
                                id="tool_1",
                                function=SimpleNamespace(
                                    name="scan_directory",
                                    arguments='{"path": "/tmp/repo"}',
                                ),
                            )
                        ],
                    ),
                )
            ]
        )


class _FakeAsyncCompletions:
    def __init__(self):
        self.last_kwargs = None

    async def create(self, **kwargs):
        self.last_kwargs = kwargs
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason="stop",
                    message=SimpleNamespace(content="Done.", tool_calls=[]),
                )
            ]
        )


class _FakeOpenAI:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.chat = SimpleNamespace(completions=_FakeCompletions())


class _FakeAsyncOpenAI:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.chat = SimpleNamespace(completions=_FakeAsyncCompletions())


def test_normalize_ollama_base_url_appends_v1_once():
    assert _normalize_ollama_base_url("http://localhost:11434") == "http://localhost:11434/v1"
    assert _normalize_ollama_base_url("http://localhost:11434/v1") == "http://localhost:11434/v1"


def test_get_model_and_describe_backend_for_ollama(monkeypatch):
    monkeypatch.setenv("PATTERN_VAULT_BACKEND", "ollama")
    monkeypatch.setenv("PATTERN_VAULT_MODEL", "qwen2.5-coder:14b")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434")

    assert get_model() == "qwen2.5-coder:14b"
    assert describe_backend() == "Ollama → http://localhost:11434/v1 — qwen2.5-coder:14b"


def test_make_client_uses_openai_compatible_ollama_adapter(monkeypatch):
    monkeypatch.setenv("PATTERN_VAULT_BACKEND", "ollama")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434")
    monkeypatch.setitem(__import__("sys").modules, "openai", SimpleNamespace(OpenAI=_FakeOpenAI, AsyncOpenAI=_FakeAsyncOpenAI))

    client = make_client()
    response = client.messages.create(
        model="qwen2.5-coder:7b",
        max_tokens=512,
        system="system prompt",
        tools=[
            {
                "name": "scan_directory",
                "description": "Scan the directory",
                "input_schema": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            }
        ],
        messages=[{"role": "user", "content": "Scan this repo"}],
    )

    assert client.messages._client.kwargs == {
        "base_url": "http://localhost:11434/v1",
        "api_key": "ollama",  # pragma: allowlist secret
    }
    assert client.messages._client.chat.completions.last_kwargs["messages"] == [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": "Scan this repo"},
    ]
    assert client.messages._client.chat.completions.last_kwargs["tools"][0]["function"]["name"] == "scan_directory"
    assert [block.type for block in response.content] == ["text", "tool_use"]
    assert response.content[1].name == "scan_directory"
    assert response.content[1].input == {"path": "/tmp/repo"}
    assert response.stop_reason == "tool_use"


def test_make_async_client_uses_openai_compatible_ollama_adapter(monkeypatch):
    monkeypatch.setenv("PATTERN_VAULT_BACKEND", "ollama")
    monkeypatch.setitem(__import__("sys").modules, "openai", SimpleNamespace(OpenAI=_FakeOpenAI, AsyncOpenAI=_FakeAsyncOpenAI))

    client = make_async_client()

    assert client.messages._client.kwargs["base_url"] == "http://localhost:11434/v1"
    assert client.messages._client.kwargs["api_key"] == "ollama"  # pragma: allowlist secret


def test_anthropic_messages_to_openai_maps_tool_results():
    openai_messages = _anthropic_messages_to_openai(
        system="system prompt",
        messages=[
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "Need to inspect files."},
                    {"type": "tool_use", "id": "tool_1", "name": "read_file", "input": {"path": "README.md"}},
                ],
            },
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": "tool_1", "content": "file contents"},
                ],
            },
        ],
    )

    assert openai_messages == [
        {"role": "system", "content": "system prompt"},
        {
            "role": "assistant",
            "content": "Need to inspect files.",
            "tool_calls": [
                {
                    "id": "tool_1",
                    "type": "function",
                    "function": {
                        "name": "read_file",
                        "arguments": '{"path": "README.md"}',
                    },
                }
            ],
        },
        {"role": "tool", "tool_call_id": "tool_1", "content": "file contents"},
    ]
