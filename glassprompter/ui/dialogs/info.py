"""About and first-run welcome dialogs."""
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QVBoxLayout

from ... import APP_NAME, __version__, paths
from ... import platform as native
from ..theme import AQUA, DASH, VIOLET
from .common import BaseDialog, button, label


class AboutDialog(BaseDialog):
    def __init__(self, parent, check_updates=None, report=None):
        super().__init__(parent, "About")
        self.setFixedWidth(520)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(10)
        lay.addWidget(label(APP_NAME, "hero"))
        lay.addWidget(label("Version %s" % __version__, "muted"))
        lay.addWidget(label("A see-through teleprompter that sits under your webcam, so you can read your script "
                            "and keep eye contact on calls, demos and videos, with an AI assistant and a meeting "
                            "copilot that stay off the screen share.", None, True))
        lay.addWidget(label("Your scripts and settings stay on this computer:\n" + paths.data_dir(), "muted", True))
        lay.addWidget(label("This is a public beta. Found a bug or have an idea? Report a problem opens a "
                            "pre-filled GitHub issue with your app version and OS only.", "muted", True))
        row = QHBoxLayout()
        row.addWidget(button("Open data folder", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(paths.data_dir()))))
        row.addWidget(button("Open logs", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(paths.log_dir()))))
        if check_updates:
            row.addWidget(button("Check for updates", lambda: (check_updates(), self.accept())))
        row.addStretch(1)
        row2 = QHBoxLayout()
        if report:
            row2.addWidget(button("Report a problem", lambda: (report("bug"), self.accept())))
            row2.addWidget(button("Suggest a feature", lambda: (report("feature"), self.accept())))
        row2.addStretch(1)
        row2.addWidget(button("Close", self.accept, primary=True))
        lay.addSpacing(6)
        lay.addLayout(row)
        lay.addLayout(row2)


# ====================================================================== welcome
class WelcomeDialog(BaseDialog):
    def __init__(self, parent, drop_dir):
        super().__init__(parent, "Welcome")
        self.setFixedWidth(560)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(32, 28, 32, 28)
        lay.setSpacing(14)
        lay.addWidget(label("Welcome to Glass Prompter", "hero"))
        lay.addWidget(label("Read your script while looking straight at the camera.", "muted"))
        steps = [
            ("1", "It sits under your camera", "The glass bar at the top of your screen is the prompter. Drag it "
                                              "anywhere, or drag an edge to resize it."),
            ("2", "Add a script", "Press E for your script library, send one from your phone (P), or drop a file "
                                  "into the Glass Prompter folder in Documents."),
            ("3", "Read from any app", "%s+Space plays and pauses even while Zoom or Teams is in front. "
                                       "Turn on Voice Follow (V) and the script follows your voice." % native.MOD),
            ("4", "Get help in meetings", "Press K for the meeting copilot: it transcribes the call and %s+Enter "
                                          "tells you what to say. Notes and a follow-up email are written when "
                                          "you end. Sign in or add an AI key in Settings first." % native.MOD),
        ]
        accents = {"1": AQUA, "2": VIOLET, "3": AQUA, "4": VIOLET}
        for num, head, body in steps:
            card = QFrame()
            card.setProperty("role", "card")
            g = QGridLayout(card)
            g.setContentsMargins(16, 14, 16, 14)
            g.setHorizontalSpacing(14)
            n = label(num, "title")
            n.setFixedWidth(22)
            n.setStyleSheet("color: %s;" % accents[num])
            g.addWidget(n, 0, 0, 2, 1, Qt.AlignmentFlag.AlignTop)
            hl = label(head)
            hl.setStyleSheet("font-weight: 600;")
            g.addWidget(hl, 0, 1)
            g.addWidget(label(body, "muted", True), 1, 1)
            lay.addWidget(card)
        lay.addWidget(label("The badge in the corner always tells you the truth about what viewers can see. "
                            "Glass Prompter lives in the " + native.TRAY + " " + DASH +
                            " click its icon for everything else.", "muted", True))
        foot = QHBoxLayout()
        foot.addStretch(1)
        foot.addWidget(button("Get started", self.accept, primary=True))
        lay.addLayout(foot)
