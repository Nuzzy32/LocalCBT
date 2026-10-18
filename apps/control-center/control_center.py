"""LocalCBT Control Center (M1 spike).

Hanya memantau service lewat HTTP. Backend berjalan sebagai service OS terpisah
(launchd / Windows Service), jadi menutup jendela ini tidak menghentikan ujian.
"""

import json
import os
import sys

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import QApplication, QFormLayout, QLabel, QWidget

API_URL = os.environ.get("LOCALCBT_API_URL", "http://127.0.0.1:8000")
POLL_MS = 3000


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


class Window(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("LocalCBT Control Center")
        self.service = QLabel("…")
        self.database = QLabel("…")
        layout = QFormLayout(self)
        layout.addRow("Server endpoint", QLabel(API_URL))
        layout.addRow("Service", self.service)
        layout.addRow("Database", self.database)

        self.net = QNetworkAccessManager(self)
        self.net.finished.connect(self.on_reply)
        timer = QTimer(self, interval=POLL_MS, timeout=self.poll)
        timer.start()
        self.poll()

    def poll(self) -> None:
        req = QNetworkRequest(QUrl(f"{API_URL}/api/v1/healthz"))
        req.setTransferTimeout(2000)
        self.net.get(req)

    def on_reply(self, reply: QNetworkReply) -> None:
        status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        service, database = describe(status, bytes(reply.readAll().data()))
        self.service.setText(service)
        self.database.setText(database)
        reply.deleteLater()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = Window()
    w.resize(420, 140)
    w.show()
    sys.exit(app.exec())
