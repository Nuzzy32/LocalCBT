#!/bin/sh
# API khusus E2E. Database localcbt_e2e DIHAPUS lalu dibuat ulang tiap run: jangan ubah namanya.
set -eu
out="$(cd "$(dirname "$0")" && pwd)/.tmp"
cd "$(dirname "$0")/../../../services/api"
mkdir -p "$out"
base="${LOCALCBT_E2E_PG:-postgresql+psycopg://localcbt:localcbt-dev@127.0.0.1:5432}"
export LOCALCBT_DATABASE_URL="$base/localcbt_e2e"
export LOCALCBT_COOKIE_SECURE=false
export LOCALCBT_ALLOWED_ORIGINS='["http://localhost:5174"]'
export LOCALCBT_BACKUP_SCHEDULER_ENABLED=false
export LOCALCBT_MEDIA_DIR="$out/media"
export LOCALCBT_LOG_LEVEL=WARNING

uv run python - "$base/localcbt" "$out/students.xlsx" <<'PY'
import sys
from openpyxl import Workbook
from sqlalchemy import create_engine, text

with create_engine(sys.argv[1], isolation_level="AUTOCOMMIT").connect() as db:
    db.execute(text("drop database if exists localcbt_e2e with (force)"))
    db.execute(text("create database localcbt_e2e"))
wb = Workbook()
ws = wb.active
ws.append(["NIS", "Nama", "Kelas"])
for n in range(1, 6):
    ws.append([f"00{n}", f"Siswa E2E {n}", "IX-A"])
wb.save(sys.argv[2])
PY
uv run alembic upgrade head
printf '%s\n' "$E2E_ADMIN_PASSWORD" | uv run python -m app.cli create-admin admin --name "Admin E2E" --password-stdin
exec uv run uvicorn app.main:app --host 127.0.0.1 --port 8200 --no-access-log
