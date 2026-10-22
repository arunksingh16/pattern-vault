import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from fastapi.testclient import TestClient

from pattern_vault import client as client_module
from pattern_vault import settings
from pattern_vault.api.main import create_app
from pattern_vault.client import list_ollama_models

SECRET = "sk-ant-api03-supersecretvalue-a1b2"
MODEL_ENV_VARS = ("PATTERN_VAULT_BACKEND", "PATTERN_VAULT_MODEL", "ANTHROPIC_API_KEY", "OLLAMA_BASE_URL")


@pytest.fixture
def api(monkeypatch):
    for name in MODEL_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    return TestClient(create_app(), base_url="http://localhost")


def test_get_settings_masks_secrets(api, write_config):
    # The browser must never receive a full key, even the user's own.
    write_config(f'[anthropic]\napi_key = "{SECRET}"\n')

    response = api.get("/api/settings")

    assert response.status_code == 200
    assert "supersecretvalue" not in response.text
    field = response.json()["fields"]["anthropic.api_key"]
    assert field == {"value": "sk-ant-…a1b2", "source": "config", "secret": True, "env_var": "ANTHROPIC_API_KEY"}


def test_put_saves_and_blank_secret_keeps_old(api):
    api.put("/api/settings", json={"values": {"anthropic.api_key": SECRET}})

    response = api.put("/api/settings", json={"values": {"anthropic.api_key": "", "model.backend": "anthropic"}})

    assert response.status_code == 200
    assert settings.get("anthropic.api_key") == SECRET
    assert response.json()["fields"]["model.backend"]["value"] == "anthropic"


def test_put_rejects_env_locked_field(api, monkeypatch):
    # An env var always wins, so saving over it would silently do nothing.
    monkeypatch.setenv("PATTERN_VAULT_BACKEND", "bedrock")

    response = api.put("/api/settings", json={"values": {"model.backend": "ollama"}})

    assert response.status_code == 409
    assert "PATTERN_VAULT_BACKEND" in response.json()["detail"]
    assert not settings.config_path().exists()


def test_put_rejects_unknown_key_and_bad_backend(api):
    assert api.put("/api/settings", json={"values": {"model.nope": "x"}}).status_code == 422
    assert api.put("/api/settings", json={"values": {"model.backend": "gpt"}}).status_code == 422


def test_put_rejects_missing_code_folder(api, tmp_path):
    response = api.put("/api/settings", json={"values": {"workspace.roots": [str(tmp_path / "missing")]}})

    assert response.status_code == 422
    assert "missing" in response.json()["detail"]


def test_put_refuses_when_config_malformed(api, write_config):
    write_config("[model\nbackend = ")

    assert api.get("/api/settings").json()["config_error"]
    assert api.put("/api/settings", json={"values": {"model.backend": "ollama"}}).status_code == 409
    assert settings.config_path().read_text() == "[model\nbackend = "


def test_health_reflects_saved_backend(api):
    # The header label must follow a Settings save without a restart.
    api.put("/api/settings", json={"values": {"model.backend": "ollama", "model.model": "qwen2.5-coder:7b"}})

    assert api.get("/api/health").json()["backend"].startswith("Ollama")


def test_connection_test_redacts_secret(api, monkeypatch):
    def failing_client(overrides=None, **_kwargs):
        raise RuntimeError(f"bad key {SECRET}")

    monkeypatch.setattr(client_module, "make_client", failing_client)

    response = api.post(
        "/api/settings/test", json={"values": {"model.backend": "anthropic", "anthropic.api_key": SECRET}}
    )

    assert response.status_code == 200
    assert response.json()["ok"] is False
    assert "supersecretvalue" not in response.text


def test_connection_test_uses_unsaved_form_values(api, monkeypatch):
    seen = {}

    class FakeClient:
        class messages:
            @staticmethod
            def create(**kwargs):
                seen.update(kwargs)

    monkeypatch.setattr(client_module, "make_client", lambda overrides=None, **_kw: seen.update(o=overrides) or FakeClient)

    response = api.post("/api/settings/test", json={"values": {"model.backend": "ollama", "model.model": "llama3.1:8b"}})

    assert response.json()["ok"] is True
    assert seen["model"] == "llama3.1:8b"
    assert not settings.config_path().exists()


def test_ollama_detection_times_out_fast():
    # An Ollama port that accepts but never answers must not hang setup or Settings.
    with socket.socket() as silent:
        silent.bind(("127.0.0.1", 0))
        silent.listen()
        port = silent.getsockname()[1]

        started = time.monotonic()
        models = list_ollama_models(f"http://127.0.0.1:{port}/v1", timeout=1.0)

    assert models is None
    assert time.monotonic() - started < 2.0


def test_ollama_detection_lists_models():
    class Tags(BaseHTTPRequestHandler):
        def do_GET(self):
            body = json.dumps({"models": [{"name": "qwen2.5-coder:7b"}]}).encode() if self.path == "/api/tags" else b""
            self.send_response(200 if body else 404)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Tags)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        assert list_ollama_models(f"http://127.0.0.1:{server.server_port}/v1") == ["qwen2.5-coder:7b"]
    finally:
        server.shutdown()


def test_ollama_models_route_lists_only_chat_models(api, monkeypatch):
    # The Settings dropdown picks the chat model; embedding models would break indexing.
    monkeypatch.setattr(client_module, "list_ollama_models", lambda *_a, **_k: ["nomic-embed-text", "qwen3:4b", "qwen3:4b"])
    assert api.get("/api/settings/ollama-models").json() == {"models": ["qwen3:4b"]}

    monkeypatch.setattr(client_module, "list_ollama_models", lambda *_a, **_k: None)
    assert api.get("/api/settings/ollama-models").json() == {"models": None}


def test_connection_test_works_through_real_ollama_client(monkeypatch):
    # Ollama is the installer's default backend; its compat client must accept the test call.
    import openai

    created = {}

    class FakeOpenAI:
        def __init__(self, **kwargs):
            created.update(kwargs)
            self.chat = type("Chat", (), {"completions": self})()

        def create(self, **kwargs):
            created["request"] = kwargs
            message = type("Msg", (), {"content": "pong", "tool_calls": []})()
            return type("Resp", (), {"choices": [type("Choice", (), {"finish_reason": "stop", "message": message})()]})()

    monkeypatch.setattr(openai, "OpenAI", FakeOpenAI)

    ok, message = client_module.check_connection({"model.backend": "ollama", "model.model": "qwen3:4b"})

    assert ok is True, message
    assert created["request"]["model"] == "qwen3:4b"
    # A connection test must fail fast, not retry for minutes.
    assert created["max_retries"] == 0 and created["timeout"] <= client_module.CONNECTION_TEST_TIMEOUT


def test_connection_test_gives_up_quickly_on_a_silent_server(monkeypatch):
    # A server that accepts but never answers must not leave the page on "Testing…".
    monkeypatch.setattr(client_module, "CONNECTION_TEST_TIMEOUT", 1.0)
    with socket.socket() as silent:
        silent.bind(("127.0.0.1", 0))
        silent.listen()
        port = silent.getsockname()[1]

        started = time.monotonic()
        ok, _message = client_module.check_connection(
            {"model.backend": "ollama", "ollama.base_url": f"http://127.0.0.1:{port}/v1", "model.model": "x"}
        )

    assert ok is False
    assert time.monotonic() - started < 3.0


def test_settings_page_loads_with_a_wrongly_typed_value(api, write_config):
    write_config('[server]\nport = "abc"\n')

    response = api.get("/api/settings")

    assert response.status_code == 200
    assert response.json()["fields"]["server.port"]["value"] == 8001
    assert "server.port" in response.json()["config_error"]
