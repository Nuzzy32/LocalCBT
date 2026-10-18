"""Sweep periodik: outage server, jeda otomatis saat heartbeat hilang, batas jeda, auto-submit.

Berjalan di thread sendiri (bukan threadpool request) agar tidak kalah antre dengan heartbeat
lalu terlihat seperti outage palsu. Aman untuk >1 proses: baris server_clock & SKIP LOCKED.
"""

import logging
import threading

from sqlalchemy import text

from app.attempts import HEARTBEAT_TIMEOUT, PAUSE_CAP, PAUSE_TOTAL, close_pause, expire_due
from app.config import settings
from app.db import engine

log = logging.getLogger("localcbt.sweeper")
SWEEP_INTERVAL = 5


def _clock_and_outage() -> None:
    with engine.begin() as db:
        prev = db.scalar(text("select last_sweep_at from server_clock for update"))
        gap = db.scalar(text("select extract(epoch from now() - :p)"), {"p": prev})
        db.execute(text("update server_clock set last_sweep_at = now()"))
        if gap is None or gap < HEARTBEAT_TIMEOUT:
            return
        # Server/DB tidak berjalan: ini bukan kesalahan siswa. DEC-03 (default disetujui):
        # bekukan waktu = geser deadline & jeda sebesar lama outage, tanpa auto-submit massal.
        shift = "now() - :p" if settings.outage_freeze else "interval '0'"
        affected = db.execute(
            text(f"""
            update exam_attempts set
              effective_deadline_at = effective_deadline_at + ({shift}),
              paused_at = paused_at + ({shift}),
              last_heartbeat_at = now()
            where state in ('IN_PROGRESS', 'PAUSED') and effective_deadline_at > :p
            """),  # noqa: S608 — fragmen konstan
            {"p": prev},
        ).rowcount
        if affected:
            db.execute(
                text("""
                insert into server_outages (started_at, ended_at, credited_sec, affected_attempts)
                values (:p, now(), :c, :n)
                """),
                {"p": prev, "c": int(gap) if settings.outage_freeze else 0, "n": affected},
            )
            log.warning(
                "server outage",
                extra={"extra_fields": {"seconds": int(gap), "affected_attempts": affected}},
            )


def _pauses() -> None:
    with engine.begin() as db:
        capped = db.scalars(
            text("""
            select id from exam_attempts
            where state = 'PAUSED'
              and now() >= paused_at
                + make_interval(secs => least(:cap, :total - pause_consumed_sec))
            for update skip locked
            """),
            {"cap": PAUSE_CAP, "total": PAUSE_TOTAL},
        ).all()
        for attempt_id in capped:
            close_pause(db, attempt_id, "CAP")
        # Jeda dimulai tepat HEARTBEAT_TIMEOUT setelah heartbeat terakhir (data server saja).
        # Tidak membuka insiden baru untuk putus yang sama setelah jatahnya habis (CAP).
        db.execute(
            text("""
            update exam_attempts a set state = 'PAUSED',
              paused_at = a.last_heartbeat_at + make_interval(secs => :hb)
            where a.id in (
              select x.id from exam_attempts x
              where x.state = 'IN_PROGRESS'
                and x.last_heartbeat_at < now() - make_interval(secs => :hb)
                and x.pause_consumed_sec < :total
                and x.effective_deadline_at > x.last_heartbeat_at + make_interval(secs => :hb)
                and not exists (select 1 from pause_incidents p
                                where p.attempt_id = x.id and p.resumed_at > x.last_heartbeat_at)
              for update skip locked)
            """),
            {"hb": HEARTBEAT_TIMEOUT, "total": PAUSE_TOTAL},
        )


def _expire() -> None:
    with engine.connect() as db:
        due = db.scalars(
            text("""
            select id from exam_attempts
            where state = 'IN_PROGRESS' and effective_deadline_at <= now()
            """)
        ).all()
    for attempt_id in due:  # satu transaksi per attempt: satu baris bermasalah tidak menahan lain
        try:
            with engine.begin() as db:
                expire_due(db, attempt_id=attempt_id)
        except Exception:
            log.exception(
                "auto-submit failed", extra={"extra_fields": {"attempt": str(attempt_id)}}
            )


def sweep_once() -> None:
    _clock_and_outage()  # commit terpisah: kegagalan langkah lain tidak memalsukan outage
    _pauses()
    _expire()


class Sweeper:
    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="sweeper", daemon=True)

    def _run(self) -> None:
        while True:
            try:
                sweep_once()
            except Exception:
                log.exception("sweep failed")
            if self._stop.wait(SWEEP_INTERVAL):
                return

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=10)
