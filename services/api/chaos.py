"""Uji gangguan M9-04 terhadap server & database sungguhan. Hanya untuk database uji.

Harness ini menjalankan uvicorn sendiri (agar bisa dimatikan paksa), lalu:
  refresh      siswa memuat ulang halaman / masuk ulang alur mulai: attempt, jawaban, timer utuh
  wifi_drop    siswa putus 25 dtk: dijeda otomatis, kredit jeda = lama jeda nyata, deadline digeser
  server_kill  kill -9 saat siswa menyimpan, mati 20 dtk: semua jawaban ber-ACK selamat, retry
               dengan Idempotency-Key sama tidak menggandakan, waktu outage dikompensasi (DEC-03)
               tanpa memakan jatah jeda siswa
  db_restart   PostgreSQL di-restart saat ujian: health melapor DOWN (T-017), API pulih sendiri,
               jawaban ber-ACK selamat
  submit       semua siswa mengumpulkan; satu receipt per siswa

  createdb localcbt_chaos && LOCALCBT_DATABASE_URL=.../localcbt_chaos uv run alembic upgrade head
  LOCALCBT_DATABASE_URL=.../localcbt_chaos uv run python chaos.py --confirm-db localcbt_chaos \\
      --db-restart-cmd "docker compose -f ../../compose.dev.yml restart db"
Keluar kode 1 bila ada skenario gagal. Disk penuh & listrik padam: lihat tes backup dan
ADMIN_GUIDE §8 (tidak aman disimulasikan di mesin bersama).
"""

import argparse
import json
import os
import random
import shlex
import signal
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

import loadtest

PORT = 8101
BASE = f"http://127.0.0.1:{PORT}"
loadtest.CREDENTIALS = Path(".chaos.json")


class Server:
    def __init__(self) -> None:
        self.proc: subprocess.Popen[bytes] | None = None
        self.env = {
            **os.environ,
            "LOCALCBT_COOKIE_SECURE": "false",
            "LOCALCBT_ALLOWED_ORIGINS": f'["{BASE}"]',
            "LOCALCBT_BACKUP_SCHEDULER_ENABLED": "false",
            "LOCALCBT_SWEEPER_ENABLED": "true",
            "LOCALCBT_LOG_LEVEL": "WARNING",
        }

    def start(self) -> None:
        cmd = [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(PORT),
               "--timeout-keep-alive", "75", "--no-access-log"]  # fmt: skip
        self.proc = subprocess.Popen(cmd, env=self.env)  # noqa: S603
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                if httpx.get(f"{BASE}/api/v1/healthz", timeout=1).status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.3)
        raise RuntimeError("server tidak sehat dalam 30 dtk")

    def kill(self) -> None:
        assert self.proc
        self.proc.send_signal(signal.SIGKILL)  # mati mendadak: tanpa shutdown rapi
        self.proc.wait()

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            self.proc.wait(timeout=10)


class Student:
    """Klien seperti browser: simpan jawaban diulang dengan Idempotency-Key yang sama sampai ACK."""

    def __init__(self, username: str, password: str) -> None:
        self.username = username
        self.c = httpx.Client(base_url=BASE, headers={"Origin": BASE}, timeout=5)
        r = self.c.post("/api/v1/auth/login", json={"username": username, "password": password})
        r.raise_for_status()
        self.c.headers["X-CSRF-Token"] = r.json()["csrf_token"]
        self.acked: dict[str, Any] = {}
        self.revision = 0
        self.rng = random.Random(username)
        self.attempt: dict[str, Any] = {}
        self.retries = 0

    def start(self) -> dict[str, Any]:
        exam = self.c.get("/api/v1/student/exams").json()[0]["id"]
        r = self.c.post(
            f"/api/v1/student/exams/{exam}/token/verify", json={"token": loadtest.TOKEN}
        )
        assert r.status_code == 200, f"{self.username} token: {r.status_code} {r.text}"
        grant = r.json()["start_grant"]
        r = self.c.post(
            f"/api/v1/student/exams/{exam}/attempts",
            json={"start_grant": grant, "confirm_start": True},
            headers={"Idempotency-Key": str(uuid.uuid4())},
        )
        assert r.status_code in (200, 201), r.text
        self.exam_id = exam
        self.attempt = r.json()
        return self.attempt

    @property
    def aid(self) -> str:
        return str(self.attempt["id"])

    def save(self, q: dict[str, Any], give_up_after: float = 60) -> bool:
        self.revision += 1
        answer = loadtest._answer(q, self.rng)
        body = {"answer": answer, "client_revision": self.revision, "marked_for_review": False}
        key = str(uuid.uuid4())
        end = time.monotonic() + give_up_after
        while time.monotonic() < end:
            try:
                r = self.c.put(
                    f"/api/v1/student/attempts/{self.aid}/answers/{q['id']}",
                    json=body,
                    headers={"Idempotency-Key": key},
                )
            except httpx.HTTPError:
                self.retries += 1
                time.sleep(0.5)
                continue
            if r.status_code == 200:
                self.acked[q["id"]] = answer
                return True
            if r.status_code < 500:
                raise AssertionError(f"{self.username} simpan ditolak {r.status_code}: {r.text}")
            self.retries += 1
            time.sleep(0.5)
        return False

    def heartbeat(self) -> dict[str, Any]:
        r = self.c.post(
            f"/api/v1/student/attempts/{self.aid}/heartbeat", json={"tab_visible": True}
        )
        r.raise_for_status()
        return dict(r.json())

    def server_answers(self) -> dict[str, Any]:
        r = self.c.get(f"/api/v1/student/attempts/{self.aid}")
        r.raise_for_status()
        return {a["question_id"]: a["answer"] for a in r.json()["answers"]}

    def check_acked(self) -> list[str]:
        server = self.server_answers()
        return [q for q, a in self.acked.items() if server.get(q) != a]


def proctor_status(proctor: httpx.Client, exam: str, username: str) -> str:
    rows = proctor.get(f"/api/v1/proctor/exams/{exam}/monitor").json()["participants"]
    return str(next(r["status"] for r in rows if r["nis"] == username))


# ---- Skenario -----------------------------------------------------------------------


def s_refresh(students: list[Student], **_: Any) -> str:
    s = students[0]
    for q in s.attempt["questions"][:3]:
        assert s.save(q)
    before = s.heartbeat()["remaining_seconds"]
    time.sleep(2)
    again = s.start()  # masuk ulang alur mulai = attempt yang sama, bukan baru (BR-13)
    assert again["id"] == s.aid, "attempt baru dibuat saat masuk ulang"
    reload = httpx.Client(base_url=BASE, headers=dict(s.c.headers), cookies=s.c.cookies)
    page = reload.get(f"/api/v1/student/attempts/{s.aid}").json()  # muat ulang halaman
    assert not s.check_acked(), "jawaban hilang setelah refresh"
    after = page["timer"]["remaining_seconds"]
    assert after <= before - 1, f"timer tidak berjalan / ter-reset: {before} -> {after}"
    return f"attempt sama, timer {before} -> {after} dtk"


def s_wifi_drop(students: list[Student], proctor: httpx.Client, **_: Any) -> str:
    s = students[1]
    assert s.save(s.attempt["questions"][0])
    t0 = s.heartbeat()
    time.sleep(25)  # tidak ada permintaan apa pun: seperti Wi-Fi putus
    seen = proctor_status(proctor, s.exam_id, s.username)
    assert seen == "PAUSED", f"monitor pengawas menampilkan {seen}, harusnya PAUSED"
    t1 = s.heartbeat()  # tersambung kembali
    assert t1["state"] == "IN_PROGRESS"
    credit = t1["pause_consumed_seconds"] - t0["pause_consumed_seconds"]
    # Jeda mulai 15 dtk setelah heartbeat terakhir: putus 25 dtk = kredit ±10 dtk.
    assert 5 <= credit <= 15, f"kredit jeda {credit} dtk"
    shift = epoch(t1["deadline_at"]) - epoch(t0["deadline_at"])
    assert abs(shift - credit) <= 1, f"deadline bergeser {shift} dtk, kredit {credit}"
    assert not s.check_acked()
    return f"monitor PAUSED, kredit jeda {credit} dtk = geser deadline {shift:.0f} dtk"


def epoch(iso: str) -> float:
    return datetime.fromisoformat(iso).timestamp()


def _saving(students: list[Student], stop: threading.Event, failures: list[str]) -> None:
    def loop(s: Student) -> None:
        qs = s.attempt["questions"]
        i = 0
        while not stop.is_set():
            if not s.save(qs[i % len(qs)], give_up_after=90):
                failures.append(f"{s.username}: jawaban tidak pernah ter-ACK")
            i += 1
            time.sleep(0.2)

    for s in students:
        threading.Thread(target=loop, args=(s,), daemon=True).start()


def s_server_kill(students: list[Student], server: Server, db_scalar: Callable[..., Any],
                  **_: Any) -> str:  # fmt: skip
    group = students[2:]
    before = {s.aid: s.heartbeat() for s in group}
    stop, failures = threading.Event(), list[str]()
    _saving(group, stop, failures)
    time.sleep(3)
    server.kill()
    down_at = time.monotonic()
    time.sleep(20)  # lebih lama dari batas putus heartbeat (15 dtk)
    server.start()
    downtime = time.monotonic() - down_at
    time.sleep(8)  # sweeper mendeteksi outage, siswa lanjut menyimpan
    stop.set()
    time.sleep(1)
    assert not failures, failures
    for s in group:
        lost = s.check_acked()
        assert not lost, f"{s.username}: {len(lost)} jawaban ber-ACK hilang setelah kill -9"
        t = s.heartbeat()
        assert t["state"] == "IN_PROGRESS", t["state"]
        assert t["pause_consumed_seconds"] == before[s.aid]["pause_consumed_seconds"], (
            "outage server memakan jatah jeda siswa"
        )
        shift = epoch(t["deadline_at"]) - epoch(before[s.aid]["deadline_at"])
        assert downtime - 8 <= shift <= downtime + 8, (
            f"kompensasi {shift:.0f} dtk vs mati {downtime:.0f}"
        )
    credited = db_scalar("select max(credited_sec) from server_outages")
    assert credited and credited >= 15, f"outage tidak tercatat: {credited}"
    revs = db_scalar("select count(*) from student_answers where server_revision > client_revision")
    assert revs == 0, "retry menggandakan revisi jawaban"
    acked = sum(len(s.acked) for s in group)
    retries = sum(s.retries for s in group)
    return (
        f"mati {downtime:.0f} dtk, outage dikredit {credited} dtk, {retries} retry, "
        f"{acked} ACK utuh"
    )


def s_db_restart(students: list[Student], db_restart: list[str], **_: Any) -> str:
    group = students[2:]
    stop, failures = threading.Event(), list[str]()
    health: list[int] = []

    def poll() -> None:
        while not stop.is_set():
            try:
                health.append(httpx.get(f"{BASE}/api/v1/healthz", timeout=2).status_code)
            except httpx.HTTPError:
                health.append(0)
            time.sleep(0.3)

    threading.Thread(target=poll, daemon=True).start()
    _saving(group, stop, failures)
    time.sleep(2)
    subprocess.run(db_restart, check=True, capture_output=True)  # noqa: S603
    t_back = time.monotonic()
    while time.monotonic() - t_back < 30 and (not health or health[-1] != 200):
        time.sleep(0.5)
    recovered = time.monotonic() - t_back
    time.sleep(5)
    stop.set()
    time.sleep(1)
    assert 503 in health, "health tidak pernah melapor DB DOWN selama restart (T-017)"
    assert health[-1] == 200, "API tidak pulih setelah DB kembali"
    assert recovered < 30, f"pulih {recovered:.0f} dtk"
    assert not failures, failures
    for s in group:
        assert not s.check_acked(), f"{s.username}: jawaban ber-ACK hilang setelah restart DB"
    down = sum(1 for h in health if h != 200)
    return f"health DOWN {down}x, pulih {recovered:.0f} dtk setelah restart, 0 ACK hilang"


def s_submit(students: list[Student], **_: Any) -> str:
    for s in students:
        key = str(uuid.uuid4())
        receipts = {
            s.c.post(
                f"/api/v1/student/attempts/{s.aid}/submit",
                json={"confirm": True},
                headers={"Idempotency-Key": key},
            ).json()["receipt_id"]
            for _ in range(2)
        }
        assert len(receipts) == 1, receipts
    return f"{len(students)} siswa, 1 receipt masing-masing"


SCENARIOS: list[tuple[str, Callable[..., str]]] = [
    ("refresh", s_refresh),
    ("wifi_drop", s_wifi_drop),
    ("server_kill", s_server_kill),
    ("db_restart", s_db_restart),
    ("submit", s_submit),
]


def main() -> None:
    parser = argparse.ArgumentParser(prog="chaos.py")
    parser.add_argument("--confirm-db", required=True)
    parser.add_argument("--db-restart-cmd", required=True)
    parser.add_argument("--students", type=int, default=6)
    args = parser.parse_args()

    from sqlalchemy import text

    from app.db import engine

    def db_scalar(sql: str) -> Any:
        with engine.connect() as c:
            return c.scalar(text(sql))

    server = Server()
    server.start()
    results: list[tuple[str, str]] = []
    try:
        loadtest.seed(BASE, args.confirm_db, max(args.students, 4), 10, 30)
        cfg = json.loads(loadtest.CREDENTIALS.read_text())
        students = [Student(u, cfg["password"]) for u in cfg["students"]]
        for s in students:
            s.start()
        proctor = httpx.Client(base_url=BASE, headers={"Origin": BASE}, timeout=5)
        r = proctor.post(
            "/api/v1/auth/login", json={"username": cfg["proctor"], "password": cfg["password"]}
        )
        r.raise_for_status()
        ctx = {
            "students": students,
            "server": server,
            "proctor": proctor,
            "db_scalar": db_scalar,
            "db_restart": shlex.split(args.db_restart_cmd),
        }
        for name, fn in SCENARIOS:
            t0, detail = time.monotonic(), ""
            try:
                detail = fn(**ctx)
                results.append((name, "LULUS"))
            except Exception as e:  # noqa: BLE001
                results.append((name, f"GAGAL: {type(e).__name__}: {e}"))
            extra = f" — {detail}" if results[-1][1] == "LULUS" else ""
            print(
                f"{name:<12} {results[-1][1]}{extra}  ({time.monotonic() - t0:.0f} dtk)", flush=True
            )
    finally:
        server.stop()
    failed = [r for r in results if r[1] != "LULUS"]
    print("\nLULUS" if not failed else f"\nGAGAL: {len(failed)} skenario")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
