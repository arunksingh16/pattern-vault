from fastapi.testclient import TestClient

from pattern_vault.api.main import create_app, host_allowed

# TestClient is used without `with` so the lifespan (which opens the vault DB) never runs.


def test_rejects_unexpected_host_on_every_api_route():
    # DNS rebinding: a malicious page resolving to 127.0.0.1 sends its own Host header.
    client = TestClient(create_app(), base_url="http://localhost")

    for path in ("/api/health", "/api/stats", "/api/settings"):
        response = client.get(path, headers={"Host": "evil.example"})
        assert response.status_code == 400, path


def test_accepts_loopback_hosts_with_ports():
    client = TestClient(create_app(), base_url="http://localhost")

    for host in ("localhost:8001", "127.0.0.1:5173", "[::1]:8001", "localhost"):
        assert client.get("/api/health", headers={"Host": host}).status_code == 200, host


def test_host_allowed_parses_ipv6_and_ports():
    allowed = {"localhost", "127.0.0.1", "::1"}

    assert host_allowed("[::1]:8001", allowed)
    assert host_allowed("127.0.0.1", allowed)
    assert not host_allowed("localhost.evil.example:8001", allowed)
    assert not host_allowed("", allowed)


def test_allow_any_host_when_bound_to_all_interfaces():
    client = TestClient(create_app(allow_any_host=True), base_url="http://localhost")

    assert client.get("/api/health", headers={"Host": "192.168.1.20:8001"}).status_code == 200


def test_extra_hosts_are_accepted():
    client = TestClient(create_app(extra_hosts=["devbox.local"]), base_url="http://localhost")

    assert client.get("/api/health", headers={"Host": "devbox.local:8001"}).status_code == 200


def test_serves_built_ui_next_to_api(tmp_path):
    # The packaged app serves the React build from the same port as the API.
    (tmp_path / "index.html").write_text('<html><div id="root"></div></html>', encoding="utf-8")
    client = TestClient(create_app(web_dist=tmp_path), base_url="http://localhost")

    page = client.get("/")
    health = client.get("/api/health")

    assert page.status_code == 200 and 'id="root"' in page.text
    assert health.headers["content-type"].startswith("application/json")
