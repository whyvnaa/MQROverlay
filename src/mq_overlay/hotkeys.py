"""Global hotkeys (work while the game has focus): Win32 RegisterHotKey, WM_HOTKEY read by a Qt native event filter.
Windows only; elsewhere register() returns False and the tray menu is the way to switch modes."""

import ctypes
import sys

from PySide6.QtCore import QAbstractNativeEventFilter, QTimer

MODS = {"alt": 0x1, "ctrl": 0x2, "shift": 0x4, "win": 0x8}
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312
KEYS = {f"f{i}": 0x6F + i for i in range(1, 25)} | {"tab": 0x09, "pause": 0x13, "home": 0x24, "end": 0x23,
                                                    "insert": 0x2D, "pageup": 0x21, "pagedown": 0x22, "esc": 0x1B}

if sys.platform == "win32":
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
    user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]


def parse(combo: str) -> tuple[int, int] | None:
    """"Ctrl+F9" -> (modifiers, virtual key); letters and digits work too ("Alt+M")."""
    *mods, key = [p.strip().lower() for p in combo.split("+")]
    if any(m not in MODS for m in mods):
        return None
    if key in KEYS:
        vk = KEYS[key]
    elif len(key) == 1 and key.isalnum():
        vk = ord(key.upper())
    else:
        return None
    return sum(MODS[m] for m in mods), vk


class Hotkeys(QAbstractNativeEventFilter):
    def __init__(self):
        super().__init__()
        self.actions = {}
        self.ids: dict[str, int] = {}
        self.next_id = 1

    def register(self, combo: str, action) -> bool:
        parsed = parse(combo)
        if sys.platform != "win32" or not parsed or combo in self.ids:
            return False
        hid = self.next_id
        if not user32.RegisterHotKey(None, hid, parsed[0] | MOD_NOREPEAT, parsed[1]):
            return False  # taken by another program
        self.next_id += 1
        self.actions[hid] = action
        self.ids[combo] = hid
        return True

    def unregister(self, combo: str) -> None:
        hid = self.ids.pop(combo, None)
        if hid is not None:
            user32.UnregisterHotKey(None, hid)
            self.actions.pop(hid, None)

    def unregister_all(self) -> None:
        if sys.platform == "win32":
            for hid in self.actions:
                user32.UnregisterHotKey(None, hid)
        self.actions.clear()
        self.ids.clear()

    def nativeEventFilter(self, event_type, message):
        if bytes(event_type) in (b"windows_generic_MSG", b"windows_dispatcher_MSG"):
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY and msg.wParam in self.actions:
                QTimer.singleShot(0, self.actions[msg.wParam])
                return True, 0
        return False, 0
