"""Starting the game with the overlay (the user 2026-10-06: one click for both). "Play MQReborn" is the patcher
(`MQReborn Patcher.exe`, which updates and starts the launcher, which starts the game); the overlay starts it when
the overlay starts, unless the game, the launcher or the patcher already runs. Where it is: the setting `game_exe`
if the user picked it, else the MQReborn installer's uninstall entry in the registry (InstallLocation), else the
default install folder. Windows only."""

import os
import subprocess
import sys
from pathlib import Path

GAME_PROCESSES = {"monkeyquest.exe", "mqreborn patcher.exe", "mqreborn launcher.exe"}
RELATIVE = [Path("patcher") / "MQReborn Patcher.exe", Path("launcher") / "MQReborn Launcher.exe"]
DEFAULT_ROOTS = [Path(r"C:\MQReborn"), Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "MQReborn",
                 Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "MQReborn"]


def install_roots() -> list[Path]:
    """Install folders of MQReborn from the registry's uninstall entries (per user and per machine)."""
    if sys.platform != "win32":
        return []
    import winreg
    roots = []
    for hive, key in ((winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
                      (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
                      (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall")):
        try:
            with winreg.OpenKey(hive, key) as k:
                for i in range(winreg.QueryInfoKey(k)[0]):
                    try:
                        with winreg.OpenKey(k, winreg.EnumKey(k, i)) as entry:
                            name = winreg.QueryValueEx(entry, "DisplayName")[0]
                            if "mqreborn" in str(name).lower():
                                roots.append(Path(winreg.QueryValueEx(entry, "InstallLocation")[0]))
                    except OSError:
                        continue
        except OSError:
            continue
    return roots


def find_game(settings: dict) -> Path | None:
    """The exe that starts the game: the user's choice, else the patcher (or launcher) of the installed MQReborn."""
    chosen = settings.get("game_exe")
    if chosen and Path(chosen).is_file():
        return Path(chosen)
    for root in install_roots() + DEFAULT_ROOTS:
        for rel in RELATIVE:
            if (root / rel).is_file():
                return root / rel
    return None


def game_running() -> bool:
    """Whether the game, its launcher or its patcher is running (a process snapshot, Windows only)."""
    if sys.platform != "win32":
        return False
    import ctypes
    from ctypes import wintypes

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                    ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)), ("th32ModuleID", wintypes.DWORD),
                    ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
                    ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_wchar * 260)]
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    snap = k32.CreateToolhelp32Snapshot(0x2, 0)  # TH32CS_SNAPPROCESS
    if snap == wintypes.HANDLE(-1).value or not snap:
        return False
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(entry)
        ok = k32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            if entry.szExeFile.lower() in GAME_PROCESSES:
                return True
            ok = k32.Process32NextW(snap, ctypes.byref(entry))
        return False
    finally:
        k32.CloseHandle(snap)


def start_game(exe: Path) -> bool:
    """Start the game's exe (detached, in its own folder); False if Windows refused."""
    try:
        flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        subprocess.Popen([str(exe)], cwd=str(exe.parent), creationflags=flags, close_fds=True)
        return True
    except OSError:
        return False
