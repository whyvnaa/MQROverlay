"""Setting up the live position: the overlay reads the game's own connection through Npcap (capture.py), which the
user installs once from npcap.com (its licence doesn't allow shipping it). This window says what is missing, opens
the download page, and tries again after the install without a restart. It opens at start when Npcap is missing
(unless the user ticked "don't show this again"), from the tray menu and from the map's header."""

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QCheckBox, QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from .capture import Sniffer

NPCAP_URL = "https://npcap.com/#download"
STYLE = """
QDialog { background: #1e3416; }
QLabel { color: #f3ead2; font-size: 13px; }
QLabel#title { font-family: GROBOLD; font-size: 20px; color: #ffd54f; }
QLabel#status { color: #ffab61; font-weight: bold; }
QLabel#status[ok="true"] { color: #a5d66b; }
QCheckBox { color: #a9bf8e; }
QPushButton { background: rgba(0, 0, 0, 90); color: #f3ead2; border: 1px solid #6b8f3a; border-radius: 8px; padding: 6px 14px; }
QPushButton:hover { border-color: #e8b130; }
QPushButton#main { background: #e8b130; color: #3b2a05; border-color: #e8b130; font-weight: bold; }
"""
STEPS = """<ol style="margin-left: -18px">
<li>Download Npcap from <a href="{url}" style="color:#ffd54f">npcap.com</a> (the free installer, about 1 MB) and run it.</li>
<li>Keep <b>"Install Npcap in WinPcap API-compatible Mode"</b> ticked.</li>
<li>Leave <b>"Restrict Npcap driver's access to Administrators only"</b> unticked, or the overlay can't read anything
without running as administrator.</li>
<li>Come back here and click <b>Check again</b>. No restart of the game or the overlay is needed.</li>
</ol>"""


def problem(sniffer: Sniffer | None) -> str:
    """Why the live position is off, in a sentence (empty when it is on)."""
    if sniffer is None:
        return "switched off (--no-live)"
    if sniffer.running:
        return ""
    if not sniffer.available:
        return "Npcap is not installed"
    if "adapter" in sniffer.error:
        return "Npcap is installed, but no network adapter could be opened (was it restricted to administrators?)"
    return sniffer.error or "not running"


class LiveSetupDialog(QDialog):
    def __init__(self, sniffer: Sniffer | None, settings: dict, on_change, parent=None):
        """on_change(): called after a successful start, so the overlay updates its status texts."""
        super().__init__(parent, Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Dialog)
        self.sniffer, self.settings, self.on_change = sniffer, settings, on_change
        self.setWindowTitle("MQ Overlay: live position")
        self.setStyleSheet(STYLE)
        self.setMinimumWidth(560)
        v = QVBoxLayout(self)
        v.setSpacing(10)
        v.addWidget(QLabel("Live position", objectName="title"))
        about = QLabel("With it the maps show where you are, the arrow points the way to your waypoint, and Build mode "
                       "knows your level, bananas, skill points, inventory and worn gear from the game's own messages. "
                       "The overlay only listens to the game's connection (port 9339), in memory: nothing is logged or saved.")
        about.setWordWrap(True)
        v.addWidget(about)
        self.status = QLabel(objectName="status")
        self.status.setWordWrap(True)
        v.addWidget(self.status)
        steps = QLabel(STEPS.format(url=NPCAP_URL))
        steps.setWordWrap(True)
        steps.setOpenExternalLinks(True)
        v.addWidget(steps)
        self.again = QCheckBox("Don't show this at start again (the tray menu and the map's header open it)")
        self.again.setChecked(not settings.get("live_prompt", True))
        self.again.toggled.connect(self.remember)
        v.addWidget(self.again)
        row = QHBoxLayout()
        get = QPushButton("Download Npcap", objectName="main")
        get.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(NPCAP_URL)))
        row.addWidget(get)
        self.check = QPushButton("Check again")
        self.check.clicked.connect(self.retry)
        row.addWidget(self.check)
        row.addStretch(1)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        row.addWidget(close)
        v.addLayout(row)
        self.show_status()

    def remember(self, dont: bool) -> None:
        self.settings["live_prompt"] = not dont
        self.on_change()

    def show_status(self) -> None:
        why = problem(self.sniffer)
        self.status.setProperty("ok", not why)
        self.status.setText("Live position is on. You can close this window." if not why else f"Live position is off: {why}.")
        self.status.style().polish(self.status)
        self.check.setVisible(bool(why) and self.sniffer is not None)

    def retry(self) -> None:
        if self.sniffer and not self.sniffer.running:
            self.sniffer.start()
            if self.sniffer.running:
                self.on_change()
        self.show_status()
