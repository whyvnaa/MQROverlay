"""Build mode: the full-width view of the full-screen overlay (F7 → Build), from what you own (logic in builder.py):

- top strip: you (level, tribe and badge bonus, bananas), your hotbar template (Melee, Ranged, Stun, Heal, Poison,
  Buff), where you fight, where items may come from;
- left: your gear per slot with its upgrades, the utility slots of your hotbar, the gear nobody knows how to get;
- middle, Progression (progression.py): the best gear at every level per badge tribe, a lane per slot, and for the
  level you pick every item per slot with what it costs against the best and how to get it;
  Shop list (shop_list.py): what is worth looking for now and a few levels above, per tribe (its weapons with the
  badge damage, accessories) and armour per resist element, as sets and per piece, with what each adds to you;
- right: an item's card (stats, what it adds to you, how to get it with the zones that have it, other upgrades for
  its slot), opened by a click on any item.

A click on a 📍 place switches to the map, sets a waypoint there and searches the map for the item. The slow part
(prices, shop list) runs in a background thread."""

import threading
from dataclasses import replace

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QFrame, QProgressBar, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton,
                               QScrollArea, QSizePolicy, QSpinBox, QStackedWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from .builder import HOTBAR, SOURCES, WHERE, Builder, Options, duration, slot_order, way_text
from .item_card import COLOURS, ItemCard
from .player import PlayerState
from .progression import Progression
from .shop_list import ShopList

PLACE = Qt.ItemDataRole.UserRole
ITEM = Qt.ItemDataRole.UserRole + 2  # (prefab, level): a click opens the item's card
STYLE = """
QPushButton#chip { background: rgba(0, 0, 0, 90); color: #a9bf8e; border: 1px solid #3d5a1c; border-radius: 11px;
    padding: 3px 10px; }
QPushButton#chip:checked { background: #e8b130; color: #3b2a05; border-color: #e8b130; }
QPushButton#icon { background: transparent; border: none; padding: 1px; }
QPushButton#icon:hover { background: rgba(232, 177, 48, 60); border-radius: 4px; }
QPushButton#chip:hover { border-color: #e8b130; }
QFrame#strip { background: rgba(30, 52, 22, 230); border: 1px solid #6b8f3a; border-radius: 10px; }
QFrame#column { background: rgba(30, 52, 22, 235); border: 2px solid #e8b130; border-radius: 12px; }
QFrame#card { background: rgba(0, 0, 0, 90); border: 1px solid #3d5a1c; border-radius: 8px; }
QFrame#card[selected="true"] { border: 2px solid #ffd54f; background: rgba(232, 177, 48, 40); }
QLabel#big { font-family: GROBOLD; font-size: 22px; color: #ffd54f; }
QLabel#group { color: #a9bf8e; font-size: 11px; }
QPushButton#pic { background: rgba(0, 0, 0, 90); border: 1px solid #3d5a1c; border-radius: 8px; padding: 3px 5px;
    font-size: 15px; }
QPushButton#pic:checked { background: rgba(232, 177, 48, 70); border: 2px solid #e8b130; padding: 2px 4px; }
QPushButton#pic:!checked { color: rgba(255, 255, 255, 90); }
QPushButton#pic:hover { border-color: #e8b130; }
QProgressBar { background: rgba(0, 0, 0, 120); border: 1px solid #6b8f3a; border-radius: 4px; max-height: 8px; }
QProgressBar::chunk { background: #e8b130; border-radius: 3px; }
"""


def section(text: str) -> QLabel:
    return QLabel(text, objectName="section")


def chip(text: str, checkable: bool = True) -> QPushButton:
    b = QPushButton(text, objectName="chip", checkable=checkable)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    return b


def narrow_button(text: str) -> QPushButton:
    """A row button that never widens its column: a long text is cut (and in the tooltip) instead of pushing the
    scroll area's inner widget past its viewport."""
    b = QPushButton(text, objectName="toggle")
    b.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
    b.setToolTip(text)
    return b


def clear(layout) -> None:
    while layout.count():
        it = layout.takeAt(0)
        if it.widget():
            it.widget().hide()  # gone at once (deleteLater waits for the event loop)
            it.widget().deleteLater()
        elif it.layout():
            clear(it.layout())


class BuildMode(QWidget):
    placeClicked = Signal(dict)  # {"zone", "at", "label"}

    def __init__(self, builder: Builder, player: PlayerState | None, settings: dict, save, current_zone=lambda: None):
        super().__init__()
        self.builder, self.player, self.settings, self.save = builder, player, settings, save
        self.current_zone = current_zone
        self.setStyleSheet(STYLE)
        self.version = -1
        self.profile, self.guide = None, None
        self.job, self.result = 0, None
        self.icons: dict[str, QIcon] = {}
        s = settings.get("build") or {}
        self.opt = Options(level=s.get("level"),
                           slots=tuple(s.get("slots", ("melee", "ranged"))), where=s.get("where", "level"),
                           sources=set(s.get("sources", ["vendor", "chest", "enemy", "craft", "quest"])),
                           look=s.get("look", 5), view="shop" if s.get("view") == "shop" else "progress",
                           shop_tab=s.get("shop_tab", "Shadow"), shop_group=s.get("shop_group", "any"),
                           tribe=s.get("tribe"), effort=s.get("effort"), switch=s.get("switch", 5.0), stage=s.get("stage"),
                           time=s.get("time", 0.0), pick=s.get("pick"), excluded=set(s.get("excluded", [])),
                           prefer=s.get("prefer") if s.get("prefer") in ("melee", "ranged") else None)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)
        outer.addWidget(self.make_strip())
        body = QHBoxLayout()
        body.setSpacing(10)
        outer.addLayout(body, 1)
        body.addWidget(self.make_left())
        body.addWidget(self.make_middle(), 1)
        self.drawer = QFrame(objectName="column")
        self.drawer.setFixedWidth(400)
        dl = QVBoxLayout(self.drawer)
        dl.setContentsMargins(10, 8, 10, 10)
        self.card = ItemCard(self.icon, self.fill_ways, back_text="✕ Close")
        self.card.back.connect(self.drawer.hide)
        self.card.openItem.connect(lambda p: self.open_card(p, 0))
        self.card.excludeClicked.connect(self.toggle_excluded)
        self.card.ways.itemClicked.connect(self.clicked)  # a place: the map; a way: fold it
        dl.addWidget(self.card)
        self.drawer.hide()
        body.addWidget(self.drawer)

        self.timer = QTimer(self, singleShot=True, interval=300)
        self.timer.timeout.connect(self.replan)
        self.poll = QTimer(self, interval=250)
        self.poll.timeout.connect(self.check)
        self.poll.start()

    # ---------------------------------------------------------------- layout

    def make_strip(self) -> QFrame:
        """Two rows: you; then three small groups of picture buttons and one list (what each is: its tooltip)."""
        strip = QFrame(objectName="strip")
        v = QVBoxLayout(strip)
        v.setContentsMargins(12, 8, 12, 8)
        v.setSpacing(6)
        row = QHBoxLayout()
        self.you = QLabel()
        self.you.setTextFormat(Qt.TextFormat.RichText)
        row.addWidget(self.you, 1)
        self.status = QLabel(objectName="sub")
        row.addWidget(self.status)
        self.busy = QProgressBar()  # runs while the plan is worked out
        self.busy.setRange(0, 0)
        self.busy.setTextVisible(False)
        self.busy.setFixedSize(120, 8)
        self.busy.hide()
        row.addWidget(self.busy)
        row.addSpacing(10)
        row.addWidget(QLabel("Your level"))
        self.level = QSpinBox(minimum=0, maximum=60, specialValueText="game")
        self.level.setValue(self.opt.level or 0)
        self.level.setToolTip("Your level (\"game\": from the game); the progression shows every level")
        self.level.valueChanged.connect(self.changed)
        row.addWidget(self.level)
        v.addLayout(row)
        row = QHBoxLayout()
        row.setSpacing(4)

        def pic(text: str, tip: str, on: bool, icon=None) -> QPushButton:
            b = QPushButton(text, objectName="pic", checkable=True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setChecked(on)
            b.setToolTip(tip)
            if icon is not None:
                b.setIcon(icon)
                b.setIconSize(QSize(22, 22))
            row.addWidget(b)
            return b
        row.addWidget(QLabel("HOTBAR", objectName="group"))
        hotbar = {"melee": ("Training Katana", "Melee weapon"), "ranged": ("Slingshot", "Ranged weapon"),
                  "stun": ("Stun Flower", "Stun weapon (stuns hold bosses too)"),
                  "heal": ("Healing Staff", "Healing or life steal"), "poison": ("Stink Bomb", "Poison over time"),
                  "buff": ("Horn of Heroism", "Resist buffs or invisibility")}
        for key, text in HOTBAR:
            name, tip = hotbar[key]
            path = self.builder.icon_named(name) if self.builder.available else None
            icon = QIcon(str(path)) if path and path.exists() else None
            b = pic("" if icon else text, f"{text}: {tip}. On: your hotbar has a slot for it", key in self.opt.slots, icon)
            b.toggled.connect(lambda on, k=key: self.set_slot(k, on))
        self.prefer_box = QComboBox()
        self.prefer_box.setToolTip("Build style: which weapon the accessories and the ranking serve. Hybrid: melee and "
                                   "ranged count the same. Melee or Ranged: that weapon decides, the other one is still "
                                   "picked for its own slot")
        for key, text in ((None, "Hybrid"), ("melee", "Melee build"), ("ranged", "Ranged build")):
            self.prefer_box.addItem(text, key)
        self.prefer_box.setCurrentIndex(max(self.prefer_box.findData(self.opt.prefer), 0))
        self.prefer_box.activated.connect(lambda i: self.set_prefer(self.prefer_box.itemData(i)))
        row.addWidget(self.prefer_box)
        row.addSpacing(18)
        row.addWidget(QLabel("ENEMIES", objectName="group"))
        self.where_box = QComboBox()
        self.where_box.setToolTip("Who the numbers are against: the attack elements decide which armour is best")
        for key, text in WHERE:
            if key != "pick":
                self.where_box.addItem({"level": "Zones around the level", "all": "All zones", "zone": "This zone",
                                        "blunt": "Blunt attackers"}.get(key, f"{text} attackers"), key)
        if self.builder.available:
            self.where_box.insertSeparator(self.where_box.count())
            for name, text in self.builder.fight_zones():
                self.where_box.addItem(text, "pick:" + name)
        wanted = "pick:" + (self.opt.pick or "") if self.opt.where == "pick" else self.opt.where
        self.where_box.setCurrentIndex(max(self.where_box.findData(wanted), 0))
        self.where_box.activated.connect(lambda i: self.set_where(self.where_box.itemData(i)))
        row.addWidget(self.where_box)
        row.addSpacing(18)
        row.addWidget(QLabel("ITEMS FROM", objectName="group"))
        sources = {"vendor": ("\U0001F6D2", "Vendors (bananas)"), "chest": ("\U0001F4E6", "Chests, breakables, gathering spots"),
                   "enemy": ("\U0001F479", "Enemy drops"), "craft": ("\U0001F528", "Crafting"),
                   "quest": ("\u2757", "Quest rewards"), "nick_cash": ("\U0001F48E", "The NickCash shop"),
                   "unknown": ("\u2753", "Items nobody knows how to get: they join the progression and the shop list")}
        for key, text in SOURCES:
            emoji, tip = sources[key]
            b = pic(emoji, tip, key in self.opt.sources)
            b.toggled.connect(lambda on, k=key: self.set_source(k, on))
        row.addStretch(1)
        v.addLayout(row)
        return strip

    def make_left(self) -> QFrame:
        col = QFrame(objectName="column")
        col.setFixedWidth(340)
        outer = QVBoxLayout(col)
        outer.setContentsMargins(10, 8, 6, 10)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        v = QVBoxLayout(inner)
        v.setContentsMargins(0, 0, 6, 0)
        v.setSpacing(6)
        scroll.setWidget(inner)
        outer.addWidget(scroll)
        v.addWidget(QLabel("Your gear", objectName="big"))
        self.gear_about = QLabel(objectName="sub")
        self.gear_about.setWordWrap(True)
        v.addWidget(self.gear_about)
        self.gear = QVBoxLayout()
        self.gear.setSpacing(2)
        v.addLayout(self.gear)
        self.util_title = section("Utility slots")
        v.addWidget(self.util_title)
        self.util = QVBoxLayout()
        self.util.setSpacing(4)
        v.addLayout(self.util)
        self.excluded_title = section("Excluded items")
        self.excluded_title.setToolTip("Items you excluded on their card: nothing suggests them. ↩ takes one back in")
        v.addWidget(self.excluded_title)
        self.excluded = QVBoxLayout()
        self.excluded.setSpacing(2)
        v.addLayout(self.excluded)
        self.show_excluded()
        self.no_way_btn = QPushButton(objectName="small", checkable=True)
        self.no_way_btn.toggled.connect(lambda on: self.no_way.setVisible(on))
        v.addWidget(self.no_way_btn)
        self.no_way = QListWidget()
        self.no_way.setMinimumHeight(160)
        self.no_way.setIconSize(QSize(22, 22))
        self.no_way.itemClicked.connect(lambda it: self.open_card(it.data(PLACE), 0))
        self.no_way.hide()
        v.addWidget(self.no_way)
        v.addStretch(1)
        return col

    def make_middle(self) -> QFrame:
        col = QFrame(objectName="column")
        v = QVBoxLayout(col)
        v.setContentsMargins(12, 8, 12, 10)
        v.setSpacing(6)
        top = QHBoxLayout()
        self.view_group = QButtonGroup(self)
        for key, text, tip in (("progress", "Progression", "The best gear at every level, per badge tribe, with every alternative"),
                               ("shop", "Shop list", "What is worth looking for now and a few levels above, per tribe and armour")):
            b = chip(text)
            b.setChecked(key == self.opt.view)
            b.setToolTip(tip)
            self.view_group.addButton(b)
            b.clicked.connect(lambda _=False, k=key: self.set_view(k))
            top.addWidget(b)
        top.addSpacing(10)
        self.progress_head = QLabel("Best gear by level", objectName="big")
        top.addWidget(self.progress_head, 1)
        self.shop = ShopList(self.icon, self.opt.shop_tab, self.opt.shop_group, self.opt.look)
        self.shop.itemClicked.connect(self.open_card)
        self.shop.lookChanged.connect(self.set_look)
        self.shop.tabChanged.connect(self.set_shop_tab)
        self.shop_head = QWidget()
        head = QHBoxLayout(self.shop_head)
        head.setContentsMargins(0, 0, 0, 0)
        head.addWidget(QLabel("What to look for", objectName="big"))
        head.addStretch(1)
        head.addWidget(QLabel("Look ahead"))
        head.addWidget(self.shop.look)
        top.addWidget(self.shop_head, 1)
        v.addLayout(top)
        self.pages = QStackedWidget()
        self.progress = Progression(self.icon, lambda t: QIcon(str(self.builder.crest(t))), self.opt.tribe,
                                    self.opt.effort, self.opt.switch, self.opt.stage, self.opt.time)
        self.progress.itemClicked.connect(self.open_card)
        self.progress.placeClicked.connect(self.placeClicked.emit)
        self.progress.changed.connect(self.progress_changed)
        self.pages.addWidget(self.progress)
        self.pages.addWidget(self.shop)
        v.addWidget(self.pages, 1)
        self.apply_view()
        return col

    def progress_changed(self) -> None:
        pr = self.progress
        if pr.tribe != self.opt.tribe and self.guide:  # "better in your bag" follows the badge you picked
            self.guide["gear"] = self.builder.gear(self.snap, self.profile, self.guide["planner"], pr.tribe)
            self.opt.tribe = pr.tribe
            self.show_gear()
        self.opt.tribe, self.opt.effort, self.opt.switch, self.opt.stage = pr.tribe, pr.effort, pr.switch, pr.level
        self.opt.time = pr.time
        self.store()

    def apply_view(self) -> None:
        shop = self.opt.view == "shop"
        for b in self.view_group.buttons():  # also when set from code (snapshots)
            b.setChecked((b.text() == "Shop list") == shop)
        self.progress_head.setVisible(not shop)
        self.shop_head.setVisible(shop)
        self.pages.setCurrentIndex(1 if shop else 0)

    def set_view(self, key: str) -> None:
        self.opt.view = key
        self.store()
        self.apply_view()

    def set_shop_tab(self, tab: str, group: str) -> None:
        self.opt.shop_tab, self.opt.shop_group = tab, group
        self.store()

    def set_look(self, levels: int) -> None:
        """The shop list's reach changed: only the shop list is worked out again (fast, GUI thread)."""
        self.opt.look = levels
        self.store()
        g = self.guide
        if g:
            g["shop"] = self.builder.shop_list(g["planner"], g["costs"], self.profile, g["now"], self.opt)
            self.shop.set_data(g["shop"], self.profile, self.profile.weapons, g["now"])

    # ---------------------------------------------------------------- options

    def store(self) -> None:
        self.settings["build"] = {"level": self.opt.level,
                                  "slots": list(self.opt.slots), "where": self.opt.where,
                                  "sources": sorted(self.opt.sources), "look": self.opt.look, "view": self.opt.view,
                                  "shop_tab": self.opt.shop_tab, "shop_group": self.opt.shop_group,
                                  "tribe": self.opt.tribe, "effort": self.opt.effort, "switch": self.opt.switch,
                                  "stage": self.opt.stage, "time": self.opt.time, "pick": self.opt.pick,
                                  "excluded": sorted(self.opt.excluded), "prefer": self.opt.prefer}
        self.save(self.settings)

    def changed(self) -> None:
        self.opt.level = self.level.value() or None
        self.store()
        self.timer.start()

    def set_slot(self, key: str, on: bool) -> None:
        self.opt.slots = tuple(k for k, _ in HOTBAR if (k == key and on) or (k != key and k in self.opt.slots))
        self.changed()

    def set_prefer(self, key: str | None) -> None:
        self.opt.prefer = key
        self.changed()

    def set_where(self, key: str) -> None:
        if not key:
            return
        if key.startswith("pick:"):
            self.opt.where, self.opt.pick = "pick", key[5:]
        else:
            self.opt.where = key
        self.changed()

    def set_source(self, key: str, on: bool) -> None:
        (self.opt.sources.add if on else self.opt.sources.discard)(key)
        self.changed()

    def check(self) -> None:
        if self.result and self.result[0] == self.job:
            _, guide = self.result
            self.result = None
            self.show_guide(guide)
        if self.isVisible() and self.player and self.player.version != self.version and not self.timer.isActive():
            self.timer.start()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self.guide is None or (self.opt.where == "zone" and self.opt.zone != self.current_zone()):
            self.timer.start()

    def icon(self, prefab: str | None) -> QIcon:
        if not prefab:
            return QIcon()
        if prefab not in self.icons:
            path = self.builder.icon(prefab)
            self.icons[prefab] = QIcon(str(path)) if path and path.exists() else QIcon()
        return self.icons[prefab]

    # ---------------------------------------------------------------- planning

    def replan(self, wait: bool = False) -> None:
        self.timer.stop()  # a pending debounce would plan the same thing again
        if not self.builder.available:
            self.status.setText("No build data: re-export the overlay data from the knowledge base.")
            return
        snap = self.player.snapshot() if self.player else {"known": False, "version": 0}
        self.version = snap["version"]
        self.opt.zone = self.current_zone()
        self.snap = snap
        self.profile = self.builder.profile(snap, self.opt)
        self.status.setText("Working out your gear…")
        self.busy.show()
        self.job += 1
        job, profile = self.job, self.profile
        opt = replace(self.opt, sources=set(self.opt.sources), excluded=set(self.opt.excluded))

        def work():
            self.result = (job, self.builder.guide(profile, opt, snap))
        if wait:
            work()
            self.check()
        else:
            threading.Thread(target=work, daemon=True).start()

    def show_guide(self, guide: dict) -> None:
        self.guide = guide
        self.status.setText("")
        self.busy.hide()
        self.show_you()
        self.show_utility()
        self.show_gear()
        self.progress.set_data(guide["planner"], guide["costs"], self.profile, guide["prices"], guide["now"],
                               self.where_text, self.opt.unknown, self.opt.utility)
        self.shop.set_data(guide["shop"], self.profile, self.profile.weapons, guide["now"])
        self.no_way_btn.setText(f"No known way to get ({len(guide['no_way'])})")
        self.no_way.clear()
        for item, why in guide["no_way"]:
            row = QListWidgetItem(self.icon(item["prefab"]), f"{item.get('name')} (level {item.get('level_req') or 1}): {why}")
            row.setData(PLACE, item["prefab"])
            self.no_way.addItem(row)

    def show_you(self) -> None:
        snap, g, p = self.snap, self.guide, self.profile
        bits = [f"<b style='color:#ffd54f'>Level {p.level}</b>"
                + (f" (set by you; the game says {snap['level']})" if snap.get("level") and snap["level"] != p.level else "")]
        if g["tribe"]:
            el = {"Shadow": "Air", "Bone": "Earth", "Outlaw": "Fire", "Wild": "Ice", "Grease": "Lightning"}.get(g["tribe"])
            dmg, dfn = g["badge"]
            bits.append(f"{g['tribe']}, {p.skill_points} skill points (badge {p.skill_points // 5})"
                        + (f": <span style='color:{COLOURS.get(el, '#ffab61')}'>+{dmg} {el} damage</span>, "
                           f"<span style='color:{COLOURS['def']}'>+{dfn} defence</span>" if dmg else ""))
        if snap.get("bananas") is not None:
            bits.append(f"{snap['bananas']:,} bananas")
        if snap.get("nick_cash") is not None:
            bits.append(f"{snap['nick_cash']:,} NickCash")
        source = snap.get("source", "none")
        bits.append({"login": "from your login", "live": "from changes (log in again for everything)",
                     "saved": "saved last time (log in to refresh)"}.get(source, "nothing from the game yet: log in with the overlay running"))
        z = self.builder.zone_info(self.opt.zone)
        self.where_box.setItemText(self.where_box.findData("zone"), f"This zone ({z['title']})" if z else "This zone")
        self.you.setText(" · ".join(bits))

    def where_text(self, level: int | None = None) -> str:
        zone = self.opt.zone if self.opt.where == "zone" else self.opt.pick if self.opt.where == "pick" else None
        if self.builder.zone_info(zone):
            z = self.builder.zone_info(zone)
            return f"{z['title']} (level {z.get('level')})"
        if self.opt.where == "all":
            return "the enemies of every zone"
        if self.opt.where in ("level", "zone", "pick"):
            return f"the zones around level {level or self.profile.level}"
        return f"{self.opt.where.lower()} attacks"

    def show_utility(self) -> None:
        clear(self.util)
        rows = self.guide["utility"]
        self.util_title.setVisible(bool(rows))
        for slot in sorted(rows, key=slot_order):
            opts = rows[slot]
            if not opts:
                lab = QLabel(f"<b>{slot}</b>: nothing you can get at your level")
                lab.setObjectName("sub")
                self.util.addWidget(lab)
                continue
            for r in reversed(opts[-2:]):  # the best, and the cheaper runner-up
                it = r["item"]
                b = narrow_button(f"{slot}: {it.get('name')} · {r['text']} · {duration(r['hours'])}")
                b.setIcon(self.icon(it["prefab"]))
                b.setIconSize(QSize(22, 22))
                b.clicked.connect(lambda _=False, p=it["prefab"]: self.open_card(p, 0))
                self.util.addWidget(b)

    def show_gear(self) -> None:
        """What you wear per slot (from the game), and under it a better piece you already own, if there is one."""
        clear(self.gear)
        g = self.guide
        now, ev, gear = g["now"], g["now_ev"], g["gear"]
        known = bool(gear["worn"])
        if not ev:
            self.gear_about.setText("Nothing from the game yet: log in with the overlay running.")
        else:
            self.gear_about.setText(("What you wear" if known else "The best of what you own")
                                    + f", against {self.where_text()}: kills in {ev['kill_time']:.1f} s, takes "
                                    f"{ev['damage_taken']:,.0f} a hit.")
        for label in g["planner"].slot_labels(self.profile):
            have = now.get(label)
            b = narrow_button(f"{label}: {have.get('name') if have else 'nothing'}")
            b.setIcon(self.icon(have["prefab"] if have else None))
            b.setIconSize(QSize(22, 22))
            b.setEnabled(bool(have))
            if have:
                b.clicked.connect(lambda _=False, p=have["prefab"], lab=label: self.open_card(p, 0, lab))
            self.gear.addWidget(b)
            up = gear["better"].get(label) if known else None
            if up:
                u = narrow_button(f"   better in your bag: {up.get('name')}")
                u.setToolTip(f"{up.get('name')}: part of the best set from your bag with the badge in {gear['bag_tribe']}, "
                             f"against {self.where_text()}")
                u.setStyleSheet("color: #a5d66b;")
                u.setIcon(self.icon(up["prefab"]))
                u.setIconSize(QSize(20, 20))
                u.clicked.connect(lambda _=False, p=up["prefab"], lab=label: self.open_card(p, 0, lab))
                self.gear.addWidget(u)

    # ---------------------------------------------------------------- items

    def toggle_excluded(self, prefab: str) -> None:
        """Leave an item out of everything Build mode suggests, or take it back in; then plan again."""
        (self.opt.excluded.discard if prefab in self.opt.excluded else self.opt.excluded.add)(prefab)
        if self.card.prefab == prefab:
            self.card.set_excluded(prefab in self.opt.excluded)
        self.show_excluded()
        self.store()
        self.timer.start()

    def show_excluded(self) -> None:
        """The left column's list of excluded items: a click opens the card, ↩ takes the item back in."""
        clear(self.excluded)
        self.excluded_title.setVisible(bool(self.opt.excluded))
        if not self.builder.available:
            return
        for name, prefab in sorted((self.builder.item(p).get("name") or p, p) for p in self.opt.excluded):
            row = QHBoxLayout()
            row.setSpacing(2)
            b = narrow_button(name)
            b.setIcon(self.icon(prefab))
            b.setIconSize(QSize(22, 22))
            b.clicked.connect(lambda _=False, p=prefab: self.open_card(p, 0))
            row.addWidget(b, 1)
            back = QPushButton("↩", objectName="small")
            back.setToolTip(f"Include {name} again")
            back.setCursor(Qt.CursorShape.PointingHandCursor)
            back.clicked.connect(lambda _=False, p=prefab: self.toggle_excluded(p))
            row.addWidget(back)
            self.excluded.addLayout(row)

    def fill_ways(self, node: QTreeWidgetItem, item: dict, level: int) -> bool:
        """Every way to get the item at that level under node; True if you have it."""
        costs = self.guide["costs"]
        prof = replace(self.profile, level=max(level, self.profile.level))
        ways = costs.ways(item["prefab"], prof)
        owned = bool(ways and ways[0].kind == "owned")
        if owned:  # still show where it comes from
            node.addChild(QTreeWidgetItem(["You have it. Where another one comes from:"]))
            ways = costs.ways(item["prefab"], prof, buy_more=True)
        if not ways:
            node.addChild(QTreeWidgetItem(["No known way to get it (with the sources you picked)"]))
        for w in ways:
            self.add_way(node, w, costs, name=item.get("name"))
        found = costs.find(item["prefab"])
        if found:  # like the map search: every zone that has it, with how many spots
            zones = QTreeWidgetItem([f"Zones that have it ({len(found)})"])
            node.addChild(zones)
            for z in found:
                leaf = QTreeWidgetItem([f"📍 {z['title']}" + (f" (Lv {z['level']})" if z["level"] else "") + f": {z['text']}"])
                leaf.setData(0, PLACE, {"zone": z["zone"], "at": None, "label": item.get("name"), "search": item.get("name")})
                leaf.setToolTip(0, "Show the zone's map with every spot that has it")
                zones.addChild(leaf)
        return owned

    def add_way(self, parent: QTreeWidgetItem, w, costs, depth: int = 0, name: str | None = None) -> None:
        """name: the item this way gives (the map then also marks every spot that has it)."""
        node = QTreeWidgetItem([way_text(w)])
        parent.addChild(node)
        self.add_places(node, w, costs, name)
        for prefab, need, have, pw in w.parts:
            text = f"{need}× {self.builder.item(prefab).get('name')}" + (f" (you have {have})" if have else "")
            part = QTreeWidgetItem([text + (f" — {way_text(pw)}" if pw else " — you have them")])
            part.setIcon(0, self.icon(prefab))
            node.addChild(part)
            if pw and pw.parts and depth < 3:
                self.add_way(part, pw, costs, depth + 1, self.builder.item(prefab).get("name"))
            elif pw:
                self.add_places(part, pw, costs, self.builder.item(prefab).get("name"))

    def add_places(self, node: QTreeWidgetItem, w, costs, name: str | None = None) -> None:
        for place in w.where:
            leaf = QTreeWidgetItem([f"📍 {costs.title(place['zone'])}: {place['label']}"])
            leaf.setData(0, PLACE, place | ({"search": name} if name and w.kind in ("chest", "enemy", "tribe_drop") else {}))
            leaf.setToolTip(0, "Show on the map and set a waypoint")
            node.addChild(leaf)

    def open_card(self, prefab: str | None, level: int, slot: str | None = None) -> None:
        if not self.guide or not prefab:
            return
        pl = self.guide["planner"]
        item = pl.opt.item.get(prefab) or self.builder.item(prefab)
        level = max(level, self.profile.level, item.get("level_req") or 0)
        slot = slot or item.get("slot")
        explain = None
        if slot and item.get("scaled_sum") and (slot not in ("Melee", "Ranged") or slot.lower() in self.profile.weapons):
            explain = pl.explain(item, slot, self.guide["now"], replace(self.profile, level=level))
        self.card.show_item(item, level, explain, self.guide["slots"].get(slot, []) if slot else [], self.profile.level,
                            prefab in self.opt.excluded)
        self.drawer.show()

    def clicked(self, item: QTreeWidgetItem) -> None:
        place = item.data(0, PLACE)
        if place and place.get("zone"):
            self.placeClicked.emit(place)
        elif item.data(0, ITEM):
            self.open_card(*item.data(0, ITEM))
        else:
            item.setExpanded(not item.isExpanded())
