# LocalCBT

CBT ujian sekolah yang berjalan penuh di LAN. Spesifikasi: [`docs/`](docs/).

| Path | Isi |
|---|---|
| `services/api` | FastAPI + SQLAlchemy + Alembic (PostgreSQL) |
| `apps/web` | React + TypeScript + Vite (satu app, route per role) |
| `apps/control-center` | PySide6, hanya di komputer server |
| `infrastructure/proxy` | Caddy: HTTPS same-origin web + API + WebSocket |
| `infrastructure/macos` | launchd: API + Caddy |
| `infrastructure/windows` | WinSW: API + Caddy |
| `scripts` | Installer/upgrade macOS & Windows |

Panduan pengguna: [admin/operator](docs/ADMIN_GUIDE.md), [guru](docs/TEACHER_QUICKSTART.md),
[pengawas](docs/PROCTOR_SOP.md). Kebutuhan produk: [`docs/PRD.docx`](docs/PRD.docx).

## Development

Butuh: Docker, [uv](https://docs.astral.sh/uv/), Node 26 + pnpm, klien PostgreSQL 16
(`pg_dump`/`pg_restore`, versi mayor harus sama dengan server; macOS: `brew install postgresql@16`
lalu `LOCALCBT_PG_BIN_DIR=/opt/homebrew/opt/postgresql@16/bin`).

```bash
docker compose -f compose.dev.yml up -d          # PostgreSQL dev
cd services/api && uv sync && uv run alembic upgrade head
uv run python -m app.cli create-admin admin --name "Admin Sekolah"   # admin pertama
echo 'LOCALCBT_BACKUP_PASSPHRASE=dev-only-passphrase' >> .env  # backup ditolak tanpa ini
uv run uvicorn app.main:app --reload             # http://127.0.0.1:8000/api/v1/docs
cd apps/web && pnpm install && pnpm dev          # http://localhost:5173 (proxy /api)
cd apps/control-center && uv sync && uv run python control_center.py
```

Cek sebelum PR (sama dengan CI):

```bash
cd services/api && uv run ruff format --check . && uv run ruff check . && uv run mypy && uv run pytest -q
cd apps/web && pnpm lint && pnpm build
cd apps/control-center && uv run ruff check . && uv run pytest -q
```

Proof HTTPS lokal (Caddy, `tls internal`, trust sertifikat masih ADR-003 OPEN):

```bash
pnpm -C apps/web build
docker run --rm -p 127.0.0.1:8443:443 -e LOCALCBT_HOST=localhost \
  -e LOCALCBT_API=host.docker.internal:8000 -e LOCALCBT_WEB_ROOT=/srv \
  -v "$PWD/infrastructure/proxy/Caddyfile:/etc/caddy/Caddyfile:ro" \
  -v "$PWD/apps/web/dist:/srv:ro" caddy:2
```

Jangan commit `.env`, kunci TLS, backup, atau data siswa.
