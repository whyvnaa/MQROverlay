"""The overlay window, two modes over the game window:

- corner map (F8 on/off): a small map below the game's banana counter, click-through, on screen whenever the game
  is visible (also while you work on another monitor);
- full-screen map (F7, Esc closes): covers the game, takes the mouse, shows the whole zone, with a menu to choose
  what the map shows, search across all zones and a zone picker.

A waypoint (click a marker or spot, in any zone) puts an arrow over the game that points the way (waypoints.py).
Without a running game the full-screen map covers the screen under the mouse."""

import json
import math
import sys
from pathlib import Path

from PySide6.QtCore import QEvent, QRect, QStandardPaths, Qt, QTimer
from PySide6.QtGui import QColor, QCursor, QGuiApplication, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (QAbstractSpinBox, QApplication, QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QPushButton, QScrollArea, QVBoxLayout, QWidget)

from .build_mode import BuildMode
from .builder import Builder
from .data import GameData
from .game_window import GameWindow, bring_to_front, move_window, set_no_activate, window_rect
from .live import LiveState
from .map_view import MapView
from .player import PlayerState
from .waypoints import ArrowWindow, ZoneGraph, short_name, target

DEFAULTS = {"hotkey_fullmap": "F7", "hotkey_minimap": "F8", "minimap": True,
            "waypoint": None,  # {"zone", "x", "y", "plane", "label"}: the arrow points the way there
            "minimap_corner": "top-right",  # top-left, top-right, bottom-left, bottom-right
            "minimap_width": 0.16,  # part of the game window's width
            "minimap_margin": 0,  # pixels between the corner map and the window edges
            "minimap_span": 60,  # world units across the corner map when it follows you (a game screen is 20)
            "tab": "Map",  # the menu's open tab: Map or Build
            "live_prompt": True,  # at start, explain how to set up the live position when Npcap is missing
            "start_game": True,  # start the game (its patcher) with the overlay, unless it already runs
            "game_exe": None,  # the exe that starts the game, when the user picked one (else: found by game_launch)
            "quit_with_game": True,  # quit when the game (after it was seen running) has closed
            "build": None}  # Build tab options: level, defence, weapons, sources
SETTINGS_VERSION = 2  # version 1 saved every value, so its placement values would hide newer defaults
KEEP_FROM_V1 = {"hotkey_fullmap", "hotkey_minimap", "minimap", "hidden"}

STYLE = """
#panel { background: rgba(10, 20, 8, 225); }
#panel[mini="true"] { background: rgba(16, 30, 14, 200); border: 1px solid rgba(232, 177, 48, 170); border-radius: 6px; }
QLabel { color: #f3ead2; }
#title { font-family: GROBOLD; font-size: 24px; color: #ffd54f; }
#panel[mini="true"] #title { font-size: 12px; }
#sub, #hint { color: #a9bf8e; }
#panel[mini="true"] #sub { font-size: 10px; }
#menu { background: rgba(30, 52, 22, 245); border: 2px solid #e8b130; border-radius: 12px; }
#section { font-family: GROBOLD; font-size: 14px; color: #ffd54f; padding-top: 6px; }
QLineEdit, QComboBox, QListWidget { background: rgba(0, 0, 0, 120); color: #f3ead2; border: 1px solid #6b8f3a;
    border-radius: 6px; padding: 4px 6px; selection-background-color: #6b8f3a; }
QComboBox QAbstractItemView { background: #1f3318; color: #f3ead2; selection-background-color: #6b8f3a; }
QPushButton { background: #6b8f3a; color: #fff6e0; border: none; border-radius: 6px; padding: 5px 10px; }
QPushButton:hover { background: #7fa548; }
QPushButton#toggle { background: rgba(0, 0, 0, 90); color: #8fa476; border: 1px solid #3d5a1c; text-align: left;
    padding: 4px 8px; }
QPushButton#toggle:checked { background: #3d5a1c; color: #fff6e0; border-color: #7fa548; }
QPushButton#path { background: rgba(0, 0, 0, 90); color: #8fa476; border: 1px solid #3d5a1c; border-radius: 0;
    padding: 5px 8px; }
QPushButton#path:checked { background: #e8b130; color: #3b2a05; border-color: #e8b130; font-weight: bold; }
QPushButton#path:hover { border-color: #e8b130; }
QPushButton#toggle:hover { border-color: #e8b130; }
QPushButton#small { background: rgba(0, 0, 0, 90); padding: 3px 8px; }
QPushButton#close { background: transparent; color: #f3ead2; font-size: 20px; padding: 0 8px; }
QPushButton#close:hover { color: #ffd54f; }
#route { color: #ffd54f; font-weight: bold; }
QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; border: none; }
QTabWidget::pane { border: none; }
QTabBar::tab { background: rgba(0, 0, 0, 90); color: #a9bf8e; border: 1px solid #3d5a1c; padding: 5px 16px;
    font-family: GROBOLD; font-size: 13px; }
QTabBar::tab:selected { background: #e8b130; color: #3b2a05; border-color: #e8b130; }
QTreeWidget { background: rgba(0, 0, 0, 120); color: #f3ead2; border: 1px solid #6b8f3a; border-radius: 6px; }
QTreeWidget::item { padding: 2px 0; }
QTreeWidget::item:hover, QListWidget::item:hover { background: rgba(232, 177, 48, 50); }
QTreeWidget::item:selected, QListWidget::item:selected { background: #6b8f3a; }
QSpinBox { background: rgba(0, 0, 0, 120); color: #f3ead2; border: 1px solid #6b8f3a; border-radius: 6px; padding: 2px 4px; }
QSlider::groove:horizontal { height: 6px; background: #3d5a1c; border-radius: 3px; }
QSlider::handle:horizontal { background: #e8b130; width: 14px; margin: -5px 0; border-radius: 7px; }
QToolTip { background: #1f3318; color: #f3ead2; border: 1px solid #e8b130; padding: 4px; }
"""


def config_file() -> Path:
    return Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppConfigLocation)) / "settings.json"


def load_settings(data: GameData) -> dict:
    """Defaults plus what the user changed. "_defaults" (not saved) lets save_settings write only the changes."""
    defaults = dict(DEFAULTS, hidden=[c["key"] for c in data.categories if not c["default"]])
    s = dict(defaults, _defaults=defaults)
    try:
        saved = json.loads(config_file().read_text(encoding="utf-8"))
        old = saved.get("version", 1) < SETTINGS_VERSION
        s.update({k: v for k, v in saved.items() if k in defaults and (not old or k in KEEP_FROM_V1)})
    except (OSError, ValueError):
        pass
    return s


def save_settings(s: dict) -> None:
    changed = {k: v for k, v in s.items() if not k.startswith("_") and v != s["_defaults"].get(k)}
    path = config_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        json.dump({"version": SETTINGS_VERSION, **changed}, fh, indent=2)
        fh.write("\n")


def to_logical(x: int, y: int, w: int, h: int) -> QRect:
    """Physical screen pixels (Win32) -> Qt's logical pixels. Qt keeps each screen's origin and scales from there."""
    for s in QGuiApplication.screens():
        g, dpr = s.geometry(), s.devicePixelRatio()
        native = QRect(g.x(), g.y(), round(g.width() * dpr), round(g.height() * dpr))
        if native.contains(x + w // 2, y + h // 2):
            return QRect(round(g.x() + (x - g.x()) / dpr), round(g.y() + (y - g.y()) / dpr), round(w / dpr), round(h / dpr))
    return QRect(x, y, w, h)


def place(widget: QWidget, rect: tuple[int, int, int, int]) -> None:
    """Put a top-level window at a rect in physical screen pixels. On Windows the window is moved with Windows' own
    call: Qt's conversion went wrong when the game switched the display to a 4:3 resolution (the screen's scale and
    the hidden window's scale disagreed, and the full map stuck out to the right)."""
    hwnd = int(widget.winId()) if sys.platform == "win32" else None
    now = window_rect(hwnd)
    if now:
        if now != tuple(rect):
            move_window(hwnd, *rect)
    elif widget.geometry() != (r := to_logical(*rect)):
        widget.setGeometry(r)


def section(text: str) -> QLabel:
    return QLabel(text, objectName="section")


class Overlay(QWidget):
    BASE_FLAGS = Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool

    def __init__(self, data: GameData, game: GameWindow, settings: dict, live: LiveState | None = None,
                 live_status: str = "", player: PlayerState | None = None, persist: bool = True):
        """live_status: "on", or why the live position is off (empty: don't mention it). persist: save setting
        changes (off for snapshots, so a test run never touches your settings)."""
        super().__init__(None, self.BASE_FLAGS)
        self.persist = persist
        self.data, self.game, self.settings = data, game, settings
        self.live, self.live_status = live, live_status
        self.setup_live = None  # set by __main__: opens the live position window (Npcap)
        self.waypoint: dict | None = settings.get("waypoint")
        self.graph: ZoneGraph | None = None  # which portals lead where (made when a waypoint first needs it)
        self.arrow = ArrowWindow()
        self.mode = "mini"
        self.current: str | None = None  # the zone the player is in (from the log)
        self.shown: str | None = None  # the zone on the map
        self.pinned = False  # the user picked another zone to look at
        self.path_choice: int | None = None  # path picked on the switch; None: the one you are on
        self.last_plane: int | None = None  # your path at the last live update (a change = you crossed a bridge)
        self.path_buttons: dict[int, QPushButton] = {}
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_AlwaysShowToolTips)  # marker tooltips while the game has focus
        self.hotkeys = None  # set by __main__ (Esc while the full-screen map is open)
        self.setWindowTitle("MQ Overlay")
        self.setStyleSheet(STYLE)

        self.panel = QFrame(objectName="panel")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.panel)
        panel = QVBoxLayout(self.panel)
        panel.setContentsMargins(8, 4, 8, 6)
        panel.setSpacing(6)

        # ---- mode bar (full-screen only): Map | Build, the way back to Build after a place click, close
        self.mode_bar = QWidget()
        bar = QHBoxLayout(self.mode_bar)
        bar.setContentsMargins(0, 0, 0, 0)
        bar.setSpacing(3)
        self.view_buttons = {}
        for key, text in (("map", "Map"), ("build", "Build")):
            b = QPushButton(text, objectName="path", checkable=True)
            b.setMinimumWidth(80)
            b.clicked.connect(lambda _=False, k=key: self.set_view(k))
            bar.addWidget(b)
            self.view_buttons[key] = b
        self.back_to_build = QPushButton("← Back to build", objectName="small")
        self.back_to_build.clicked.connect(lambda: self.set_view("build"))
        self.back_to_build.hide()
        bar.addSpacing(10)
        bar.addWidget(self.back_to_build)
        bar.addStretch(1)
        close = QPushButton("✕", objectName="close")
        close.setToolTip("Close (Esc)")
        close.clicked.connect(lambda: self.set_mode("mini"))
        bar.addWidget(close)
        panel.addWidget(self.mode_bar)
        self.map_page = QWidget()
        root = QHBoxLayout(self.map_page)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)
        panel.addWidget(self.map_page, 1)
        self.build_mode = BuildMode(Builder(data.root), player, settings, lambda _s: self.store_settings(),
                                    lambda: self.current)
        self.build_mode.placeClicked.connect(self.show_place)
        panel.addWidget(self.build_mode, 1)
        self.view = "build" if settings.get("tab") == "Build" else "map"

        # ---- menu (full-screen map only): find and filters
        self.menu = QFrame(objectName="menu")
        self.menu.setFixedWidth(290)
        menu = QVBoxLayout(self.menu)
        menu.setContentsMargins(12, 10, 12, 12)
        menu.setSpacing(6)
        menu.addWidget(section("Find"))
        self.search = QLineEdit(placeholderText="Enemy, item, NPC, portal… (Ctrl+F)")
        self.search.setClearButtonEnabled(True)
        # a click into any field you type in (search, level, ...) takes the keyboard: see eventFilter
        QApplication.instance().installEventFilter(self)
        self.search_timer = QTimer(self, singleShot=True, interval=200)
        self.search_timer.timeout.connect(self.run_search)
        self.search.textChanged.connect(self.search_timer.start)
        menu.addWidget(self.search)
        self.result_label = QLabel(objectName="sub")
        self.result_label.setWordWrap(True)
        menu.addWidget(self.result_label)
        self.results = QListWidget()
        self.results.setMaximumHeight(170)
        self.results.itemClicked.connect(lambda it: self.view_zone(it.data(Qt.ItemDataRole.UserRole), pinned=True))
        menu.addWidget(self.results)
        self.zone_box = QComboBox()
        self.zone_box.addItem("Look at another zone…", None)
        for meta in sorted(data.zones.values(), key=lambda z: (z["title"] or z["name"]).lower()):
            self.zone_box.addItem(f"{meta['title']} (Lv {meta['level']})", meta["name"])
        self.zone_box.activated.connect(self.pick_zone)
        menu.addWidget(self.zone_box)

        menu.addWidget(section("Show on the map"))
        all_row = QHBoxLayout()
        for text, on in (("Show all", True), ("Hide all", False)):
            b = QPushButton(text, objectName="small")
            b.clicked.connect(lambda _=False, on=on: self.set_all(on))
            all_row.addWidget(b)
        menu.addLayout(all_row)
        self.toggle_box = QWidget()
        self.toggles = QVBoxLayout(self.toggle_box)
        self.toggles.setContentsMargins(0, 0, 0, 0)
        self.toggles.setSpacing(3)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(self.toggle_box)
        menu.addWidget(scroll, 1)
        root.addWidget(self.menu)

        # ---- map column
        col = QVBoxLayout()
        col.setSpacing(2)
        top = QHBoxLayout()
        self.title = QLabel(objectName="title")
        self.sub = QLabel(objectName="sub")
        self.back = QPushButton()
        self.back.clicked.connect(self.follow)
        self.menu_btn = QPushButton("Hide menu", objectName="small")
        self.menu_btn.clicked.connect(self.toggle_menu)
        top.addWidget(self.title)
        top.addWidget(self.sub)
        top.addStretch(1)
        self.find_me = QPushButton("Find me", objectName="small")
        self.find_me.setToolTip("Zoom to where you are, on the path you are on")
        self.find_me.clicked.connect(self.go_to_me)
        self.find_me.hide()
        top.addWidget(self.find_me)
        self.live_btn = QPushButton("Live position: off", objectName="small")
        self.live_btn.setToolTip("Where you are, the arrow and your character in Build mode need Npcap: click for the steps")
        self.live_btn.clicked.connect(lambda: self.setup_live and self.setup_live())
        self.live_btn.hide()
        top.addWidget(self.live_btn)
        self.route_label = QLabel(objectName="route")
        self.route_label.hide()
        self.clear_btn = QPushButton("Clear waypoint", objectName="small")
        self.clear_btn.clicked.connect(self.clear_waypoint)
        self.clear_btn.hide()
        top.addWidget(self.route_label)
        top.addWidget(self.clear_btn)
        top.addWidget(self.back)
        top.addWidget(self.menu_btn)
        col.addLayout(top)
        self.map = MapView(data)
        self.map.markerClicked.connect(self.set_waypoint_marker)
        self.map.pointClicked.connect(self.set_waypoint_point)
        col.addWidget(self.map, 1)
        self.hint = QLabel(objectName="hint")
        col.addWidget(self.hint)
        root.addLayout(col, 1)
        self.full_only = [self.menu, self.back, self.menu_btn, self.mode_bar, self.hint]

        self.menu_open = True

        self.tracker = QTimer(self, interval=200)
        self.tracker.timeout.connect(self.track)
        self.tracker.start()
        self.live_timer = QTimer(self, interval=100)
        self.live_timer.timeout.connect(self.update_live)
        if live:
            self.live_timer.start()
        self.apply_mode()
        self.view_zone(None)

    # ---------------------------------------------------------------- zones

    def update_live(self) -> None:
        if self.pinned:  # looking at another zone: your position belongs to a different map
            self.map.set_live(None, {})
            self.find_me.hide()
            return
        me, others = self.live.snapshot()
        mine = self.live.plane()
        if mine is not None and mine != self.last_plane:  # you crossed a bridge (or arrived): follow you again
            self.last_plane, self.path_choice = mine, None
        self.show_path()
        self.map.set_live(me, others)
        self.find_me.setVisible(self.mode == "full" and me is not None)

    def set_current_zone(self, name: str) -> None:
        if self.live and name != self.current:
            self.live.clear()
        self.current = name
        if not self.pinned:
            self.view_zone(name)
        self.update_header()

    def view_zone(self, name: str | None, pinned: bool = False) -> None:
        self.pinned = pinned and bool(name) and (name or "").lower() != (self.current or "").lower()
        if (name or "").lower() != (self.shown or "").lower():
            self.path_choice = None  # another zone: start on your path (or the front one)
        self.shown = name
        self.map.show_zone(self.data.zone(name))
        self.rebuild_toggles()
        self.update_header()
        self.update_waypoint()

    # ---------------------------------------------------------------- waypoint

    def set_waypoint_marker(self, m: dict) -> None:
        label = short_name(m["tip"])
        self.set_waypoint({"zone": self.shown, "x": m["x"], "y": m["y"], "plane": None if m.get("both") else m["plane"],
                           "label": label})

    def set_waypoint_point(self, x: float, y: float, shift: bool) -> None:
        self.set_waypoint({"zone": self.shown, "x": round(x, 2), "y": round(y, 2), "plane": self.map.path,
                           "label": "the spot you picked"})

    def set_waypoint(self, wp: dict) -> None:
        if not wp.get("zone"):
            return
        self.waypoint = wp
        self.settings["waypoint"] = wp
        self.store_settings()
        self.update_waypoint()

    def clear_waypoint(self) -> None:
        self.waypoint = None
        self.settings["waypoint"] = None
        self.store_settings()
        self.update_waypoint()

    def update_waypoint(self) -> None:
        """Where the waypoint leads from where you are (the waypoint, the portal toward its zone, or a bridge first):
        a flag on the map with a line from you, the arrow over the game, and the header line."""
        wp = self.waypoint
        me = self.live.snapshot()[0] if self.live else None  # in your zone (the map may show another)
        mine = self.live.plane() if self.live else None
        t = None
        if wp and self.current:
            if self.graph is None:
                self.graph = ZoneGraph(self.data)
            t = target(self.data, self.graph, self.current, wp, me, mine)
        if wp and t and not self.pinned:
            self.map.set_waypoint((t["x"], t["y"]), me)
        elif wp and (self.shown or "").lower() == wp["zone"].lower():
            self.map.set_waypoint((wp["x"], wp["y"]))  # looking at the waypoint's zone
        else:
            self.map.clear_waypoint()
        if wp:
            title = self.data.zones.get(wp["zone"].lower(), {}).get("title") or wp["zone"]
            text = f"Waypoint: {short_name(wp['label'])} in {title}"
            if t and not t["final"]:
                text += f" · next: {t['label']}"
            elif self.current and not t:
                text += " · no portal way from here"
            self.route_label.setText(text)
        self.route_label.setVisible(self.mode == "full" and wp is not None)
        self.clear_btn.setVisible(self.mode == "full" and wp is not None)
        # the arrow over the game: on the corner map's side of things (the full map covers the game)
        rect = self.game.rect()
        game = rect if rect and self.game.is_visible() else None
        show = t is not None and me is not None and self.mode == "mini" and game is not None
        self.arrow.set_state(game if show else None, (t["x"] - me[0], t["y"] - me[1]) if show else None,
                             t["label"] if t else "",
                             other_path=bool(show and t["plane"] is not None and mine is not None and t["plane"] != mine),
                             goal=t["goal"] if t else "")

    def follow(self) -> None:
        self.view_zone(self.current)

    def pick_zone(self, index: int) -> None:
        name = self.zone_box.itemData(index)
        self.zone_box.setCurrentIndex(0)
        if name:
            self.view_zone(name, pinned=True)

    def update_header(self) -> None:
        z = self.map.zone
        if z:
            self.title.setText(z["title"] or z["name"])
            self.sub.setText(f"Lv {z['level']} · {z['tribe']}" + (" · not your zone" if self.pinned else ""))
        else:
            self.title.setText("MQ Overlay")
            self.sub.setText(f"No map for {self.shown}" if self.shown else "Waiting for the game to enter a zone…")
        cur = self.data.zones.get((self.current or "").lower())
        self.back.setText(f"Back to {cur['title']}" if cur else "Back to your zone")
        self.back.setVisible(self.mode == "full" and self.pinned and bool(self.current))

    # ---------------------------------------------------------------- menu: what the map shows, search

    def rebuild_toggles(self) -> None:
        while self.toggles.count():
            item = self.toggles.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        counts = self.map.counts()
        hidden = set(self.settings["hidden"])
        dpr = self.devicePixelRatioF()
        self.cat_buttons = {}
        for c in self.data.categories:
            if not counts.get(c["key"]):
                continue
            b = QPushButton(f"  {c['label']}   {counts[c['key']]}", objectName="toggle", checkable=True)
            b.setIcon(QIcon(self.map.sprites.get(c["key"], None, dpr)))
            b.setChecked(c["key"] not in hidden)
            b.toggled.connect(lambda on, k=c["key"]: self.toggle_cat(k, on))
            self.toggles.addWidget(b)
            self.cat_buttons[c["key"]] = b
        planes = self.map.planes_present()
        self.path_buttons = {}
        if len(planes) > 1:  # one switch: the path on show is on top, the other one faded behind it
            self.toggles.addWidget(section("Path"))
            row = QWidget()
            lay = QHBoxLayout(row)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(0)
            for p in planes:
                b = QPushButton(objectName="path", checkable=True)
                b.clicked.connect(lambda _=False, p=p: self.choose_path(p))
                lay.addWidget(b, 1)
                self.path_buttons[p] = b
            self.toggles.addWidget(row)
            self.toggles.addWidget(QLabel("Follows you when you cross a bridge", objectName="hint", wordWrap=True))
        self.toggles.addStretch(1)
        self.map.set_filters(hidden)
        self.show_path()

    def toggle_cat(self, key: str, on: bool) -> None:
        hidden = set(self.settings["hidden"])
        hidden.discard(key) if on else hidden.add(key)
        self.settings["hidden"] = sorted(hidden)
        self.map.set_filters(hidden)
        self.store_settings()

    def set_all(self, on: bool) -> None:
        for b in self.cat_buttons.values():
            b.blockSignals(True)
            b.setChecked(on)
            b.blockSignals(False)
        self.settings["hidden"] = [] if on else [c["key"] for c in self.data.categories]
        self.map.set_filters(set(self.settings["hidden"]))
        self.store_settings()

    def choose_path(self, plane: int) -> None:
        """A click on the path switch: show that path (until you next cross a bridge, then it follows you again)."""
        mine = self.my_plane()
        self.path_choice = None if plane == mine else plane
        self.show_path()

    def go_to_me(self) -> None:
        """Find me: back to the path you are on (drops your choice of the other one) and zoom to where you are."""
        self.path_choice = None
        self.show_path()
        self.map.center_on_me(80)
        self.map.user_zoomed = True

    def my_plane(self) -> int | None:
        """The path you are on, when the map shows your zone and the game has told us."""
        return self.live.plane() if self.live is not None and not self.pinned else None

    def shown_path(self) -> int:
        """The path on show: your choice, else the one you are on (the front one until the game tells us)."""
        planes = self.map.planes_present() or [0]
        want = self.path_choice if self.path_choice is not None else self.my_plane()
        return want if want in planes else planes[0]

    def show_path(self) -> None:
        path = self.shown_path()
        if path != self.map.path:
            self.map.set_path(path)
        mine = self.my_plane()
        for p, b in self.path_buttons.items():
            text = ("Front path" if p == 0 else "Back path") + ("  · you" if p == mine else "")
            if b.text() != text:
                b.setText(text)
            if b.isChecked() != (p == path):
                b.blockSignals(True)
                b.setChecked(p == path)
                b.blockSignals(False)

    def set_live_status(self, status: str) -> None:
        """"on", or why the live position is off: the header gets a button that opens the setup window."""
        self.live_status = status
        self.live_btn.setVisible(bool(status) and status != "on" and self.mode == "full")
        self.update_hint()

    def update_hint(self) -> None:
        self.hint.setText(f"{self.settings['hotkey_fullmap']} or Esc: close · {self.settings['hotkey_minimap']}: corner map "
                          "on/off · click a marker or spot: your waypoint (an arrow points the way) · right-click a marker: "
                          "wiki page · wheel: zoom · drag: move · double-click: whole zone"
                          + (f" · live position: {self.live_status}" if self.live_status else ""))

    def store_settings(self) -> None:
        if self.persist:
            save_settings(self.settings)

    def set_view(self, key: str) -> None:
        """The full-screen overlay shows the map (with its menu) or Build mode."""
        self.view = key
        self.settings["tab"] = "Build" if key == "build" else "Map"
        self.store_settings()
        if key == "build":
            self.back_to_build.hide()
        self.apply_view()

    def apply_view(self) -> None:
        build = self.mode == "full" and self.view == "build"
        self.map_page.setVisible(not build)
        self.build_mode.setVisible(build)
        for key, b in self.view_buttons.items():
            b.setChecked(key == self.view)
        if not build:
            QTimer.singleShot(0, self.map.fit)

    def show_place(self, place: dict) -> None:
        """A place from Build mode: the map with its zone, and the waypoint there (or at its zone)."""
        zone = place["zone"]
        if not self.data.zone(zone):
            return
        self.set_view("map")
        self.back_to_build.show()
        self.view_zone(zone, pinned=True)
        if place.get("search"):  # an item: mark every spot of the map that has it, and list the other zones
            self.search.setText(place["search"])
            self.search_timer.stop()
            self.run_search()
        at = place.get("at")
        if at:
            self.set_waypoint({"zone": self.data.zone(zone)["name"], "x": at[0], "y": at[1], "plane": at[2],
                               "label": place.get("label") or "the spot"})

    def toggle_menu(self) -> None:
        self.menu_open = not self.menu_open
        self.menu.setVisible(self.mode == "full" and self.menu_open)
        self.menu_btn.setText("Hide menu" if self.menu_open else "Menu")
        QTimer.singleShot(0, self.map.fit)

    def run_search(self) -> None:
        q = self.search.text()
        here = self.map.highlight(q)
        self.results.clear()
        if not q.strip():
            self.result_label.setText("")
            self.results.hide()
            return
        hits = self.data.search(q)
        self.result_label.setText(f"{here} on this map · {len(hits)} zones have “{q.strip()}”:" if hits
                                  else f"Nothing found for “{q.strip()}”.")
        self.results.setVisible(bool(hits))
        for meta, n in hits:
            it = QListWidgetItem(f"{meta['title']} (Lv {meta['level']}): {n}")
            it.setData(Qt.ItemDataRole.UserRole, meta["name"])
            self.results.addItem(it)

    # ---------------------------------------------------------------- modes and placement

    def toggle_full(self) -> None:
        self.set_mode("mini" if self.mode == "full" else "full")

    def toggle_minimap(self) -> None:
        self.settings["minimap"] = not self.settings["minimap"]
        self.store_settings()
        self.track()

    def set_mode(self, mode: str) -> None:
        if mode == self.mode:
            return
        if self.mode == "full":
            # hand the keyboard back while this window is still in front (Windows refuses it afterwards)
            self.game.activate()
            if self.hotkeys:
                self.hotkeys.unregister("Esc")
        self.mode = mode
        if mode == "full" and self.hotkeys:
            self.hotkeys.register("Esc", self.escape)  # the game keeps the keyboard, so Esc comes as a hotkey
        self.apply_mode()

    def escape(self) -> None:
        if self.search.hasFocus() and self.search.text():
            self.search.clear()
        else:
            self.set_mode("mini")

    def take_keyboard(self) -> None:
        """Typing in the menu needs the keyboard: only then does the overlay become the active window."""
        hwnd = int(self.winId())
        set_no_activate(hwnd, False)
        bring_to_front(hwnd)

    TYPING = (QLineEdit, QAbstractSpinBox, QComboBox)  # a spin box's text is a QLineEdit inside it

    def eventFilter(self, obj, event) -> bool:
        """Watches the whole app: a click on a field you type in, anywhere in this window, takes the keyboard. Only
        the search and the zone list did before, so a number typed into the Build tab's level went to the game."""
        if (event.type() == QEvent.Type.MouseButtonPress and self.mode == "full" and isinstance(obj, self.TYPING)
                and obj.window() is self):
            self.take_keyboard()
        return False

    def apply_mode(self) -> None:
        full = self.mode == "full"
        flags = self.BASE_FLAGS
        if not full:
            flags |= Qt.WindowType.WindowTransparentForInput | Qt.WindowType.WindowDoesNotAcceptFocus
        visible = self.isVisible()
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, not full)
        self.panel.setProperty("mini", not full)
        self.panel.style().unpolish(self.panel)
        self.panel.style().polish(self.panel)
        self.panel.layout().setContentsMargins(*((16, 12, 16, 10) if full else (5, 2, 5, 4)))
        for w in self.full_only:
            w.setVisible(full)
        self.menu.setVisible(full and self.menu_open)
        self.results.setVisible(bool(self.results.count()))
        self.apply_view()
        self.update_header()
        self.update_waypoint()
        self.update_hint()
        self.live_btn.setVisible(full and bool(self.live_status) and self.live_status != "on")
        self.setWindowOpacity(1.0 if full else 0.95)
        # each mode starts with the whole zone; the corner map keeps it (a zoom from the full map must not stay)
        self.map.always_fit = not full
        self.map.follow_span = None if full else self.settings["minimap_span"]
        self.map.set_marker_scale(1.0 if full else 0.7)
        QTimer.singleShot(0, self.map.fit)
        if full:
            # shown without taking focus: the game stays the active window (and keeps running), while the map
            # still gets the mouse and the wheel
            self.track()
            self.show()
            self.raise_()
            set_no_activate(int(self.winId()), True)
        elif visible:
            self.track()

    def track(self) -> None:
        self.update_waypoint()
        game = self.game.rect()  # physical pixels
        if self.mode == "full":
            if game:
                place(self, game)
            elif not self.isVisible():
                screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
                self.set_geometry(screen.availableGeometry())
            return
        if not (self.settings["minimap"] and game and self.game.is_visible() and self.map.zone):
            self.hide()
            return
        s = self.settings
        gx, gy, gw, gh = game
        w = round(gw * s["minimap_width"])
        h = round(w * 0.62)
        m = round(s["minimap_margin"] * self.game.scale())
        corner = s["minimap_corner"]
        x = gx + m if "left" in corner else gx + gw - m - w
        y = gy + gh - m - h if "bottom" in corner else gy + m
        place(self, (x, y, w, h))
        if not self.isVisible():
            self.show()

    def set_geometry(self, r: QRect) -> None:
        if self.geometry() != r:
            self.setGeometry(r)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape and self.mode == "full":
            if self.search.hasFocus() and self.search.text():
                self.search.clear()
            else:
                self.set_mode("mini")
            return
        if event.key() == Qt.Key.Key_F and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if not self.menu_open:
                self.toggle_menu()
            self.search.setFocus()
            self.search.selectAll()
            return
        super().keyPressEvent(event)

    # ---------------------------------------------------------------- testing

    def snapshot(self, path: str, mode: str, size: tuple[int, int]) -> None:
        """Render the overlay into a PNG over a game-like background, without showing a window."""
        self.tracker.stop()
        self.mode = mode
        full = mode == "full"
        self.panel.setProperty("mini", not full)
        self.panel.layout().setContentsMargins(*((16, 12, 16, 10) if full else (5, 2, 5, 4)))
        for w in self.full_only:
            w.setVisible(full)
        self.menu.setVisible(full and self.menu_open)
        self.results.setVisible(bool(self.results.count()))
        self.apply_view()
        self.route_label.setVisible(full and self.waypoint is not None)
        self.clear_btn.setVisible(full and self.waypoint is not None)
        self.update_header()
        self.resize(*size)
        self.ensurePolished()
        self.layout().activate()
        self.map.fit()
        QApplication.processEvents()  # widgets replaced since the last pass (deleteLater, layout requests) settle
        img = QPixmap(*size)
        img.fill(QColor("#7fb3d5"))
        p = QPainter(img)
        p.drawPixmap(0, 0, self.grab())
        p.end()
        img.save(path)
