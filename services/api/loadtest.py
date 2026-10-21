"""Uji beban M9-03: N siswa serentak di 2 ujian, simpan jawaban beruntun, submit serentak.

HANYA untuk database uji (mis. hasil restore backup ke DB baru), jangan database produksi:
seed membuat akun/ujian berawalan "lt." yang tidak dihapus otomatis.

  # 1. Database uji + migrasi
  createdb localcbt_load && LOCALCBT_DATABASE_URL=.../localcbt_load uv run alembic upgrade head
  # 2. Server seperti produksi (1 proses, tanpa --reload), arahkan ke DB uji
  # 3. Seed lalu jalankan
  uv run python loadtest.py seed --confirm-db localcbt_load --base-url https://cbt.sekolah.test
  uv run python loadtest.py run                  # memakai base_url & akun dari .loadtest.json

Target PRD §3.2/NFR-04 (LAN normal): P95 simpan jawaban ≤ 1,5 dtk, P95 API lain ≤ 2 dtk,
0 jawaban ber-ACK hilang, tepat 1 attempt & 1 submit per siswa. Keluar kode 1 bila gagal.
Catatan: generator beban di mesin yang sama dengan server ikut memakan CPU; untuk angka
yang mewakili sekolah, jalankan `run` dari laptop lain di jaringan ujian.
"""

import argparse
import asyncio
import json
import random
import secrets
import statistics
import sys
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

CREDENTIALS = Path(".loadtest.json")  # di-.gitignore: berisi kata sandi akun uji
PREFIX = "lt."
TOKEN = "UJIBEBAN1"  # noqa: S105 — token ujian data uji
TARGET_P95 = {"save_answer": 1.5}
DEFAULT_P95 = 2.0


# ---- Seed ----------------------------------------------------------------------------


def _question(i: int) -> dict[str, Any]:
    kind = i % 3
    if kind == 0:
        return {
            "type": "SINGLE_CHOICE",
            "stem": f"Soal uji {i}: {i} + {i} = …",
            "weight": 1,
            "options": [{"text": str(i * 2 + d), "is_correct": d == 0} for d in range(5)],
        }
    if kind == 1:
        return {
            "type": "MULTIPLE_CHOICE",
            "stem": f"Soal uji {i}: pilih semua bilangan genap",
            "weight": 2,
            "options": [{"text": str(i + d), "is_correct": (i + d) % 2 == 0} for d in range(5)],
        }
    return {
        "type": "CATEGORY_CHOICE",
        "stem": f"Soal uji {i}: benar atau salah?",
        "weight": 3,
        "statements": [
            {"text": f"{i + d} lebih dari {i}", "correct_value": d > 0} for d in range(4)
        ],
    }


def seed(base_url: str, confirm_db: str, students: int, questions: int, minutes: int) -> None:
    # Impor app hanya di sini: `run` bisa dijalankan dari laptop lain tanpa akses DB.
    from sqlalchemy import make_url, text

    from app.auth import hash_password
    from app.config import settings
    from app.db import engine

    db_name = make_url(settings.database_url).database
    if confirm_db != db_name:
        sys.exit(f"Menolak: --confirm-db harus sama dengan database aktif ({db_name}).")
    password = secrets.token_urlsafe(12)
    pw_hash = hash_password(password)

    def user(db: Any, username: str, role: str, name: str) -> str:
        uid = db.scalar(
            text("""
            insert into users (username, password_hash, display_name) values (:u, :h, :n)
            on conflict ((lower(username))) do update set password_hash = excluded.password_hash
            returning id
            """),
            {"u": username, "h": pw_hash, "n": name},
        )
        db.execute(
            text("insert into user_roles (user_id, role) values (:i, :r) on conflict do nothing"),
            {"i": uid, "r": role},
        )
        return str(uid)

    run_id = datetime.now().strftime("%m%d%H%M%S")
    with engine.begin() as db:
        subject = str(
            db.scalar(
                text("""
            insert into subjects (code, name) values (:c, 'Uji Beban')
            on conflict (code) do update set name = excluded.name returning id
            """),
                {"c": "LT"},
            )
        )
        teacher = user(db, f"{PREFIX}guru", "TEACHER", "Guru Uji Beban")
        proctor = user(db, f"{PREFIX}pengawas", "PROCTOR", "Pengawas Uji Beban")
        classes = []
        for label in ("A", "B"):
            cls = db.scalar(
                text("""
                insert into classes (code, label, academic_year)
                values (:c, :l, '2026/2027') returning id
                """),
                {"c": f"LT-{run_id}-{label}", "l": f"Uji Beban {label}"},
            )
            db.execute(
                text("""
                insert into teaching_assignments (teacher_id, class_id, subject_id)
                values (:t, :c, :s)
                """),
                {"t": teacher, "c": cls, "s": subject},
            )
            classes.append(str(cls))
        names = []
        for n in range(1, students + 1):
            username = f"{PREFIX}s{run_id}{n:03d}"
            sid = user(db, username, "STUDENT", f"Siswa Uji {n}")
            db.execute(
                text("insert into class_memberships (class_id, student_id) values (:c, :s)"),
                {"c": classes[n % 2], "s": sid},
            )
            names.append(username)

    origin = _origin(base_url)
    with httpx.Client(base_url=base_url, headers={"Origin": origin}, verify=False) as c:
        r = c.post("/api/v1/auth/login", json={"username": f"{PREFIX}guru", "password": password})
        r.raise_for_status()
        c.headers["X-CSRF-Token"] = r.json()["csrf_token"]
        bank = c.post(
            "/api/v1/question-banks", json={"title": f"Uji beban {run_id}", "subject_id": subject}
        ).json()["id"]
        qids = []
        for i in range(questions):
            r = c.post(f"/api/v1/question-banks/{bank}/questions", json=_question(i))
            r.raise_for_status()
            qids.append(r.json()["id"])
        now = datetime.now(UTC)
        exams = []
        for label, cls in zip("AB", classes, strict=True):
            r = c.post(
                "/api/v1/exams",
                json={
                    "title": f"Uji beban {run_id} {label}",
                    "subject_id": str(subject),
                    "class_ids": [cls],
                    "question_ids": qids,
                    "start_window_from": (now - timedelta(minutes=1)).isoformat(),
                    "start_window_until": (now + timedelta(hours=3)).isoformat(),
                    "duration_seconds": minutes * 60,
                    "token": TOKEN,
                },
            )
            r.raise_for_status()
            exam = r.json()["id"]
            c.post(
                f"/api/v1/exams/{exam}/publish",
                json={"confirm": True, "scoring_rule_version": "PROPOSED-1"},
            ).raise_for_status()
            c.post(f"/api/v1/exams/{exam}/proctors", json={"user_id": proctor}).raise_for_status()
            exams.append(exam)
    CREDENTIALS.write_text(
        json.dumps(
            {
                "base_url": base_url,
                "password": password,
                "students": names,
                "teacher": f"{PREFIX}guru",
                "proctor": f"{PREFIX}pengawas",
                "exams": exams,
            },
            indent=1,
        )
    )
    CREDENTIALS.chmod(0o600)
    print(f"Seed selesai: {students} siswa, {questions} soal, 2 ujian. Data: {CREDENTIALS}")


# ---- Run -------------------------------------------------------------------------------


def _origin(base_url: str) -> str:
    parts = urlsplit(base_url)
    return f"{parts.scheme}://{parts.netloc}"


@dataclass
class Stats:
    latencies: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))
    errors: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))
    integrity: list[str] = field(default_factory=list)

    async def call(
        self, client: httpx.AsyncClient, name: str, method: str, url: str, **kw: Any
    ) -> httpx.Response | None:
        t0 = time.perf_counter()
        try:
            r = await client.request(method, url, **kw)
        except httpx.HTTPError as e:
            self.latencies[name].append(time.perf_counter() - t0)
            self.errors[name].append(type(e).__name__)
            return None
        self.latencies[name].append(time.perf_counter() - t0)
        if r.status_code >= 400:
            self.errors[name].append(f"{r.status_code} {r.text[:120]}")
        return r


def _answer(q: dict[str, Any], rng: random.Random) -> dict[str, Any]:
    if q["type"] == "SINGLE_CHOICE":
        return {"type": q["type"], "selected_option_id": rng.choice(q["options"])["id"]}
    if q["type"] == "MULTIPLE_CHOICE":
        picked = rng.sample(q["options"], rng.randint(1, len(q["options"])))
        return {"type": q["type"], "selected_option_ids": [o["id"] for o in picked]}
    return {
        "type": q["type"],
        "choices": [
            {"statement_id": s["id"], "value": rng.random() < 0.5} for s in q["statements"]
        ],
    }


async def student(
    cfg: dict[str, Any],
    username: str,
    stats: Stats,
    think: float,
    started: asyncio.Barrier,
    submit_gate: asyncio.Barrier,
    seed_value: int,
) -> None:
    rng = random.Random(seed_value)
    base = cfg["base_url"]
    async with httpx.AsyncClient(
        base_url=base,
        headers={"Origin": _origin(base)},
        verify=False,
        timeout=30,
    ) as c:
        r = await stats.call(
            c, "login", "POST", "/api/v1/auth/login",
            json={"username": username, "password": cfg["password"]},
        )  # fmt: skip
        if r is None or r.status_code != 200:
            stats.integrity.append(f"{username}: login gagal")
            await started.wait()
            await submit_gate.wait()
            return
        c.headers["X-CSRF-Token"] = r.json()["csrf_token"]
        r = await stats.call(c, "list_exams", "GET", "/api/v1/student/exams")
        exam = r.json()[0]["id"] if r is not None and r.status_code == 200 and r.json() else None
        await started.wait()  # semua siswa menekan "Mulai" hampir bersamaan (burst)
        attempt = None
        if exam:
            r = await stats.call(
                c, "verify_token", "POST", f"/api/v1/student/exams/{exam}/token/verify",
                json={"token": TOKEN},
            )  # fmt: skip
            if r is not None and r.status_code == 200:
                r = await stats.call(
                    c, "start_attempt", "POST", f"/api/v1/student/exams/{exam}/attempts",
                    json={"start_grant": r.json()["start_grant"], "confirm_start": True},
                    headers={"Idempotency-Key": str(uuid.uuid4())},
                )  # fmt: skip
                attempt = r.json() if r is not None and r.status_code in (200, 201) else None
        if attempt is None:
            stats.integrity.append(f"{username}: tidak bisa memulai ujian")
            await submit_gate.wait()
            return

        aid = attempt["id"]
        done = asyncio.Event()

        async def heartbeat() -> None:
            while not done.is_set():
                await stats.call(
                    c, "heartbeat", "POST", f"/api/v1/student/attempts/{aid}/heartbeat",
                    json={"tab_visible": True},
                )  # fmt: skip
                try:
                    await asyncio.wait_for(done.wait(), 5)
                except TimeoutError:
                    pass

        beat = asyncio.create_task(heartbeat())
        acked: dict[str, Any] = {}
        revision = 0
        # Kerjakan semua soal, lalu ubah ~20% jawaban (navigasi bebas, BR-02).
        order = attempt["questions"] + rng.sample(
            attempt["questions"], len(attempt["questions"]) // 5
        )
        for q in order:
            await asyncio.sleep(rng.uniform(think * 0.5, think * 1.5))
            revision += 1
            answer = _answer(q, rng)
            r = await stats.call(
                c, "save_answer", "PUT", f"/api/v1/student/attempts/{aid}/answers/{q['id']}",
                json={"answer": answer, "client_revision": revision, "marked_for_review": False},
                headers={"Idempotency-Key": str(uuid.uuid4())},
            )  # fmt: skip
            if r is not None and r.status_code == 200:
                acked[q["id"]] = answer

        # Integritas (G-02): setiap jawaban ber-ACK harus persis yang tersimpan di server.
        r = await stats.call(c, "get_attempt", "GET", f"/api/v1/student/attempts/{aid}")
        if r is not None and r.status_code == 200:
            server = {a["question_id"]: a["answer"] for a in r.json()["answers"]}
            lost = [qid for qid, ans in acked.items() if server.get(qid) != ans]
            if lost:
                stats.integrity.append(f"{username}: {len(lost)} jawaban ber-ACK tidak cocok")
        else:
            stats.integrity.append(f"{username}: gagal membaca attempt untuk verifikasi")

        await submit_gate.wait()  # semua siswa mengumpulkan bersamaan (burst submit)
        key = str(uuid.uuid4())
        receipts = set()
        for _ in range(2):  # klik ganda / retry: harus satu receipt yang sama (FR-REC-10)
            r = await stats.call(
                c, "submit", "POST", f"/api/v1/student/attempts/{aid}/submit",
                json={"confirm": True}, headers={"Idempotency-Key": key},
            )  # fmt: skip
            if r is not None and r.status_code in (200, 201):
                receipts.add(r.json()["receipt_id"])
        if len(receipts) != 1:
            stats.integrity.append(f"{username}: receipt submit {len(receipts)} (harus 1)")
        done.set()
        await beat


async def proctor_and_teacher(cfg: dict[str, Any], stats: Stats, stop: asyncio.Event) -> None:
    """Pengawas memantau lewat WebSocket, guru mengekspor nilai saat ujian berjalan."""
    import websockets

    base = cfg["base_url"]
    origin = _origin(base)

    async def login(username: str) -> httpx.AsyncClient:
        c = httpx.AsyncClient(base_url=base, headers={"Origin": origin}, verify=False, timeout=30)
        r = await c.post(
            "/api/v1/auth/login", json={"username": username, "password": cfg["password"]}
        )
        r.raise_for_status()
        c.headers["X-CSRF-Token"] = r.json()["csrf_token"]
        return c

    try:
        proctor = await login(cfg["proctor"])
        teacher = await login(cfg["teacher"])
    except httpx.HTTPError as e:
        stats.errors["monitor_ws"].append(f"login pengawas/guru gagal: {type(e).__name__}")
        return
    cookie = "; ".join(f"{k}={v}" for k, v in proctor.cookies.items())
    ws_base = base.replace("https://", "wss://").replace("http://", "ws://")

    async def watch(exam: str) -> None:
        url = f"{ws_base}/api/v1/ws/exams/{exam}"
        ssl_ctx = None
        if url.startswith("wss://"):
            import ssl

            ssl_ctx = ssl.create_default_context()
            ssl_ctx.check_hostname = False
            ssl_ctx.verify_mode = ssl.CERT_NONE
        try:
            async with websockets.connect(
                url, additional_headers={"Origin": origin, "Cookie": cookie}, ssl=ssl_ctx
            ) as ws:
                last = time.perf_counter()
                while not stop.is_set():
                    try:
                        await asyncio.wait_for(ws.recv(), 10)
                    except TimeoutError:
                        stats.errors["monitor_ws"].append("tidak ada snapshot 10 dtk")
                        continue
                    now = time.perf_counter()
                    stats.latencies["monitor_ws_interval"].append(now - last)
                    last = now
        except Exception as e:  # noqa: BLE001
            stats.errors["monitor_ws"].append(f"{type(e).__name__}: {e}")

    async def export_loop() -> None:
        while not stop.is_set():
            for exam in cfg["exams"]:
                await stats.call(
                    teacher, "export_xlsx", "GET", f"/api/v1/teacher/exams/{exam}/results/export"
                )
            try:
                await asyncio.wait_for(stop.wait(), 20)
            except TimeoutError:
                pass

    try:
        await asyncio.gather(*(watch(e) for e in cfg["exams"]), export_loop())
    finally:
        await proctor.aclose()
        await teacher.aclose()


def _pct(values: list[float], p: float) -> float:
    if len(values) < 2:
        return values[0] if values else 0.0
    return statistics.quantiles(values, n=100, method="inclusive")[int(p) - 1]


def report(stats: Stats, wall: float, students: int) -> tuple[bool, dict[str, Any]]:
    rows, ok = {}, True
    for name, vals in sorted(stats.latencies.items()):
        if name == "monitor_ws_interval":
            continue
        p95 = _pct(vals, 95)
        limit = TARGET_P95.get(name, DEFAULT_P95)
        passed = p95 <= limit and not stats.errors.get(name)
        ok &= passed
        rows[name] = {
            "count": len(vals),
            "errors": len(stats.errors.get(name, [])),
            "p50_ms": round(_pct(vals, 50) * 1000),
            "p95_ms": round(p95 * 1000),
            "p99_ms": round(_pct(vals, 99) * 1000),
            "max_ms": round(max(vals) * 1000),
            "target_p95_ms": round(limit * 1000),
            "pass": passed,
        }
    ws = stats.latencies.get("monitor_ws_interval", [])
    ws_errors = stats.errors.get("monitor_ws", [])
    ok &= not ws_errors and not stats.integrity
    return ok, {
        "students": students,
        "wall_seconds": round(wall, 1),
        "endpoints": rows,
        "monitor_ws": {
            "frames": len(ws),
            "max_gap_ms": round(max(ws) * 1000) if ws else None,
            "errors": ws_errors[:10],
        },
        "integrity_failures": stats.integrity,
        "error_samples": {k: v[:3] for k, v in stats.errors.items()},
        "pass": ok,
    }


async def run(students: int | None, think: float) -> int:
    cfg = json.loads(CREDENTIALS.read_text())
    names = cfg["students"][:students] if students else cfg["students"]
    stats = Stats()
    started, submit_gate = asyncio.Barrier(len(names)), asyncio.Barrier(len(names))
    stop = asyncio.Event()
    t0 = time.perf_counter()
    side = asyncio.create_task(proctor_and_teacher(cfg, stats, stop))
    await asyncio.gather(
        *(
            student(cfg, n, stats, think, started, submit_gate, seed_value=i)
            for i, n in enumerate(names)
        )
    )
    stop.set()
    await side
    ok, data = report(stats, time.perf_counter() - t0, len(names))
    print(f"\n{'endpoint':<14}{'n':>6}{'err':>5}{'p50':>7}{'p95':>7}{'p99':>7}{'max':>7}  target")
    for name, r in data["endpoints"].items():
        mark = "OK " if r["pass"] else "GAGAL"
        print(
            f"{name:<14}{r['count']:>6}{r['errors']:>5}{r['p50_ms']:>7}{r['p95_ms']:>7}"
            f"{r['p99_ms']:>7}{r['max_ms']:>7}  ≤{r['target_p95_ms']} {mark}"
        )
    print(f"monitor WS: {data['monitor_ws']}")
    print(f"integritas: {data['integrity_failures'] or 'OK (0 jawaban ber-ACK hilang)'}")
    if data["error_samples"]:
        print(f"contoh error: {data['error_samples']}")
    out = Path(f"loadtest-report-{datetime.now():%Y%m%d-%H%M%S}.json")
    out.write_text(json.dumps(data, indent=1))
    print(f"\n{'LULUS' if ok else 'GAGAL'} — laporan: {out}")
    return 0 if ok else 1


def main() -> None:
    parser = argparse.ArgumentParser(prog="loadtest.py")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("seed")
    p.add_argument("--confirm-db", required=True, help="nama database uji (pengaman)")
    p.add_argument("--base-url", required=True)
    p.add_argument("--students", type=int, default=30)
    p.add_argument("--questions", type=int, default=40)
    p.add_argument("--minutes", type=int, default=90)
    p = sub.add_parser("run")
    p.add_argument("--students", type=int)
    p.add_argument("--think", type=float, default=2.0, help="rata-rata detik antar jawaban")
    args = parser.parse_args()
    if args.cmd == "seed":
        seed(args.base_url, args.confirm_db, args.students, args.questions, args.minutes)
    else:
        sys.exit(asyncio.run(run(args.students, args.think)))


if __name__ == "__main__":
    main()
