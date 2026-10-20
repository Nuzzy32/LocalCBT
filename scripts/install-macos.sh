#!/bin/sh
# Pasang/perbarui LocalCBT sebagai service macOS (launchd). Jalankan dari folder repo:
#   sudo scripts/install-macos.sh             pasang pertama kali
#   sudo scripts/install-macos.sh --upgrade   versi baru: tolak bila ujian berjalan, backup, migrasi
# Prasyarat (offline-friendly, ditaruh di mesin lebih dulu): uv, PostgreSQL 16 (Postgres.app /
# Homebrew postgresql@16), caddy. Isi services/api/.env lewat Control Center → Setup awal.
set -eu

ROOT=$(cd "$(dirname "$0")/.." && pwd)
API="$ROOT/services/api"
LOGS=/Library/Logs/LocalCBT
DAEMONS=/Library/LaunchDaemons

[ "$(id -u)" -eq 0 ] || { echo "Jalankan dengan sudo." >&2; exit 1; }
OWNER=$(stat -f %Su "$ROOT")   # uv/venv dijalankan sebagai pemilik folder, bukan root
as_owner() { sudo -u "$OWNER" -H "$@"; }

UV=$(as_owner sh -lc 'command -v uv') || { echo "uv belum terpasang." >&2; exit 1; }
CADDY=$(command -v caddy || true)
[ -n "$CADDY" ] || { echo "caddy belum terpasang." >&2; exit 1; }
[ -f "$API/.env" ] || { echo "services/api/.env belum ada: jalankan Setup awal di Control Center." >&2; exit 1; }
chmod 600 "$API/.env"

echo "› Dependensi API"
(cd "$API" && as_owner "$UV" sync --locked --no-dev)

if [ "${1:-}" = "--upgrade" ]; then
  echo "› Upgrade: cek ujian berjalan, backup terverifikasi, migrasi"
  (cd "$API" && as_owner "$UV" run --no-dev python -m app.cli upgrade)
  launchctl kickstart -k system/id.localcbt.api
  echo "› Menunggu API sehat"
  for _ in $(seq 1 60); do
    curl -fsS http://127.0.0.1:8000/api/v1/healthz >/dev/null 2>&1 && { echo "Upgrade selesai."; exit 0; }
    sleep 1
  done
  echo "API tidak sehat setelah upgrade. Lihat $LOGS/api.log; restore memakai backup PRE_UPGRADE (ADMIN_GUIDE)." >&2
  exit 1
fi

echo "› Migrasi database"
(cd "$API" && as_owner "$UV" run --no-dev alembic upgrade head)

[ -f "$ROOT/apps/web/dist/index.html" ] || {
  echo "apps/web/dist belum ada: build web (pnpm -C apps/web build) atau pakai paket rilis." >&2; exit 1; }

HOST=$(sed -n 's/^LOCALCBT_PUBLIC_HOST=//p' "$API/.env" | tr -d "'\"")
[ -n "$HOST" ] || { echo "LOCALCBT_PUBLIC_HOST belum diisi di .env." >&2; exit 1; }

mkdir -p "$LOGS"
sed "s#__API_DIR__#$API#g" "$ROOT/infrastructure/macos/id.localcbt.api.plist" > "$DAEMONS/id.localcbt.api.plist"
sed -e "s#__ROOT__#$ROOT#g" -e "s#__CADDY__#$CADDY#g" -e "s#__HOST__#$HOST#g" \
  "$ROOT/infrastructure/macos/id.localcbt.caddy.plist" > "$DAEMONS/id.localcbt.caddy.plist"
chmod 644 "$DAEMONS"/id.localcbt.*.plist
chown root:wheel "$DAEMONS"/id.localcbt.*.plist

for svc in api caddy; do
  launchctl bootout "system/id.localcbt.$svc" 2>/dev/null || true
  launchctl bootstrap system "$DAEMONS/id.localcbt.$svc.plist"
done

echo "› Menunggu API sehat"
for _ in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:8000/api/v1/healthz >/dev/null 2>&1; then
    echo "Terpasang. Portal: https://$HOST — lanjutkan preflight & backup di Control Center."
    exit 0
  fi
  sleep 1
done
echo "API belum sehat. Lihat $LOGS/api.log" >&2
exit 1
