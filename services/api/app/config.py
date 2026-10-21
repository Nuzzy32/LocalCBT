from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LOCALCBT_", env_file=".env")

    # Default = Postgres dev dari compose.dev.yml. Produksi wajib di-set lewat env/secret store.
    database_url: str = "postgresql+psycopg://localcbt:localcbt-dev@127.0.0.1:5432/localcbt"
    log_level: str = "INFO"
    # Swagger/OpenAPI hanya untuk development: di produksi tidak perlu dibuka ke jaringan siswa.
    api_docs: bool = False
    # Origin yang boleh melakukan mutasi (CSRF/Origin check). Produksi: https://<host CBT>.
    allowed_origins: list[str] = ["http://localhost:5173", "https://localhost:8443"]
    cookie_secure: bool = True
    session_ttl_seconds: int = 12 * 3600
    # Siswa di luar ujian: login kedua ditolak selama sesi lama aktif dalam jendela ini. Saat
    # attempt berjalan tidak ada jendela: pindah perangkat wajib lewat pengawas (BR-21).
    student_session_stale_seconds: int = 600
    # Sesi siswa berakhir setelah diam selama ini (komputer lab dipakai bergantian).
    student_session_idle_seconds: int = 1800
    # Gambar soal; nama berkas = sha256 isinya. Ikut dibackup bersama DB (M8).
    media_dir: Path = Path("data/media")
    # Sweep periodik (jeda otomatis, auto-submit). Dimatikan di tes; tes memanggil sweep_once().
    sweeper_enabled: bool = True
    # DEC-03: lama server mati ditambahkan ke batas waktu attempt aktif (default disetujui).
    outage_freeze: bool = True
    # Backup (M8). Arahkan backup_dir ke disk/drive lain dari media_dir bila memungkinkan.
    backup_dir: Path = Path("data/backups")
    # Kunci enkripsi backup (NFR-11). Tanpa ini backup ditolak. Simpan salinannya di luar server.
    backup_passphrase: str = ""
    # Folder pg_dump/pg_restore bila tidak ada di PATH (mis. /opt/homebrew/opt/libpq/bin).
    pg_bin_dir: Path | None = None
    backup_scheduler_enabled: bool = True
    # Nama portal (mis. cbt.sekolah.sch.id) untuk preflight DNS/HTTPS.
    public_host: str = ""
    # Subnet jaringan ujian, mis. ["10.20.0.0/22"]; laporan probe dari luar subnet tidak dihitung.
    exam_subnets: list[str] = []


settings = Settings()
