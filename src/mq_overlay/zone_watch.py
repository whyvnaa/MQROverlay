"""Which zone the player is in, from the client's log: it writes "Starting level LV_SHD_dungeon01" on every zone
change. Read-only; the file is polled, so it works while the game holds it open."""

import re
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal

DEFAULT_LOG = Path.home() / "AppData" / "LocalLow" / "MQReborn Team" / "MQReborn" / "output_log.txt"
PATTERN = re.compile(rb"Starting level (LV_\w+)")


def last_zone(path: Path, chunk: int = 1 << 20) -> str | None:
    """The last zone named in the log, reading backwards from the end."""
    try:
        with path.open("rb") as fh:
            end = fh.seek(0, 2)
            tail = b""
            while end > 0:
                start = max(0, end - chunk)
                fh.seek(start)
                buf = fh.read(end - start) + tail
                found = PATTERN.findall(buf)
                if found:
                    return found[-1].decode()
                tail = buf[:64]  # a match cut by the chunk border
                end = start
    except OSError:
        pass
    return None


class ZoneWatcher(QObject):
    zoneChanged = Signal(str)

    def __init__(self, path: Path = DEFAULT_LOG, interval_ms: int = 500, parent=None):
        super().__init__(parent)
        self.path = path
        self.zone: str | None = None
        self.pos = 0
        self.rest = b""
        self.timer = QTimer(self)
        self.timer.setInterval(interval_ms)
        self.timer.timeout.connect(self.poll)

    def start(self) -> None:
        self.zone = last_zone(self.path)
        try:
            self.pos = self.path.stat().st_size
        except OSError:
            self.pos = 0
        if self.zone:
            self.zoneChanged.emit(self.zone)
        self.timer.start()

    def poll(self) -> None:
        try:
            size = self.path.stat().st_size
            if size < self.pos:  # the game started again and began a new log
                self.pos, self.rest = 0, b""
            if size == self.pos:
                return
            with self.path.open("rb") as fh:
                fh.seek(self.pos)
                new = fh.read(size - self.pos)
        except OSError:
            return
        self.pos += len(new)
        buf = self.rest + new
        cut = buf.rfind(b"\n") + 1
        self.rest = buf[cut:]
        for name in PATTERN.findall(buf[:cut]):
            zone = name.decode()
            if zone != self.zone:
                self.zone = zone
                self.zoneChanged.emit(zone)
