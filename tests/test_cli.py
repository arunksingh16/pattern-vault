import asyncio
import socket

import pytest
import uvicorn
from fastapi import HTTPException
from fastapi.testclient import TestClient

from pattern_vault import cli
from pattern_vault.api.routes import mcp_monitor


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_version_flag_prints_package_version(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--version"])

    assert exc.value.code == 0
    assert "0.2.1" in capsys.readouterr().out


def test_mcp_subcommand_runs_mcp_server(monkeypatch):
    # `serve` now means "start the UI"; the MCP server moved to `mcp`.
    calls = []
    monkeypatch.setattr(cli, "cmd_mcp", calls.append)

    cli.main(["mcp", "--transport", "http"])

    assert calls and calls[0].transport == "http"


def test_serve_exits_cleanly_when_port_busy(capsys):
    # The default port clashes with a running dev backend; the user needs a hint, not a traceback.
    with socket.socket() as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        port = busy.getsockname()[1]

        with pytest.raises(SystemExit) as exc:
            cli.main(["serve", "--port", str(port)])

    err = capsys.readouterr().err
    assert exc.value.code == 1
    assert "already in use" in err and "--port" in err


def test_port_is_free_again_right_after_a_server_stops():
    # Restarting serve leaves the old connections in TIME_WAIT; uvicorn can bind
    # (SO_REUSEADDR), so the pre-check must not report the port as busy.
    listener = socket.socket()
    # Like uvicorn; on Linux, TIME_WAIT leftovers only allow a rebind if the old server set this too
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    port = listener.getsockname()[1]
    client = socket.create_connection(("127.0.0.1", port))
    accepted, _ = listener.accept()
    accepted.close()  # server closes first, so its side of the connection enters TIME_WAIT
    client.close()
    listener.close()

    assert cli.port_available("127.0.0.1", port)


def test_serve_warns_on_all_interfaces(monkeypatch, capsys):
    started = {}
    monkeypatch.setattr(uvicorn, "run", lambda app, **kwargs: started.update(app=app, **kwargs))

    cli.main(["serve", "--host", "0.0.0.0", "--port", str(_free_port())])

    assert "reachable from the network" in capsys.readouterr().out
    client = TestClient(started["app"], base_url="http://localhost")
    assert client.get("/api/health", headers={"Host": "10.0.0.5:8001"}).status_code == 200


def test_serve_prints_url_and_binds_loopback_by_default(monkeypatch, capsys):
    started = {}
    monkeypatch.setattr(uvicorn, "run", lambda app, **kwargs: started.update(app=app, **kwargs))
    port = _free_port()

    cli.main(["serve", "--port", str(port)])

    assert started["host"] == "127.0.0.1" and started["port"] == port
    assert f"http://localhost:{port}" in capsys.readouterr().out


def test_mcp_monitor_spawns_mcp_subcommand(monkeypatch):
    spawned = []

    async def fake_exec(*command, **_kwargs):
        spawned.append(command)
        raise OSError("not really starting")

    monkeypatch.setattr(mcp_monitor.asyncio, "create_subprocess_exec", fake_exec)

    with pytest.raises(HTTPException):
        asyncio.run(mcp_monitor.MCPServerMonitor().start())

    assert "mcp" in spawned[0] and "serve" not in spawned[0]
