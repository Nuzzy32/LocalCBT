"""LocalCBT Control Center (M8).

Jendela operator untuk server sekolah: status, preflight jaringan, backup/restore, log, dan
start/stop service. Backend berjalan sebagai service OS terpisah (launchd / WinSW), jadi menutup
jendela ini tidak menghentikan ujian (FR-ADM-02).

Semua aksi memanggil CLI backend (`python -m app.cli --json ...`) di folder API, sehingga tetap
berfungsi saat API mati dan tidak butuh token/kata sandi tambahan: yang menjalankan jendela ini
sudah admin OS di server (bisa membaca .env dan mengendalikan service).
"""

import json
import os
import re
import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

import psutil
from PySide6.QtCore import QProcess, QTimer, QUrl
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
    QWizard,
    QWizardPage,
)

API_URL = os.environ.get("LOCALCBT_API_URL", "http://127.0.0.1:8000")
API_DIR = Path(
    os.environ.get("LOCALCBT_API_DIR", Path(__file__).resolve().parents[2] / "services" / "api")
)
DEFAULT_LOG = (
    r"C:\LocalCBT\logs\localcbt-api.err.log"
    if sys.platform == "win32"
    else "/Library/Logs/LocalCBT/api.log"
)
LOG_FILE = Path(os.environ.get("LOCALCBT_LOG_FILE", DEFAULT_LOG))
POLL_MS = 3000
STATUS_MS = 15000
MAC_LABEL = "id.localcbt.api"
MAC_PLIST = f"/Library/LaunchDaemons/{MAC_LABEL}.plist"
WIN_SERVICE = "LocalCBT-API"

# ---- Fungsi murni (dites tanpa GUI) ---------------------------------------------------


def describe(http_status: int | None, body: bytes) -> tuple[str, str]:
    """(service, database) label. Tidak pernah hijau bila data tidak meyakinkan (T-017)."""
    if not http_status:
        return "● STOPPED / tidak terjangkau", "● tidak diketahui"
    try:
        db = json.loads(body).get("database_status")
    except (ValueError, AttributeError):
        db = None
    service = "● RUNNING" if http_status in (200, 503) else f"● ERROR (HTTP {http_status})"
    database = "● OK" if http_status == 200 and db == "OK" else "● DOWN"
    return service, database


_BAD = re.compile(r"STOPPED|DOWN|CRITICAL|GAGAL|FAILED|BELUM|ERROR|tidak diketahui")
_WARN = re.compile(r"WARNING|PERINGATAN|UNTESTED|DEGRADED|DARURAT")


def tone(text: str) -> str:
    """Warna pendamping teks status (warna bukan satu-satunya penanda)."""
    if _BAD.search(text):
        return "#b3261e"
    if _WARN.search(text):
        return "#8a5a00"
    return "#0a6b2e" if text.startswith("●") else ""


def api_python(api_dir: Path, platform: str = sys.platform) -> Path:
    if platform == "win32":
        return api_dir / ".venv" / "Scripts" / "python.exe"
    return api_dir / ".venv" / "bin" / "python"


_SECRET_FIELD = re.compile(
    r'(?i)("?(?:password|passphrase|token|csrf[_-]?token|cookie|authorization|secret)"?\s*[:=]\s*)'
    r'("[^"]*"|\S+)'
)
_LONG_TOKEN = re.compile(r"[A-Za-z0-9_\-+/=]{32,}")
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_NISN = re.compile(r"\b\d{10}\b")
_DB_PASSWORD = re.compile(r"(://[^:/@\s]+:)[^@\s]+@")


def redact(line: str) -> str:
    """Samarkan rahasia & data siswa sebelum log ditampilkan/diekspor untuk dukungan teknis."""
    line = _DB_PASSWORD.sub(r"\1***@", line)
    line = _SECRET_FIELD.sub(r'\1"***"', line)
    line = _LONG_TOKEN.sub(lambda m: m[0] if _UUID.fullmatch(m[0]) else "[REDACTED]", line)
    line = _EMAIL.sub("[email]", line)
    return _NISN.sub("[nisn]", line)


def can_stop(active_attempts: int | None, reason: str) -> tuple[bool, str]:
    """Stop/restart diblokir selama ada ujian berjalan, kecuali alasan darurat ≥ 10 karakter."""
    if active_attempts is None:
        return True, "Jumlah ujian berjalan tidak diketahui (database mati)."
    if active_attempts == 0:
        return True, ""
    if len(reason.strip()) >= 10:
        return True, f"DARURAT: {active_attempts} ujian berjalan akan terganggu."
    return False, f"{active_attempts} ujian sedang berjalan. Isi alasan darurat (min. 10 karakter)."


def service_commands(action: str, platform: str = sys.platform) -> list[list[str]] | None:
    """Perintah OS untuk START/STOP/RESTART service API. None = OS tidak didukung."""
    if platform == "darwin":
        script = {
            "START": f"launchctl bootstrap system {MAC_PLIST}",
            "STOP": f"launchctl bootout system/{MAC_LABEL}",
            "RESTART": f"launchctl kickstart -k system/{MAC_LABEL}",
        }[action]
        osa = f'do shell script "{script}" with administrator privileges'
        return [["osascript", "-e", osa]]
    if platform == "win32":
        if action == "RESTART":
            return [["sc", "stop", WIN_SERVICE], ["sc", "start", WIN_SERVICE]]
        return [["sc", action.lower(), WIN_SERVICE]]
    return None


def fmt_bytes(n: int | None) -> str:
    if not n:
        return "-"
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return "-"


def fmt_time(value: str | None) -> str:
    if not value:
        return "-"
    try:
        return datetime.fromisoformat(value).astimezone().strftime("%d-%m-%Y %H:%M")
    except ValueError:
        return value


def backup_label(status: dict[str, Any]) -> str:
    """Ringkasan backup untuk halaman utama. Gagal/belum ada selalu ditandai jelas."""
    last = status.get("last_backup")
    ok_at = status.get("last_verified_backup_at")
    if not status.get("backup_passphrase_set"):
        return "● BELUM SIAP: kata sandi enkripsi backup belum diatur"
    if last and last.get("status") == "FAILED":
        return f"● GAGAL {fmt_time(last.get('created_at'))}: {last.get('error') or '-'}"
    if last and last.get("status") in ("QUEUED", "RUNNING"):
        return "● sedang berjalan…"
    if not ok_at:
        return "● BELUM ADA backup terverifikasi"
    return f"● OK, terverifikasi {fmt_time(ok_at)}"


def env_quote(value: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_./:@%+,=\[\]\"-]*", value):
        return value
    if "'" not in value:
        return f"'{value}'"
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def merge_env(existing: str, updates: dict[str, str]) -> str:
    """Ganti/tambah kunci di isi .env, baris lain dipertahankan."""
    lines = [ln for ln in existing.splitlines() if ln.split("=", 1)[0] not in updates]
    lines += [f"{k}={env_quote(v)}" for k, v in updates.items()]
    return "\n".join(lines) + "\n"


# ---- Pemanggil CLI ---------------------------------------------------------------------

Done = Callable[[Any, str | None], None]


class Cli:
    """Jalankan `python -m app.cli --json ...` tanpa membekukan jendela."""

    def __init__(self) -> None:
        self._running: set[QProcess] = set()

    def run(self, args: list[str], done: Done, stdin: str | None = None) -> None:
        self.raw([str(api_python(API_DIR)), "-m", "app.cli", "--json", *args], done, stdin, True)

    def raw(self, cmd: list[str], done: Done, stdin: str | None = None, js: bool = False) -> None:
        proc = QProcess()  # tanpa parent: tetap hidup sampai selesai walau jendela ditutup
        proc.setWorkingDirectory(str(API_DIR))
        self._running.add(proc)

        def finished(code: int, _status: QProcess.ExitStatus) -> None:
            if proc not in self._running:
                return
            try:
                out = bytes(proc.readAllStandardOutput().data()).decode(errors="replace")
                err = bytes(proc.readAllStandardError().data()).decode(errors="replace")
            except RuntimeError:  # aplikasi sedang ditutup
                return
            self._running.discard(proc)
            proc.deleteLater()
            if js:
                try:
                    data = json.loads(out.strip().splitlines()[-1]) if out.strip() else None
                except ValueError:
                    data = None
                if isinstance(data, dict) and "error" in data:
                    done(None, str(data["error"]))
                elif code != 0 or data is None:
                    done(None, (err or out).strip()[-800:] or f"Gagal (kode {code}).")
                else:
                    done(data, None)
            else:
                done(out, None if code == 0 else (err or out).strip()[-800:] or f"kode {code}")

        def failed(_: QProcess.ProcessError) -> None:
            try:
                stopped = proc.state() == QProcess.ProcessState.NotRunning
            except RuntimeError:  # aplikasi sedang ditutup
                return
            if proc in self._running and stopped:
                self._running.discard(proc)
                proc.deleteLater()
                done(None, f"Tidak bisa menjalankan {cmd[0]}. Periksa LOCALCBT_API_DIR.")

        proc.finished.connect(finished)
        proc.errorOccurred.connect(failed)
        proc.start(cmd[0], cmd[1:])
        if stdin is not None:
            proc.write(stdin.encode())
            proc.closeWriteChannel()

    def busy(self) -> bool:
        return bool(self._running)


def table(headers: list[str]) -> QTableWidget:
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    t.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    t.horizontalHeader().setSectionResizeMode(len(headers) - 1, QHeaderView.ResizeMode.Stretch)
    t.verticalHeader().setVisible(False)
    return t


def fill(t: QTableWidget, rows: list[list[str]]) -> None:
    t.setRowCount(len(rows))
    for r, row in enumerate(rows):
        for c, value in enumerate(row):
            t.setItem(r, c, QTableWidgetItem(value))
    t.resizeColumnsToContents()


def ask_text(parent: QWidget, title: str, fields: list[tuple[str, QWidget]], note: str) -> bool:
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    lay = QVBoxLayout(dlg)
    if note:
        lbl = QLabel(note)
        lbl.setWordWrap(True)
        lay.addWidget(lbl)
    form = QFormLayout()
    for label, widget in fields:
        form.addRow(label, widget)
    lay.addLayout(form)
    buttons = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
    )
    buttons.accepted.connect(dlg.accept)
    buttons.rejected.connect(dlg.reject)
    lay.addWidget(buttons)
    return dlg.exec() == QDialog.DialogCode.Accepted


# ---- Jendela -----------------------------------------------------------------------


class Window(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("LocalCBT Control Center")
        self.cli = Cli()
        self.status: dict[str, Any] = {}
        self.backups: list[dict[str, Any]] = []
        tabs = QTabWidget()
        tabs.addTab(self._overview(), "Ringkasan")
        tabs.addTab(self._network(), "Jaringan")
        tabs.addTab(self._backup(), "Backup && Restore")
        tabs.addTab(self._logs(), "Log")
        tabs.addTab(self._service(), "Layanan")
        self.setCentralWidget(tabs)

        self.net = QNetworkAccessManager(self)
        self.net.finished.connect(self.on_health)
        QTimer(self, interval=POLL_MS, timeout=self.poll).start()
        QTimer(self, interval=STATUS_MS, timeout=self.refresh).start()
        psutil.cpu_percent()
        self.poll()
        self.refresh()

    def set_label(self, key: str, text: str) -> None:
        self.labels[key].setText(text)
        self.labels[key].setStyleSheet(f"color: {tone(text)}" if tone(text) else "")

    def note(self, msg: str) -> None:
        self.statusBar().showMessage(msg, 15000)

    def error(self, title: str, msg: str) -> None:
        QMessageBox.warning(self, title, msg)

    # Ringkasan
    def _overview(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        self.labels: dict[str, QLabel] = {}
        for key, label in [
            ("service", "Service"),
            ("database", "Database"),
            ("disk", "Disk"),
            ("cpu", "CPU / RAM"),
            ("active", "Ujian berjalan"),
            ("backup", "Backup terakhir"),
            ("backup_disk", "Lokasi backup"),
            ("network", "Jaringan ujian"),
            ("rev", "Versi skema"),
        ]:
            self.labels[key] = QLabel("…")
            self.labels[key].setWordWrap(True)
            form.addRow(label, self.labels[key])
        form.addRow("Server endpoint", QLabel(API_URL))
        return w

    def poll(self) -> None:
        req = QNetworkRequest(QUrl(f"{API_URL}/api/v1/healthz"))
        req.setTransferTimeout(2000)
        self.net.get(req)
        mem = psutil.virtual_memory()
        self.set_label("cpu", f"CPU {psutil.cpu_percent():.0f}% · RAM {mem.percent:.0f}%")

    def on_health(self, reply: QNetworkReply) -> None:
        status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        service, database = describe(status, bytes(reply.readAll().data()))
        self.set_label("service", service)
        self.set_label("database", database)
        reply.deleteLater()

    def refresh(self) -> None:
        self.cli.run(["status"], self.on_status)
        self.cli.run(["backups"], self.on_backups)

    def on_status(self, data: Any, err: str | None) -> None:
        if err:
            self.set_label("backup", f"● tidak diketahui ({err[:120]})")
            return
        self.status = data
        free = data.get("disk_free_ratio")
        pct = "" if free is None else f" (kosong {free * 100:.0f}%)"
        self.set_label("disk", f"● {data['disk_status']}{pct}")
        active = data.get("active_attempts")
        self.set_label("active", "tidak diketahui" if active is None else str(active))
        self.set_label("backup", backup_label(data))
        self.set_label(
            "backup_disk",
            "● PERINGATAN: satu disk dengan data utama. Arahkan ke drive lain."
            if data.get("backup_same_disk_as_media")
            else "● terpisah dari data utama",
        )
        net = data.get("network") or {}
        probe = net.get("probe") or {}
        self.set_label("network", f"● {probe.get('status', '?')}: {probe.get('detail', '')}")
        self.set_label("rev", str(data.get("alembic_rev", "-")))
        url = net.get("probe_url") or "PUBLIC_HOST belum diatur"
        self.probe_label.setText(
            f"Probe dari perangkat siswa: {probe.get('status', '?')} — {probe.get('detail', '')}\n"
            f"Buka di HP/laptop siswa (SSID ujian): {url}"
        )
        s = data.get("settings") or {}
        hour, daily = s.get("backup_hour", "?"), s.get("backup_keep_daily", "?")
        self.retention_label.setText(
            f"Backup harian jam {hour}:00 · simpan {daily} backup harian · "
            f"backup manual {s.get('backup_keep_manual_days', '?')} hari"
        )

    # Jaringan
    def _network(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        row = QHBoxLayout()
        run = QPushButton("Jalankan preflight")
        run.clicked.connect(self.run_preflight)
        attest = QPushButton("Catat pemeriksaan manual…")
        attest.clicked.connect(self.attest)
        row.addWidget(run)
        row.addWidget(attest)
        row.addStretch()
        lay.addLayout(row)
        self.preflight_table = table(["Pemeriksaan", "Status", "Detail"])
        lay.addWidget(self.preflight_table)
        self.probe_label = QLabel("…")
        self.probe_label.setWordWrap(True)
        self.probe_label.setTextInteractionFlags(self.probe_label.textInteractionFlags())
        lay.addWidget(self.probe_label)
        hint = QLabel(
            "Probe hanya membuktikan HTTPS ke internet tertutup dari browser. Port lain, IPv6, "
            "isolasi jaringan staf dan halaman admin router tetap harus diperiksa manual dari "
            "perangkat siswa, lalu dicatat lewat tombol di atas."
        )
        hint.setWordWrap(True)
        lay.addWidget(hint)
        return w

    def run_preflight(self) -> None:
        self.note("Menjalankan preflight…")

        def done(data: Any, err: str | None) -> None:
            if err:
                return self.error("Preflight gagal", err)
            fill(self.preflight_table, [[c["id"], c["status"], c["detail"]] for c in data])
            self.note("Preflight selesai dan dicatat.")

        self.cli.run(["preflight"], done)

    def attest(self) -> None:
        def got_items(items: Any, err: str | None) -> None:
            if err:
                return self.error("Gagal", err)
            boxes = {k: QCheckBox(v) for k, v in items.items()}
            by, note = QLineEdit(), QLineEdit()
            fields: list[tuple[str, QWidget]] = [("", b) for b in boxes.values()]
            fields += [("Diperiksa oleh", by), ("Catatan", note)]
            if not ask_text(
                self,
                "Pemeriksaan jaringan manual",
                fields,
                "Centang hanya yang benar-benar sudah diuji dari perangkat di SSID ujian hari ini.",
            ):
                return
            checked = ",".join(k for k, b in boxes.items() if b.isChecked())
            self.cli.run(
                ["attest-network", "--by", by.text(), "--items", checked, "--note", note.text()],
                lambda _d, e: self.error("Gagal", e) if e else self.note("Pemeriksaan dicatat."),
            )

        self.cli.run(["attest-items"], got_items)

    # Backup
    def _backup(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        row = QHBoxLayout()
        for text, slot in [
            ("Backup sekarang", self.backup_now),
            ("Uji restore", self.rehearse),
            ("Restore…", self.restore),
            ("Atur masa simpan…", self.retention),
        ]:
            b = QPushButton(text)
            b.clicked.connect(slot)
            row.addWidget(b)
        row.addStretch()
        lay.addLayout(row)
        self.retention_label = QLabel("…")
        lay.addWidget(self.retention_label)
        self.backup_table = table(
            ["Waktu", "Jenis", "Status", "Ukuran", "Uji restore", "Keterangan"]
        )
        lay.addWidget(self.backup_table)
        lay.addWidget(
            QLabel(
                "Backup dienkripsi. Tanpa kata sandi backup, backup tidak bisa dibuka: simpan "
                "salinannya di amplop tertutup / brankas sekolah."
            )
        )
        return w

    def on_backups(self, data: Any, err: str | None) -> None:
        if err:
            return
        self.backups = data
        fill(
            self.backup_table,
            [
                [
                    fmt_time(j["created_at"]),
                    j["trigger"],
                    "dihapus (masa simpan)" if j["pruned_at"] else j["status"],
                    fmt_bytes(j["size_bytes"]),
                    fmt_time(j["restore_verified_at"]),
                    j["error"] or "",
                ]
                for j in data
            ],
        )

    def selected_backup(self) -> dict[str, Any] | None:
        rows = self.backup_table.selectionModel().selectedRows()
        job = self.backups[rows[0].row()] if rows else None
        if not job or job["status"] != "VERIFIED" or job["pruned_at"]:
            self.error("Pilih backup", "Pilih satu backup berstatus VERIFIED di tabel.")
            return None
        return job

    def backup_now(self) -> None:
        self.note("Backup berjalan… (bisa beberapa menit)")

        def done(_: Any, err: str | None) -> None:
            if err:
                self.error("Backup GAGAL", err)
            else:
                self.note("Backup selesai dan terverifikasi.")
            self.refresh()

        self.cli.run(["backup"], done)

    def rehearse(self) -> None:
        job = self.selected_backup()
        if not job:
            return
        self.note("Uji restore berjalan ke database sementara…")

        def done(data: Any, err: str | None) -> None:
            if err:
                self.error("Uji restore GAGAL", err)
            else:
                QMessageBox.information(
                    self, "Uji restore berhasil", f"Data cocok dengan backup: {data['counts']}"
                )
            self.refresh()

        self.cli.run(["rehearse", job["id"]], done)

    def restore(self) -> None:
        job = self.selected_backup()
        if not job:
            return
        name = QLineEdit(f"localcbt_restore_{datetime.now():%Y%m%d_%H%M}")
        switch = QCheckBox("Alihkan service ke database hasil restore lalu restart")
        switch.setChecked(True)
        reason = QLineEdit()
        confirm = QLineEdit()
        ok = ask_text(
            self,
            "Restore backup",
            [
                ("Database baru", name),
                ("", switch),
                ("Alasan insiden (wajib bila ada ujian berjalan)", reason),
                ("Ketik PULIHKAN", confirm),
            ],
            f"Backup {fmt_time(job['created_at'])} dipulihkan ke database BARU. Database lama "
            "tidak dihapus, jadi bisa kembali bila perlu. Setelah dialihkan, data sejak waktu "
            "backup tidak terlihat di aplikasi. Lakukan di luar jam ujian.",
        )
        if not ok or confirm.text().strip() != "PULIHKAN":
            return
        args = ["restore", job["id"], "--into", name.text().strip()]
        if switch.isChecked():
            args.append("--switch")
        if reason.text().strip():
            args += ["--incident-reason", reason.text().strip()]
        self.note("Restore berjalan…")

        def done(data: Any, err: str | None) -> None:
            if err:
                return self.error("Restore GAGAL", err)
            msg = f"Restore ke {data['database']} berhasil dan dicocokkan: {data['counts']}"
            QMessageBox.information(self, "Restore selesai", msg)
            if data.get("switched"):
                self.run_service("RESTART", reason.text(), skip_audit=True)

        self.cli.run(args, done)

    def retention(self) -> None:
        s = (self.status or {}).get("settings") or {}
        hour, daily, manual = QSpinBox(), QSpinBox(), QSpinBox()
        hour.setRange(0, 23)
        daily.setRange(1, 365)
        manual.setRange(1, 3650)
        hour.setValue(s.get("backup_hour", 2))
        daily.setValue(s.get("backup_keep_daily", 14))
        manual.setValue(s.get("backup_keep_manual_days", 90))
        reason = QLineEdit()
        if not ask_text(
            self,
            "Masa simpan backup",
            [
                ("Jam backup harian", hour),
                ("Jumlah backup harian disimpan", daily),
                ("Backup manual disimpan (hari)", manual),
                ("Alasan / dasar kebijakan", reason),
            ],
            "Backup di luar masa simpan dihapus otomatis. Backup terbaru tidak pernah dihapus.",
        ):
            return
        args = [
            "set-retention",
            f"--hour={hour.value()}",
            f"--keep-daily={daily.value()}",
            f"--keep-manual-days={manual.value()}",
            f"--reason={reason.text()}",
        ]

        def done(_: Any, err: str | None) -> None:
            if err:
                return self.error("Gagal menyimpan", err)
            self.note("Masa simpan disimpan.")
            self.refresh()

        self.cli.run(args, done)

    # Log
    def _logs(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        row = QHBoxLayout()
        self.log_filter = QLineEdit(placeholderText="Saring teks…")
        self.only_errors = QCheckBox("Hanya error")
        reload = QPushButton("Muat ulang")
        export = QPushButton("Ekspor…")
        for x in (self.log_filter, self.only_errors, reload, export):
            row.addWidget(x)
        lay.addLayout(row)
        self.log_view = QPlainTextEdit(readOnly=True)
        lay.addWidget(self.log_view)
        lay.addWidget(QLabel(f"Berkas: {LOG_FILE} · kata sandi, token, email, NISN disamarkan."))
        reload.clicked.connect(self.load_logs)
        self.log_filter.textChanged.connect(self.load_logs)
        self.only_errors.toggled.connect(self.load_logs)
        export.clicked.connect(self.export_logs)
        return w

    def log_lines(self) -> list[str]:
        try:
            raw = LOG_FILE.read_text(errors="replace").splitlines()[-3000:]
        except OSError as e:
            return [f"Log tidak bisa dibaca: {e}"]
        needle = self.log_filter.text().lower()
        lines = [redact(ln) for ln in raw]
        if self.only_errors.isChecked():
            lines = [ln for ln in lines if '"level": "ERROR"' in ln or "Traceback" in ln]
        return [ln for ln in lines if needle in ln.lower()]

    def load_logs(self) -> None:
        self.log_view.setPlainText("\n".join(self.log_lines()))
        self.log_view.moveCursor(self.log_view.textCursor().MoveOperation.End)

    def export_logs(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Ekspor log", f"localcbt-log-{datetime.now():%Y%m%d-%H%M}.txt"
        )
        if path:
            Path(path).write_text("\n".join(self.log_lines()) + "\n")
            self.note(f"Log tersimpan: {path}")

    # Layanan
    def _service(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        row = QHBoxLayout()
        for action, text in [("START", "Start"), ("STOP", "Stop"), ("RESTART", "Restart")]:
            b = QPushButton(text)
            b.clicked.connect(
                lambda _=False, a=action: self.run_service(a, self.stop_reason.text())
            )
            row.addWidget(b)
        row.addStretch()
        lay.addLayout(row)
        self.stop_reason = QLineEdit(placeholderText="Alasan darurat (wajib bila ujian berjalan)")
        lay.addWidget(self.stop_reason)
        setup = QPushButton("Setup awal…")
        setup.clicked.connect(lambda: SetupWizard(self).exec())
        lay.addWidget(setup)
        lay.addWidget(
            QLabel(
                "Menutup Control Center tidak menghentikan ujian. Stop/Restart dikunci selama ada "
                "ujian berjalan; alasan darurat dicatat di audit."
            )
        )
        lay.addStretch()
        return w

    def run_service(self, action: str, reason: str, skip_audit: bool = False) -> None:
        commands = service_commands(action)
        if commands is None:
            return self.error("Tidak didukung", "Kendali service hanya untuk macOS dan Windows.")
        if action in ("STOP", "RESTART") and not skip_audit:
            allowed, msg = can_stop(self.status.get("active_attempts"), reason)
            if not allowed:
                return self.error("Ditolak", msg)

        def run_next(i: int) -> None:
            if i == len(commands):
                self.note(f"Service: {action} selesai.")
                return QTimer.singleShot(2000, self.refresh)

            def done(_: Any, err: str | None) -> None:
                if err:
                    return self.error(f"{action} gagal", err)
                run_next(i + 1)

            self.cli.raw(commands[i], done)

        if skip_audit:
            return run_next(0)

        def audited(_: Any, err: str | None) -> None:
            if err:
                return self.error("Ditolak", err)
            run_next(0)

        self.cli.run(["service-action", action, "--reason", reason], audited)


class SetupWizard(QWizard):
    """Setup awal (FR-ADM-03): konfigurasi, migrasi database, admin pertama."""

    def __init__(self, win: Window) -> None:
        super().__init__(win)
        self.win = win
        self.setWindowTitle("Setup awal LocalCBT")
        self.addPage(self._config_page())
        self.addPage(self._migrate_page())
        self.addPage(self._admin_page())
        self.addPage(self._service_page())

    def _config_page(self) -> QWizardPage:
        page = ConfigPage()
        page.setTitle("1. Konfigurasi server")
        return page

    def _migrate_page(self) -> QWizardPage:
        page = QWizardPage()
        page.setTitle("2. Siapkan database")
        lay = QVBoxLayout(page)
        out = QPlainTextEdit(readOnly=True)
        btn = QPushButton("Jalankan migrasi database")
        page.done = False  # type: ignore[attr-defined]
        page.isComplete = lambda: page.done  # type: ignore[method-assign]

        def run() -> None:
            out.setPlainText("Menjalankan…")

            def done(text: Any, err: str | None) -> None:
                out.setPlainText(err or (text or "Selesai."))
                page.done = err is None  # type: ignore[attr-defined]
                page.completeChanged.emit()

            self.win.cli.raw([str(api_python(API_DIR)), "-m", "alembic", "upgrade", "head"], done)

        btn.clicked.connect(run)
        lay.addWidget(btn)
        lay.addWidget(out)
        return page

    def _admin_page(self) -> QWizardPage:
        page = QWizardPage()
        page.setTitle("3. Admin pertama")
        form = QFormLayout(page)
        user, name = QLineEdit(), QLineEdit()
        pw1 = QLineEdit(echoMode=QLineEdit.EchoMode.Password)
        pw2 = QLineEdit(echoMode=QLineEdit.EchoMode.Password)
        result = QLabel("")
        btn = QPushButton("Buat admin")
        for label, w in [("Nama pengguna", user), ("Nama lengkap", name), ("Kata sandi", pw1),
                         ("Ulangi", pw2), ("", btn), ("", result)]:  # fmt: skip
            form.addRow(label, w)

        def create() -> None:
            if pw1.text() != pw2.text():
                return result.setText("Kata sandi tidak sama.")
            if len(pw1.text()) < 12:
                return result.setText("Kata sandi minimal 12 karakter.")
            self.win.cli.run(
                ["create-admin", user.text(), "--name", name.text(), "--password-stdin"],
                lambda _d, e: result.setText(e or "Admin dibuat."),
                stdin=pw1.text() + "\n",
            )

        btn.clicked.connect(create)
        return page

    def _service_page(self) -> QWizardPage:
        page = QWizardPage()
        page.setTitle("4. Pasang service")
        lay = QVBoxLayout(page)
        script = (
            r"powershell -ExecutionPolicy Bypass -File scripts\install-windows.ps1"
            if sys.platform == "win32"
            else "sudo scripts/install-macos.sh"
        )
        label = QLabel(
            "Jalankan sekali sebagai administrator dari folder LocalCBT untuk memasang service "
            f"API dan Caddy agar otomatis hidup saat komputer menyala:\n\n{script}\n\n"
            "Setelah itu buka tab Jaringan → Jalankan preflight, lalu tab Backup → Backup sekarang "
            "dan Uji restore."
        )
        label.setWordWrap(True)
        label.setTextInteractionFlags(label.textInteractionFlags())
        lay.addWidget(label)
        return page


class ConfigPage(QWizardPage):
    def __init__(self) -> None:
        super().__init__()
        form = QFormLayout(self)
        self.db = QLineEdit(
            placeholderText="postgresql+psycopg://localcbt:SANDI@127.0.0.1:5432/localcbt"
        )
        self.host = QLineEdit(placeholderText="cbt.sekolah.sch.id")
        self.backup_dir = QLineEdit(placeholderText="mis. E:\\LocalCBT-Backup atau /Volumes/Backup")
        self.subnets = QLineEdit(placeholderText="10.20.0.0/22")
        self.pw1 = QLineEdit(echoMode=QLineEdit.EchoMode.Password)
        self.pw2 = QLineEdit(echoMode=QLineEdit.EchoMode.Password)
        self.msg = QLabel("")
        self.msg.setWordWrap(True)
        for label, w in [
            ("URL database", self.db),
            ("Alamat portal (PUBLIC_HOST)", self.host),
            ("Folder backup", self.backup_dir),
            ("Subnet jaringan ujian (pisah koma)", self.subnets),
            ("Kata sandi backup (min. 12)", self.pw1),
            ("Ulangi kata sandi backup", self.pw2),
            ("", self.msg),
        ]:
            form.addRow(label, w)
        note = QLabel(
            "Kata sandi backup mengunci semua backup. Bila hilang, backup TIDAK bisa dibuka. "
            "Tulis dan simpan di amplop tertutup / brankas sekolah, terpisah dari server."
        )
        note.setWordWrap(True)
        form.addRow(note)

    def validatePage(self) -> bool:  # noqa: N802 — nama method Qt
        if not self.db.text().strip().startswith("postgresql"):
            self.msg.setText("Isi URL database PostgreSQL.")
            return False
        if len(self.pw1.text()) < 12 or self.pw1.text() != self.pw2.text():
            self.msg.setText("Kata sandi backup minimal 12 karakter dan harus sama.")
            return False
        subnets = [s.strip() for s in self.subnets.text().split(",") if s.strip()]
        host = self.host.text().strip()
        updates = {
            "LOCALCBT_DATABASE_URL": self.db.text().strip(),
            "LOCALCBT_BACKUP_PASSPHRASE": self.pw1.text(),
            "LOCALCBT_EXAM_SUBNETS": json.dumps(subnets),
        }
        if host:
            updates["LOCALCBT_PUBLIC_HOST"] = host
            updates["LOCALCBT_ALLOWED_ORIGINS"] = json.dumps([f"https://{host}"])
        if self.backup_dir.text().strip():
            updates["LOCALCBT_BACKUP_DIR"] = self.backup_dir.text().strip()
        env = API_DIR / ".env"
        try:
            existing = env.read_text() if env.exists() else ""
            env.write_text(merge_env(existing, updates))
            env.chmod(0o600)
        except OSError as e:
            self.msg.setText(f"Tidak bisa menulis {env}: {e}")
            return False
        return True


if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = Window()
    w.resize(860, 560)
    w.show()
    sys.exit(app.exec())
