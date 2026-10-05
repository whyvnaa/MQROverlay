"""Finds the game window (MonkeyQuest.exe) and its client area on screen. Windows only (Win32 via ctypes); on other
systems no window is found and the overlay runs as a normal map window."""

import ctypes
import os
import sys
from pathlib import Path

GAME_EXE = "monkeyquest.exe"

if sys.platform == "win32":
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    ENUM_PROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [ENUM_PROC, wintypes.LPARAM]
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindow.argtypes = [wintypes.HWND]
    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
    user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
    GWL_EXSTYLE, WS_EX_NOACTIVATE, SW_RESTORE = -20, 0x08000000, 9
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    # the taskbar and the desktop don't cover the game
    SHELL_CLASSES = {"Shell_TrayWnd", "Shell_SecondaryTrayWnd", "Progman", "WorkerW"}
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                    ctypes.POINTER(wintypes.DWORD)]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def _exe_name(pid: int) -> str:
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(len(buf))
        return Path(buf.value).name.lower() if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)) else ""
    finally:
        kernel32.CloseHandle(handle)


def bring_to_front(hwnd) -> bool:
    """Make hwnd the active window. Windows refuses that to a process that isn't in front; attaching to the input
    of the window in front is the usual way around it (only used to hand the keyboard back to the game)."""
    if sys.platform != "win32" or not hwnd:
        return False
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
    if user32.SetForegroundWindow(hwnd):
        return True
    fg_thread = user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), None)
    me = kernel32.GetCurrentThreadId()
    user32.AttachThreadInput(me, fg_thread, True)
    try:
        return bool(user32.SetForegroundWindow(hwnd))
    finally:
        user32.AttachThreadInput(me, fg_thread, False)


def set_no_activate(hwnd, on: bool) -> None:
    """A window with WS_EX_NOACTIVATE takes mouse clicks and the wheel without becoming the active window, so the
    game keeps its focus (and keeps running) under the full-screen map."""
    if sys.platform != "win32" or not hwnd:
        return
    style = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
    user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, style | WS_EX_NOACTIVATE if on else style & ~WS_EX_NOACTIVATE)


def client_rect(hwnd) -> tuple[int, int, int, int] | None:
    """The window's client area (x, y, width, height) in physical screen pixels."""
    if sys.platform != "win32" or not hwnd:
        return None
    r = wintypes.RECT()
    p = wintypes.POINT(0, 0)
    if not user32.GetClientRect(hwnd, ctypes.byref(r)) or not user32.ClientToScreen(hwnd, ctypes.byref(p)):
        return None
    return p.x, p.y, r.right - r.left, r.bottom - r.top


class GameWindow:
    """Caches the game's window handle; find() is cheap when the window still exists."""

    def __init__(self):
        self.hwnd = None
        self._names: dict[int, str] = {}

    def find(self):
        if sys.platform != "win32":
            return None
        if self.hwnd and user32.IsWindow(self.hwnd):
            return self.hwnd
        found = []

        def visit(hwnd, _):
            if user32.IsWindowVisible(hwnd):
                pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if pid.value not in self._names:
                    self._names[pid.value] = _exe_name(pid.value)
                if self._names[pid.value] == GAME_EXE:
                    r = client_rect(hwnd)  # 0 x 0 while minimized
                    found.append((bool(user32.IsIconic(hwnd)), r[2] * r[3] if r else 0, hwnd))
            return True

        user32.EnumWindows(ENUM_PROC(visit), 0)
        # the biggest open window; a minimized one still counts (it has no size until restored)
        self.hwnd = max(found, key=lambda f: (not f[0], f[1]))[2] if found else None
        return self.hwnd

    def rect(self) -> tuple[int, int, int, int] | None:
        """The game's client area, or None if there is no game window or it is minimized."""
        r = client_rect(self.find())
        return r if r and r[2] > 0 and r[3] > 0 else None

    def is_foreground(self) -> bool:
        return sys.platform == "win32" and bool(self.hwnd) and user32.GetForegroundWindow() == self.hwnd

    def is_visible(self) -> bool:
        """The game is on screen: not minimized, and the active window (if it isn't the game or this program) doesn't
        overlap it. Working on another monitor keeps the game visible."""
        game = self.rect()
        if sys.platform != "win32" or not game:
            return False
        fg = user32.GetForegroundWindow()
        if not fg or fg == self.hwnd:
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(fg, ctypes.byref(pid))
        if pid.value == os.getpid():
            return True
        cls = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(fg, cls, len(cls))
        if cls.value in SHELL_CLASSES:
            return True
        r = wintypes.RECT()
        if not user32.GetWindowRect(fg, ctypes.byref(r)):
            return True
        x, y, w, h = game
        return r.right <= x or r.left >= x + w or r.bottom <= y or r.top >= y + h

    def activate(self) -> None:
        """Give the keyboard back to the game (after the full map had it)."""
        if self.find():
            bring_to_front(self.hwnd)

    def is_minimized(self) -> bool:
        return sys.platform == "win32" and bool(self.hwnd) and bool(user32.IsIconic(self.hwnd))
