from collections.abc import Iterator
from typing import Annotated

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
