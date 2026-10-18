from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_ok_with_database() -> None:
    with patch("app.main.database_ok", return_value=True):
        r = client.get("/api/v1/healthz")
    assert r.status_code == 200
    assert r.json() == {"server_status": "OK", "database_status": "OK"}


def test_health_never_false_green_when_db_down() -> None:
    # T-017: DB mati -> status merah, bukan hijau palsu.
    with patch("app.main.database_ok", return_value=False):
        r = client.get("/api/v1/healthz")
    assert r.status_code == 503
    assert r.json()["database_status"] == "DOWN"


def test_request_id_generated_and_unsafe_one_replaced() -> None:
    r = client.get("/api/v1/healthz", headers={"X-Request-ID": "bad id\n<script>"})
    rid = r.headers["X-Request-ID"]
    assert rid != "bad id\n<script>" and len(rid) == 36

    r = client.get("/api/v1/healthz", headers={"X-Request-ID": "abc12345-proxy"})
    assert r.headers["X-Request-ID"] == "abc12345-proxy"
