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


def test_inflight_limit_leaves_headroom_against_pool_thread_deadlock() -> None:
    # M9-03: request yang diproses bersamaan harus < pool koneksi & < thread AnyIO, dengan sisa
    # untuk WebSocket monitor, sweeper, dan backup. Kalau tidak, lonjakan login membuat API macet.
    import anyio
    import anyio.to_thread

    from app.db import engine
    from app.main import MAX_INFLIGHT

    pool_max = engine.pool.size() + engine.pool._max_overflow  # type: ignore[attr-defined]

    async def tokens() -> float:
        return anyio.to_thread.current_default_thread_limiter().total_tokens

    threads = anyio.run(tokens)
    assert MAX_INFLIGHT + 8 <= pool_max
    assert MAX_INFLIGHT + 8 <= threads
