from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LOCALCBT_", env_file=".env")

    # Default = Postgres dev dari compose.dev.yml. Produksi wajib di-set lewat env/secret store.
    database_url: str = "postgresql+psycopg://localcbt:localcbt-dev@127.0.0.1:5432/localcbt"
    log_level: str = "INFO"
    # Origin yang boleh melakukan mutasi (CSRF/Origin check). Produksi: https://<host CBT>.
    allowed_origins: list[str] = ["http://localhost:5173", "https://localhost:8443"]
    cookie_secure: bool = True
    session_ttl_seconds: int = 12 * 3600
    # Siswa: login kedua ditolak selama sesi lama masih aktif dalam jendela ini.
    student_session_stale_seconds: int = 600
    # Gambar soal; nama berkas = sha256 isinya. Ikut dibackup bersama DB (M8).
    media_dir: Path = Path("data/media")
    # Sweep periodik (jeda otomatis, auto-submit). Dimatikan di tes; tes memanggil sweep_once().
    sweeper_enabled: bool = True
    # DEC-03: lama server mati ditambahkan ke batas waktu attempt aktif (default disetujui).
    outage_freeze: bool = True


settings = Settings()
