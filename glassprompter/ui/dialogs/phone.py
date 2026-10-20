"""Phone pairing dialog."""
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QPainter
from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QVBoxLayout, QWidget

from .common import BaseDialog, button, label

try:
    import qrcode
except Exception:            # optional
    qrcode = None


class QrWidget(QWidget):
    def __init__(self, data, size=220):
        super().__init__()
        self.setFixedSize(size, size)
        self.matrix = None
        if qrcode:
            q = qrcode.QRCode(border=2, error_correction=qrcode.constants.ERROR_CORRECT_M)
            q.add_data(data)
            q.make(fit=True)
            self.matrix = q.get_matrix()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#FFFFFF"))
        p.drawRoundedRect(QRectF(self.rect()), 14, 14)
        if not self.matrix:
            p.setPen(QColor("#333"))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "QR code unavailable")
            return
        n = len(self.matrix)
        cell = (self.width() - 8) / n
        off = (self.width() - cell * n) / 2
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        p.setBrush(QColor("#000000"))
        for y, row in enumerate(self.matrix):
            for x, v in enumerate(row):
                if v:
                    p.drawRect(QRectF(off + x * cell, off + y * cell, cell + 0.6, cell + 0.6))


class PhoneDialog(BaseDialog):
    def __init__(self, parent, controller):
        super().__init__(parent, "Phone remote")
        self.c = controller
        self.setFixedWidth(460)
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(28, 24, 28, 24)
        self.lay.setSpacing(12)
        self.build()

    def build(self):
        while self.lay.count():
            it = self.lay.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
            elif it.layout():
                _clear_layout(it.layout())
        lay, srv = self.lay, self.c.server
        lay.addWidget(label("Control it from your phone", "title"))
        if not self.c.cfg.s.remote_enabled:
            lay.addWidget(label("The phone remote is turned off.", "muted", True))
            lay.addWidget(button("Turn it on", lambda: (self.c.set_remote_enabled(True), self.build()), primary=True))
        elif not srv or not srv.running:
            err = srv.error if srv else "not started"
            lay.addWidget(label("The phone remote couldn't start (%s). Another app may be using port %d. "
                                "Change nothing and restart the app, or turn the remote off in Settings."
                                % (err, self.c.cfg.s.remote_port), "warn", True))
        else:
            url = srv.url()
            lay.addWidget(label("Scan with your phone's camera. Your phone must be on the same Wi-Fi as this "
                                "computer. From the phone you can play, see your screen, chat with the AI and run "
                                "the meeting copilot.", "muted", True))
            row = QHBoxLayout()
            row.addStretch(1)
            row.addWidget(QrWidget(url))
            row.addStretch(1)
            lay.addLayout(row)
            lay.addWidget(label("Or open this address and enter the PIN", "muted"))
            urow = QHBoxLayout()
            box = QLineEdit(srv.url(with_pin=False))
            box.setReadOnly(True)
            urow.addWidget(box, 1)
            copy = button("Copy", lambda: (QGuiApplication.clipboard().setText(srv.url(with_pin=False)),
                                           copy.setText("Copied")))
            urow.addWidget(copy)
            lay.addLayout(urow)
            prow = QHBoxLayout()
            prow.addWidget(label("PIN", "muted"))
            prow.addWidget(label(srv.pin, "pin"))
            prow.addStretch(1)
            prow.addWidget(button("New PIN", self._new_pin))
            lay.addLayout(prow)
            lay.addWidget(label("A new PIN disconnects every paired phone.", "muted"))
            if self.c.network_note:
                lay.addWidget(label(self.c.network_note, "warn", True))
        lay.addWidget(label("Different network? Save a .txt or .docx into your Glass Prompter drop folder "
                            "(Documents) from any device through OneDrive or iCloud Drive. It loads here "
                            "automatically.", "muted", True))
        foot = QHBoxLayout()
        foot.addStretch(1)
        foot.addWidget(button("Done", self.accept, primary=True))
        lay.addLayout(foot)

    def _new_pin(self):
        self.c.regenerate_pin()
        self.build()


def _clear_layout(layout):
    while layout.count():
        it = layout.takeAt(0)
        if it.widget():
            it.widget().deleteLater()
        elif it.layout():
            _clear_layout(it.layout())
