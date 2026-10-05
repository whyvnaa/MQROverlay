"""Starting the game with the overlay: where the game is found and what counts as running (no windows)."""

import sys
from pathlib import Path

from mq_overlay import game_launch
from mq_overlay.game_launch import find_game, game_running


def test_the_users_choice_wins_and_a_missing_file_is_ignored(tmp_path, monkeypatch):
    exe = tmp_path / "Play.exe"
    exe.write_bytes(b"")
    monkeypatch.setattr(game_launch, "install_roots", lambda: [])
    monkeypatch.setattr(game_launch, "DEFAULT_ROOTS", [])
    assert find_game({"game_exe": str(exe)}) == exe
    assert find_game({"game_exe": str(tmp_path / "gone.exe")}) is None
    root = tmp_path / "MQReborn"
    (root / "patcher").mkdir(parents=True)
    (root / "patcher" / "MQReborn Patcher.exe").write_bytes(b"")
    monkeypatch.setattr(game_launch, "install_roots", lambda: [root])
    assert find_game({}) == root / "patcher" / "MQReborn Patcher.exe"


def test_running_looks_at_the_process_names(monkeypatch):
    if sys.platform != "win32":
        assert game_running() is False
        return
    monkeypatch.setattr(game_launch, "GAME_PROCESSES", {"python.exe", "pytest.exe", Path(sys.executable).name.lower()})
    assert game_running() is True
    monkeypatch.setattr(game_launch, "GAME_PROCESSES", {"no-such-program-xyz.exe"})
    assert game_running() is False
