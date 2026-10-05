"""Start the overlay: uv run mq-overlay [--zone LV_CRS_Trail01] [--snapshot out.png]"""

import argparse
import signal
import sys
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QAction, QFontDatabase, QIcon
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from .data import DATA, GameData
from .game_window import GameWindow
from .capture import Sniffer
from .hotkeys import Hotkeys
from .live import LiveState
from .live_setup import LiveSetupDialog, problem
from .overlay import Overlay, config_file, load_settings
from .player import PlayerState
from .zone_watch import DEFAULT_LOG, ZoneWatcher


def main() -> int:
    parser = argparse.ArgumentParser(prog="mq-overlay", description="Map overlay for the Monkey Quest client.")
    parser.add_argument("--log", type=Path, default=DEFAULT_LOG, help="the client's output_log.txt")
    parser.add_argument("--zone", help="show this zone instead of following the log (e.g. LV_CRS_Trail01)")
    parser.add_argument("--full", action="store_true", help="open the full-screen map right away")
    parser.add_argument("--no-live", action="store_true", help="don't read the game's traffic for live positions")
    parser.add_argument("--snapshot", metavar="PNG", help="render the overlay into a PNG and exit (for testing)")
    parser.add_argument("--mode", choices=["full", "mini"], default="full", help="snapshot mode")
    parser.add_argument("--size", default="1400x900", help="snapshot size, WIDTHxHEIGHT")
    parser.add_argument("--search", default="", help="snapshot with this search")
    parser.add_argument("--build", type=int, metavar="LEVEL", help="snapshot of Build mode, planning for LEVEL")
    parser.add_argument("--own", default="", help="snapshot: items you own, comma-separated names")
    parser.add_argument("--tribe", default="", help="snapshot: the progression's badge tribe (Outlaw, Crossroads, ...)")
    parser.add_argument("--stage", type=int, metavar="LEVEL", help="snapshot: the level the progression shows")
    parser.add_argument("--effort", type=float, help="snapshot: the progression's effort limit per item (hours)")
    parser.add_argument("--switch", type=float, help="snapshot: the progression's cost of a change (0, 5, 15, 40)")
    parser.add_argument("--time", type=float, help="snapshot: the progression's weight of an hour (0, 1, 4, 15)")
    parser.add_argument("--unknown", action="store_true", help="snapshot: the progression takes items with no known way")
    parser.add_argument("--character", type=Path, help="snapshot: a saved character.json instead of --own")
    parser.add_argument("--prefer", choices=["melee", "ranged"], help="snapshot: the build style (default hybrid)")
    parser.add_argument("--exclude", default="", help="snapshot: items excluded in Build mode, comma-separated names")
    parser.add_argument("--card", default="", help="snapshot: open this item's card in Build mode")
    parser.add_argument("--shop", default="", metavar="TAB[:GROUP]",
                        help="snapshot: Build mode's shop list on this tab (a tribe or Armour[:Fire|blunt|any])")
    args = parser.parse_args()

    app = QApplication(sys.argv)
    app.setApplicationName("MQ Overlay")
    app.setOrganizationName("MonkeyQuest-Overlay")
    app.setQuitOnLastWindowClosed(False)
    QFontDatabase.addApplicationFont(str(DATA / "GROBOLD.ttf"))
    icon = QIcon(str(DATA / "icon.png"))
    app.setWindowIcon(icon)

    data = GameData()
    settings = load_settings(data)
    live = LiveState()
    # your character: the saved copy from last time, then the game's messages (snapshots: none)
    player = None if args.snapshot else PlayerState(config_file().parent / "character.json")

    def on_message(direction: str, msg: str) -> None:
        live.handle(direction, msg)
        player.handle(direction, msg)
    sniffer = None if args.snapshot or args.no_live else Sniffer(on_message)
    if sniffer:
        sniffer.start()
    status = "" if args.snapshot else "on" if sniffer and sniffer.running else problem(sniffer)
    if args.snapshot and args.own:  # a made-up inventory, for testing the Build tab
        from .builder import Builder
        items = Builder(DATA).bundle["items"].values()
        ids = {it["name"].lower(): it["id"] for it in items if it.get("name") and it.get("id")}
        player = PlayerState()
        player.inventory = {ids[n.strip().lower()]: 1 for n in args.own.split(",") if n.strip().lower() in ids}
        player.version = 1
    if args.snapshot and args.character:
        player = PlayerState(args.character)
        player.cache = None  # read it, never write it
    overlay = Overlay(data, GameWindow(), settings, live, status, player, persist=not args.snapshot)

    if args.snapshot:
        overlay.set_current_zone(args.zone or "LV_CRS_Trail01")
        overlay.search.setText(args.search)
        overlay.run_search()
        if args.build:
            overlay.view = "build"
            overlay.build_mode.level.setValue(args.build)
            if args.unknown:
                overlay.build_mode.opt.sources.add("unknown")
            if args.prefer:
                overlay.build_mode.opt.prefer = args.prefer
                overlay.build_mode.prefer_box.setCurrentIndex(overlay.build_mode.prefer_box.findData(args.prefer))
            if args.exclude:
                wanted = {n.strip().lower() for n in args.exclude.split(",")}
                items = overlay.build_mode.builder.bundle["items"]
                for prefab in [p for p, it in items.items() if (it.get("name") or "").lower() in wanted]:
                    overlay.build_mode.toggle_excluded(prefab)
            if args.shop:
                tab, _, group = args.shop.partition(":")
                overlay.build_mode.shop.set_tab(tab.capitalize())
                if group:
                    overlay.build_mode.shop.set_group(group if group in ("blunt", "any") else group.capitalize())
                overlay.build_mode.set_view("shop")
            else:
                overlay.build_mode.set_view("progress")
            overlay.build_mode.replan(wait=True)
            if args.tribe:
                overlay.build_mode.progress.set_tribe(args.tribe.capitalize())
            if args.effort is not None:
                overlay.build_mode.progress.set_effort(args.effort)
            if args.switch is not None:
                overlay.build_mode.progress.set_switch(args.switch)
            if args.time is not None:
                overlay.build_mode.progress.set_time(args.time)
            if args.stage:
                overlay.build_mode.progress.set_level(args.stage)
            if args.card:
                items = overlay.build_mode.builder.bundle["items"]
                prefab = next((p for p, it in items.items() if (it.get("name") or "").lower() == args.card.lower()), None)
                overlay.build_mode.open_card(prefab, 0)
        w, h = (int(v) for v in args.size.lower().split("x"))
        overlay.snapshot(args.snapshot, args.mode, (w, h))
        print(args.snapshot)
        return 0

    watcher = ZoneWatcher(args.log)
    watcher.zoneChanged.connect(overlay.set_current_zone)
    if args.zone:
        overlay.set_current_zone(args.zone)
    else:
        watcher.start()

    hotkeys = Hotkeys()
    app.installNativeEventFilter(hotkeys)
    overlay.hotkeys = hotkeys
    failed = [k for k, action in ((settings["hotkey_fullmap"], overlay.toggle_full),
                                  (settings["hotkey_minimap"], overlay.toggle_minimap))
              if not hotkeys.register(k, action)]

    tray = QSystemTrayIcon(icon)
    menu = QMenu()
    full = QAction(f"Full-screen map ({settings['hotkey_fullmap']})", menu, triggered=overlay.toggle_full)
    mini = QAction(f"Corner map on/off ({settings['hotkey_minimap']})", menu, triggered=overlay.toggle_minimap)
    quit_ = QAction("Quit", menu, triggered=app.quit)
    menu.addActions([full, mini])
    menu.addSeparator()

    def live_changed() -> None:
        on = bool(sniffer and sniffer.running)
        overlay.set_live_status("on" if on else problem(sniffer))
        overlay.store_settings()
        live_action.setText("Live position: " + ("on" if on else "set up…"))

    def setup_live() -> None:
        LiveSetupDialog(sniffer, settings, live_changed).exec()
    overlay.setup_live = setup_live
    live_action = QAction("Live position: " + ("on" if status == "on" else "set up…"), menu, triggered=setup_live)
    menu.addAction(live_action)
    menu.addSeparator()
    menu.addAction(quit_)
    tray.setContextMenu(menu)
    tray.activated.connect(lambda reason: overlay.toggle_full() if reason == QSystemTrayIcon.ActivationReason.Trigger else None)
    tray.setToolTip("MQ Overlay")
    tray.show()
    msg = f"{settings['hotkey_fullmap']}: full-screen map · {settings['hotkey_minimap']}: corner map on/off"
    msg += f"\nLive position: {status}"
    if failed:
        msg += f"\nHotkey taken by another program: {', '.join(failed)} (use the tray menu)"
    tray.showMessage("MQ Overlay is running", msg, icon, 4000)
    if args.full:
        overlay.set_mode("full")
    if sniffer and not sniffer.running and settings.get("live_prompt", True):  # Npcap missing: say how to get it
        QTimer.singleShot(800, setup_live)

    # Ctrl+C in the terminal: Python only sees it while it runs Python code, and inside a Qt callback it would be
    # swallowed. A handler that quits the app, plus a timer that gives Python a moment to notice, makes it stop.
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    wake = QTimer(interval=250)
    wake.timeout.connect(lambda: None)
    wake.start()

    code = app.exec()
    tray.hide()
    hotkeys.unregister_all()
    if sniffer:
        sniffer.stop()
    return code


if __name__ == "__main__":
    sys.exit(main())
