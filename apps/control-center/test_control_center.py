import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from control_center import (  # noqa: E402
    api_python,
    backup_label,
    can_stop,
    describe,
    env_quote,
    fmt_bytes,
    merge_env,
    redact,
    service_commands,
)


def test_describe() -> None:
    assert describe(200, b'{"database_status":"OK"}') == ("● RUNNING", "● OK")
    assert describe(503, b'{"database_status":"DOWN"}') == ("● RUNNING", "● DOWN")
    assert describe(None, b"")[0].startswith("● STOPPED")
    assert describe(0, b"")[0].startswith("● STOPPED")
    # Body aneh tidak boleh jadi hijau
    assert describe(200, b"not json")[1] == "● DOWN"
    assert describe(500, b"")[0] == "● ERROR (HTTP 500)"


def test_redact_python_repr_and_auth_header() -> None:
    out = redact("{'password': 'rahasia-siswa', 'n': 1} Authorization: Bearer abc.def")
    assert "rahasia-siswa" not in out and "abc.def" not in out


def test_env_values_roundtrip_through_dotenv(tmp_path: Path) -> None:
    from dotenv import dotenv_values

    values = {
        "A": 'pass phrase #1 {HOME} "q" \\x',
        "B": '["10.20.0.0/22"]',
        "C": "postgresql+psycopg://u:p@h:5432/db",
    }
    env = tmp_path / ".env"
    env.write_text(merge_env("", values))
    assert dotenv_values(env) == values


def test_redact_hides_secrets_and_student_data() -> None:
    line = (
        '{"msg": "x", "password": "hunter2-rahasia", "url": '
        '"postgresql+psycopg://localcbt:sandi-db@127.0.0.1/localcbt", '
        '"request_id": "4e517484-e62e-4cb9-81ed-bc2bdb9cf624", '
        '"token": "abc", "nisn": "0051234567", "email": "siswa@sekolah.sch.id", '
        '"session": "q8Yt1n0v3Rk9xZ2pL5mW7cB4dF6hJ8sA0eG"}'
    )
    out = redact(line)
    for secret in ("hunter2", "sandi-db", "0051234567", "siswa@sekolah", "q8Yt1n0v3Rk9"):
        assert secret not in out, secret
    assert '"token": "***"' in out
    assert "4e517484-e62e-4cb9-81ed-bc2bdb9cf624" in out  # request id tetap berguna
    assert "127.0.0.1" in out


def test_can_stop_requires_reason_during_exams() -> None:
    assert can_stop(0, "")[0]
    assert can_stop(None, "")[0]  # DB mati: tidak bisa tahu, jangan kunci operator
    allowed, msg = can_stop(3, "")
    assert not allowed and "3 ujian" in msg
    assert not can_stop(3, "pendek")[0]
    assert can_stop(3, "Server hang, semua siswa macet")[0]


def test_service_commands_per_os() -> None:
    mac = service_commands("STOP", "darwin")
    assert mac and mac[0][0] == "osascript" and "bootout system/id.localcbt.api" in mac[0][2]
    assert service_commands("RESTART", "win32") == [
        ["sc", "stop", "LocalCBT-API"],
        ["sc", "start", "LocalCBT-API"],
    ]
    assert service_commands("START", "linux") is None
    assert str(api_python(__import__("pathlib").Path("/x"), "win32")).endswith("python.exe")


def test_backup_label_never_green_when_unsure() -> None:
    assert "BELUM SIAP" in backup_label({"backup_passphrase_set": False})
    assert "BELUM ADA" in backup_label({"backup_passphrase_set": True})
    failed = {
        "backup_passphrase_set": True,
        "last_verified_backup_at": "2026-10-19T02:00:00+07:00",
        "last_backup": {"status": "FAILED", "error": "disk penuh", "created_at": None},
    }
    assert "GAGAL" in backup_label(failed) and "disk penuh" in backup_label(failed)
    ok = {**failed, "last_backup": {"status": "VERIFIED"}}
    assert backup_label(ok).startswith("● OK")


def test_merge_env_and_quoting() -> None:
    merged = merge_env(
        "A=1\nLOCALCBT_BACKUP_PASSPHRASE=lama\n", {"LOCALCBT_BACKUP_PASSPHRASE": "a b#c"}
    )
    assert merged == "A=1\nLOCALCBT_BACKUP_PASSPHRASE='a b#c'\n"
    assert env_quote('["10.0.0.0/8"]') == "'[\"10.0.0.0/8\"]'"
    for bad in ("it's", "a\nLOCALCBT_X=1", "p${HOME}x"):
        try:
            env_quote(bad)
            raise AssertionError(bad)
        except ValueError:
            pass
    assert fmt_bytes(1536) == "1.5 KB" and fmt_bytes(None) == "-"


def test_window_builds_offscreen() -> None:
    from PySide6.QtWidgets import QApplication

    from control_center import Window

    app = QApplication.instance() or QApplication([])
    w = Window()
    assert w.windowTitle() == "LocalCBT Control Center"
    w.close()
    app.processEvents()


def test_tone_marks_bad_states() -> None:
    from control_center import tone

    assert tone("● STOPPED / tidak terjangkau") == "#b3261e"
    assert tone("● UNTESTED: belum") == "#8a5a00"
    assert tone("● OK, terverifikasi") == "#0a6b2e"
