import json
from collections.abc import Iterator
from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends
from sqlalchemy import Connection, create_engine, text

from app.config import settings

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    connect_args={"connect_timeout": 2},
)


def get_db() -> Iterator[Connection]:
    """Satu transaksi per request: commit bila handler sukses, rollback bila exception."""
    with engine.begin() as conn:
        yield conn


# scope="function": commit selesai SEBELUM response dikirim (ACK = sudah durable).
DB = Annotated[Connection, Depends(get_db, scope="function")]


def database_ok() -> bool:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def audit(
    db: Connection,
    actor_id: UUID | None,
    action: str,
    target_type: str,
    target_id: UUID,
    reason: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Jejak tindakan penting (append-only). Jangan masukkan jawaban, token, atau kata sandi."""
    db.execute(
        text("""
        insert into audit_events (actor_id, action, target_type, target_id, reason, metadata)
        values (:a, :act, :tt, :tid, :r, cast(:m as jsonb))
        """),
        {
            "a": actor_id,
            "act": action,
            "tt": target_type,
            "tid": target_id,
            "r": reason,
            "m": json.dumps(metadata or {}),
        },
    )
