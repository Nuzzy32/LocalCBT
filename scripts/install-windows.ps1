# Pasang/perbarui LocalCBT sebagai Windows Service (WinSW). Jalankan PowerShell sebagai Administrator
# dari folder repo:
#   powershell -ExecutionPolicy Bypass -File scripts\install-windows.ps1            pasang
#   powershell -ExecutionPolicy Bypass -File scripts\install-windows.ps1 -Upgrade   versi baru
# Prasyarat (ditaruh di mesin lebih dulu, tanpa internet): uv, PostgreSQL 16 (installer EDB),
# infrastructure\windows\localcbt-api.exe & localcbt-caddy.exe (= WinSW-x64.exe yang diganti nama),
# infrastructure\windows\caddy.exe. Isi services\api\.env lewat Control Center -> Setup awal.
# BELUM DIUJI di Windows asli (T-018 Windows): uji di mesin target sebelum pilot.
param([switch]$Upgrade)
$ErrorActionPreference = "Stop"

$Root = Resolve-Path "$PSScriptRoot\.."
$Api = "$Root\services\api"
$Win = "$Root\infrastructure\windows"
$Env = "$Api\.env"

$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
  throw "Jalankan PowerShell sebagai Administrator."
}
foreach ($f in @("$Win\localcbt-api.exe", "$Win\localcbt-caddy.exe", "$Win\caddy.exe", $Env)) {
  if (-not (Test-Path $f)) { throw "Tidak ditemukan: $f" }
}
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { throw "uv belum terpasang." }

# .env hanya bisa dibaca Administrators & SYSTEM (berisi kata sandi DB & kunci backup).
icacls $Env /inheritance:r /grant:r "Administrators:F" "SYSTEM:F" | Out-Null
New-Item -ItemType Directory -Force "C:\LocalCBT\logs", "C:\LocalCBT\caddy" | Out-Null

function Wait-Healthy {
  for ($i = 0; $i -lt 60; $i++) {
    try { Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/api/v1/healthz | Out-Null; return $true }
    catch { Start-Sleep 1 }
  }
  return $false
}

Write-Host "> Dependensi API"
Push-Location $Api
uv sync --locked --no-dev
if ($LASTEXITCODE) { throw "uv sync gagal" }

if ($Upgrade) {
  Write-Host "> Upgrade: cek ujian berjalan, backup terverifikasi, migrasi"
  uv run --no-dev python -m app.cli upgrade
  if ($LASTEXITCODE) { Pop-Location; throw "Upgrade dibatalkan (lihat pesan di atas)." }
  Pop-Location
  Restart-Service LocalCBT-API
  if (Wait-Healthy) { Write-Host "Upgrade selesai."; exit 0 }
  throw "API tidak sehat setelah upgrade. Lihat C:\LocalCBT\logs; restore memakai backup PRE_UPGRADE (ADMIN_GUIDE)."
}

Write-Host "> Migrasi database"
uv run --no-dev alembic upgrade head
if ($LASTEXITCODE) { Pop-Location; throw "Migrasi gagal" }
Pop-Location

if (-not (Test-Path "$Root\apps\web\dist\index.html")) { throw "apps\web\dist belum ada (pakai paket rilis)." }
$HostLine = Select-String -Path $Env -Pattern '^LOCALCBT_PUBLIC_HOST=(.+)$' | Select-Object -First 1
if (-not $HostLine) { throw "LOCALCBT_PUBLIC_HOST belum diisi di .env." }
$PublicHost = $HostLine.Matches[0].Groups[1].Value.Trim("'", '"')
(Get-Content "$Win\localcbt-caddy.xml") -replace "__HOST__", $PublicHost |
  Set-Content "$Win\localcbt-caddy.generated.xml"
Copy-Item "$Win\localcbt-caddy.exe" "$Win\localcbt-caddy.generated.exe" -Force

foreach ($svc in @("localcbt-api", "localcbt-caddy.generated")) {
  & "$Win\$svc.exe" stop 2>$null
  & "$Win\$svc.exe" uninstall 2>$null
  & "$Win\$svc.exe" install
  if ($LASTEXITCODE) { throw "Gagal memasang service $svc" }
  & "$Win\$svc.exe" start
}

if (Wait-Healthy) {
  Write-Host "Terpasang. Portal: https://$PublicHost - lanjutkan preflight & backup di Control Center."
} else {
  throw "API belum sehat. Lihat C:\LocalCBT\logs\localcbt-api.err.log"
}
