"""Live positions from the game's sync messages (SmartFox extension "ss"), as the client builds them
(decompiled client: SyncEvent.EncodeData, A2m.Server.Synchronizer.OnSFSExtensionResponse):

- client to server: %xt%<ext>%ss%<room>%<event>%
- server to client: %xt%ss%<room>%<event>%, or a batch "$<x>[<event>$<x>[<event>..." (times relative to the first)
- event: target id & type & time & values, each value typed by its first letter (i int, f float, l long, s string).
  The client writes numbers in the PC's locale, so a decimal comma can appear.

Your own position comes from what the client sends; other players from what the server sends. Your path: PhysicBasic
carries z (front path 0, back path 20, in between while crossing a bridge: AvatarSyncEventGenerator.TeleportToPosition),
PhysicTeleport an "on the back plane" flag."""

import threading
import time
from collections import deque

PHYSIC_BASIC, PHYSIC_TELEPORT = 2, 34  # SyncEvent.EventType


def sync_events(direction: str, msg: str):
    """The fields of each sync event in one SmartFox message."""
    if not msg.startswith("%xt%"):
        return
    parts = msg.split("%")
    if direction == "out":
        data = parts[5] if len(parts) > 5 and parts[3] == "ss" else None
    else:
        data = parts[4] if len(parts) > 4 and parts[2] == "ss" else None
    if not data:
        return
    if data.startswith("$"):
        for entry in data.split("$"):
            if "[" in entry:
                yield entry.split("[", 1)[1].split("&")
    else:
        yield data.split("&")


def number(field: str) -> float:
    if field[:1] not in ("f", "i", "l"):
        raise ValueError(field)
    return float(field[1:].replace(",", "."))


class LiveState:
    """Latest positions, written by the capture threads and read by the overlay's timer."""
    STALE = 30.0  # seconds without news before another player is dropped

    def __init__(self):
        self.lock = threading.Lock()
        self.me_id: str | None = None
        self.me: tuple[float, float, float] | None = None  # x, y, time
        self.me_plane: int | None = None  # 0 front path, 1 back path
        self.others: dict[str, tuple[float, float, float]] = {}
        self.messages = 0  # sync messages seen (to tell "no traffic" from "nothing parsed")
        # your own samples (x, y, on the ground, time), or None for a teleport (respawn, checkpoint): for learning
        # the moves you make (learn.py)
        self.track: deque = deque(maxlen=500)

    def clear(self) -> None:
        """New zone: the old positions mean nothing there."""
        with self.lock:
            self.me = None
            self.me_plane = None
            self.others.clear()
            self.track.append(None)

    def handle(self, direction: str, msg: str) -> None:
        now = time.monotonic()
        for f in sync_events(direction, msg):
            self.messages += 1
            try:
                target, kind = f[0], int(f[1])
                if kind == PHYSIC_BASIC and len(f) >= 7:
                    x, y = number(f[4]), number(f[5])  # f[3]: forced flag, f[7..9] velocity
                    plane = int(number(f[6]) > 10)  # z: 0 front, 20 back
                    ground = len(f) > 10 and f[10] == "i1"
                elif kind == PHYSIC_TELEPORT and len(f) >= 5:
                    x, y = number(f[3]), number(f[4])
                    plane = int(f[5] == "i1") if len(f) > 5 else None
                    ground = None
                else:
                    continue
            except (ValueError, IndexError):
                continue
            with self.lock:
                if direction == "out":
                    self.me_id = target
                if target == self.me_id:
                    self.me = (x, y, now)
                    if plane is not None:
                        self.me_plane = plane
                    self.track.append(None if ground is None else (x, y, ground, now))
                else:
                    self.others[target] = (x, y, now)

    def plane(self) -> int | None:
        """The path you are on (0 front, 1 back), or None before the first position."""
        with self.lock:
            return self.me_plane

    def take_track(self) -> list:
        """Your samples since the last call."""
        with self.lock:
            out = list(self.track)
            self.track.clear()
        return out

    def snapshot(self) -> tuple[tuple[float, float] | None, dict[str, tuple[float, float]]]:
        now = time.monotonic()
        with self.lock:
            for k in [k for k, v in self.others.items() if now - v[2] > self.STALE]:
                del self.others[k]
            me = self.me[:2] if self.me else None
            return me, {k: v[:2] for k, v in self.others.items()}
