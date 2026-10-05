"""The shop list of Build mode: what is worth looking for now and a few levels above, broadly (Planner.recommend
through builder.Builder.shop_list). One tab per tribe (the weapons of its element with the badge damage you would
get there, the accessories per slot) and an Armour tab with a group per resist element (plus blunt attackers and
defence only), each with the best set from the lists on top. Every row: icon, name, from which level, hours and the
way to get it, the item's own stats and what it adds to you (hit, hits to kill, kill time; armour: damage taken per
attack element). A click opens the item's card."""

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QButtonGroup, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea,
                               QSizePolicy, QSpinBox, QVBoxLayout, QWidget)

from .build_planner import ELEMENTS, TRIBE_ELEMENT
from .builder import duration, way_short
from .item_card import COLOURS, c, stats_html

TABS = ["Shadow", "Bone", "Outlaw", "Wild", "Grease", "Crossroads", "Armour"]
TRIBE_NAMES = {"Shadow": "Chim Foo", "Bone": "Ootu Mystics", "Outlaw": "Sea Dragons", "Wild": "Ice Raiders",
               "Grease": "Mek-Tek", "Crossroads": "blunt"}
GROUPS = [(el, el) for el in ELEMENTS] + [("blunt", "Blunt"), ("any", "Defence only")]
GREY = "#a9bf8e"


def grey(text) -> str:
    return f"<span style='color:{GREY}'>{text}</span>"


def secs(t: float) -> str:
    return c("t", f"{t:.1f} s")


def dmg_text(hit: float) -> str:
    return c("dmg", f"{hit:,.0f}")


def clear(layout) -> None:
    while layout.count():
        it = layout.takeAt(0)
        if it.widget():
            it.widget().hide()
            it.widget().deleteLater()
        elif it.layout():
            clear(it.layout())


def chip(text: str) -> QPushButton:
    b = QPushButton(text, objectName="chip", checkable=True)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    return b


class Row(QFrame):
    """One recommended item: icon, name, from which level, hours; its stats; what it adds; the way to get it."""
    clicked = Signal()
    pinned = Signal()  # the pin button: show the place on the map

    def __init__(self, icon, name: str, right: str, lines: list[str], pin: str = ""):
        super().__init__(objectName="card")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Click: details, what it adds to you, how to get it")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 5, 8, 5)
        lay.setSpacing(8)
        pic = QLabel()
        pic.setFixedSize(36, 36)
        pic.setPixmap(icon.pixmap(34, 34) if not icon.isNull() else QPixmap())
        lay.addWidget(pic, 0, Qt.AlignmentFlag.AlignTop)
        v = QVBoxLayout()
        v.setSpacing(1)
        top = QHBoxLayout()
        top.setSpacing(6)
        title = QLabel(name)
        title.setTextFormat(Qt.TextFormat.RichText)
        title.setWordWrap(True)
        top.addWidget(title, 1)
        hours = QLabel(right)
        hours.setTextFormat(Qt.TextFormat.RichText)
        top.addWidget(hours, 0, Qt.AlignmentFlag.AlignTop)
        if pin:
            b = QPushButton("📍", objectName="icon")
            b.setToolTip(pin)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(self.pinned.emit)
            top.addWidget(b, 0, Qt.AlignmentFlag.AlignTop)
        v.addLayout(top)
        for line in lines:
            if not line:
                continue
            lab = QLabel(line)
            lab.setTextFormat(Qt.TextFormat.RichText)
            lab.setWordWrap(True)
            v.addWidget(lab)
        lay.addLayout(v, 1)

    def mousePressEvent(self, event) -> None:
        self.clicked.emit()


class ShopList(QWidget):
    itemClicked = Signal(str, int, str)  # prefab, level, slot label
    lookChanged = Signal(int)
    tabChanged = Signal(str, str)  # tab, armour group

    def __init__(self, icon_for, tab: str = "Shadow", group: str = "any", look: int = 5):
        super().__init__()
        self.icon_for = icon_for
        self.tab, self.group = tab if tab in TABS else "Shadow", group if group in dict(GROUPS) else "any"
        self.shop, self.profile, self.weapons, self.now_picks = None, None, ("melee", "ranged"), {}
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)
        # two rows, one choice between them: weapons and accessories with the badge in a tribe, or armour against
        # an attack element (one click each)
        row = QHBoxLayout()
        row.setSpacing(3)
        row.addWidget(QLabel("<b>Weapons, badge in</b>"))
        self.tabs = QButtonGroup(self)
        self.tab_buttons = {}
        for t in TABS:
            if t == "Armour":
                continue
            b = chip(t)
            b.setChecked(t == self.tab)
            b.setToolTip(f"If you put your skill points in {t} ({TRIBE_NAMES[t]}): weapons of its element get the badge damage")
            self.tabs.addButton(b)
            self.tab_buttons[t] = b
            b.clicked.connect(lambda _=False, t=t: self.set_tab(t))
            row.addWidget(b)
        row.addStretch(1)
        v.addLayout(row)
        # the reach spinner is placed by Build mode in its title row (it belongs to this list: lookChanged)
        self.look = QSpinBox(minimum=0, maximum=40, suffix=" levels")
        self.look.setValue(look)
        self.look.setToolTip("Items you can use now or within this many levels (the next ones above are shown as \"later\")")
        self.look.valueChanged.connect(self.lookChanged.emit)
        # never widen the column: a hidden page still counts for a stacked widget's minimum width
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        row = QHBoxLayout()
        row.setSpacing(3)
        row.addWidget(QLabel("<b>Armour against</b>"))
        self.group_buttons = {}
        for key, text in GROUPS:
            b = chip(text)
            b.setChecked(self.tab == "Armour" and key == self.group)
            b.setToolTip({"blunt": "Blunt attackers (Crossroads enemies): every resist counts",
                          "any": "Defence alone, which counts against everything"}.get(
                key, f"{key} attackers: {key} resist counts, on top of defence"))
            self.tabs.addButton(b)
            self.group_buttons[key] = b
            b.clicked.connect(lambda _=False, k=key: self.set_group(k))
            row.addWidget(b)
        row.addStretch(1)
        v.addLayout(row)
        self.about = QLabel(objectName="sub")
        self.about.setWordWrap(True)
        v.addWidget(self.about)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        inner = QWidget()
        self.body = QVBoxLayout(inner)
        self.body.setContentsMargins(0, 0, 6, 0)
        self.body.setSpacing(6)
        scroll.setWidget(inner)
        v.addWidget(scroll, 1)

    # ---------------------------------------------------------------- state

    def set_tab(self, tab: str) -> None:
        if tab == "Armour":
            return self.set_group(self.group)
        self.tab = tab
        if tab in self.tab_buttons:  # also when set from code (snapshots, settings)
            self.tab_buttons[tab].setChecked(True)
        self.tabChanged.emit(self.tab, self.group)
        self.rebuild()

    def set_group(self, group: str) -> None:
        self.tab, self.group = "Armour", group
        if group in self.group_buttons:
            self.group_buttons[group].setChecked(True)
        self.tabChanged.emit(self.tab, self.group)
        self.rebuild()

    def set_data(self, shop: dict, profile, weapons: tuple[str, ...], now_picks: dict) -> None:
        """shop: Builder.shop_list(); now_picks: your build (slot label -> item)."""
        self.shop, self.profile, self.weapons, self.now_picks = shop, profile, weapons, now_picks
        self.rebuild()

    # ---------------------------------------------------------------- building

    def rebuild(self) -> None:
        clear(self.body)
        if not self.shop:
            self.about.setText("")
            return
        if self.tab == "Armour":
            self.build_armour()
        else:
            self.build_tribe(self.tab)
        self.body.addStretch(1)

    def section(self, text: str, hint: str = "") -> None:
        lab = QLabel(text + (f" <span style='font-family:Nunito; font-size:11px; color:{GREY}'>{hint}</span>" if hint else ""),
                     objectName="section")
        lab.setTextFormat(Qt.TextFormat.RichText)
        self.body.addWidget(lab)

    def note(self, text: str) -> None:
        lab = QLabel(text, objectName="sub")
        lab.setTextFormat(Qt.TextFormat.RichText)
        lab.setWordWrap(True)
        self.body.addWidget(lab)

    def rows(self, rows: list[dict], slot: str, adds) -> None:
        """A two-column grid of rows; adds(row) -> the "what it adds" line."""
        grid = QGridLayout()
        grid.setSpacing(5)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        p = self.profile
        for i, r in enumerate(rows):
            it = r["item"]
            name = f"<b>{it.get('name')}</b>"
            if r["pick"]:
                name = f"<span style='color:#ffd54f'>★</span> " + name
            if r["from"] > p.level:
                name += " " + (f"<span style='color:#ff9f5a'>later: from level {r['from']}</span>" if r["later"]
                               else f"<span style='color:#ffd54f'>from level {r['from']}</span>")
            if r["owned"]:
                right = c("hp", "you have it")
            elif r["hours"] == float("inf"):
                right = c("loss", "no known way")
            else:
                right = f"<b>{duration(r['hours'])}</b>"
            way = grey("in your inventory" if r["owned"] else way_short(r["way"]))
            row = Row(self.icon_for(it["prefab"]), name, right, [stats_html(it), adds(r), way])
            row.clicked.connect(lambda prefab=it["prefab"], level=r["level"], slot=slot: self.itemClicked.emit(prefab, level, slot))
            grid.addWidget(row, i // 2, i % 2)
        self.body.addLayout(grid)

    def missing(self, items: list[dict]) -> None:
        """The better items with no known way: a line, or (many) a button that unfolds the full list."""
        if not items:
            return
        text = ", ".join(f"{it.get('name')} (level {it.get('level_req') or 1})" for it in items)
        if len(items) <= 6:
            self.note("No known way to get: " + text)
            return
        btn = QPushButton(f"No known way to get: {len(items)} more items ▸", objectName="small", checkable=True)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        lab = QLabel(text, objectName="sub")
        lab.setWordWrap(True)
        lab.hide()
        btn.toggled.connect(lambda on: (lab.setVisible(on), btn.setText(btn.text()[:-1] + ("▾" if on else "▸"))))
        row = QHBoxLayout()
        row.addWidget(btn)
        row.addStretch(1)
        self.body.addLayout(row)
        self.body.addWidget(lab)

    def header(self, title: str, lines: list[str], items: list[dict]) -> None:
        card = QFrame(objectName="card")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(3)
        t = QLabel(title)
        t.setTextFormat(Qt.TextFormat.RichText)
        t.setWordWrap(True)
        lay.addWidget(t)
        for line in lines:
            lab = QLabel(line)
            lab.setTextFormat(Qt.TextFormat.RichText)
            lab.setWordWrap(True)
            lay.addWidget(lab)
        if items:
            row = QHBoxLayout()
            row.setSpacing(1)
            for slot, it in items:
                b = QPushButton(objectName="icon")
                b.setIcon(self.icon_for(it["prefab"]))
                b.setIconSize(QSize(26, 26))
                b.setFixedSize(30, 30)
                b.setToolTip(f"{slot}: {it.get('name')} (click for details)")
                b.clicked.connect(lambda _=False, prefab=it["prefab"], slot=slot: self.itemClicked.emit(prefab, 0, slot))
                row.addWidget(b)
            row.addStretch(1)
            lay.addLayout(row)
        self.body.addWidget(card)

    def build_tribe(self, tribe: str) -> None:
        t = self.shop["tribes"][tribe]
        el = t["element"]
        p = self.profile
        look = self.shop["ahead"]
        dmg, dfn = t["badge"]
        colour = COLOURS.get(el, "#ffab61")
        mine = self.shop["tribe"] == tribe
        self.about.setText(
            f"If your skill points sit in {tribe}: the {el or 'blunt'} weapons get the badge damage, the accessories "
            f"with {el or 'blunt'} damage help them; every number is against level {p.level} enemies as if you had the item "
            f"now. ★ no other is cheaper, stronger and usable sooner at once. Up to level {p.level + look}, then the "
            f"next ones as \"later\". Click a row for details and how to get it." if el else
            f"Crossroads: no badge damage; weapons with no element and accessories with blunt damage, which counts for "
            f"every weapon. Every number is against level {p.level} enemies as if you had the item now. ★ no other is "
            f"cheaper, stronger and usable sooner at once. Up to level {p.level + look}, then the next ones as \"later\".")
        badge = (f"badge {p.skill_points // 5}: <span style='color:{colour}'>+{dmg} {el} damage</span> on {el} weapons, "
                 f"{c('def', f'+{dfn} defence')} against everything" if dmg else
                 f"no badge bonus yet ({p.skill_points} skill points)" if el else "no badge damage (blunt)")
        now, build = t["now"], t["build"]
        picks = [(slot, it) for slot, it in build["picks"].items() if it and slot not in ("Hat", "Body", "Legs", "Backpack")]
        new = [(slot, it) for slot, it in picks if not p.owned.get(it["prefab"])]
        lines = [f"Your gear in this tribe kills in {secs(now['kill_time'])}" + (" (your tribe now)" if mine else "") + "."]
        if new:
            lines.append(f"<b>Best set from the lists:</b> kills in {secs(build['kill_time'])} · "
                         f"<b>{duration(build['hours'])}</b> to get · " + ", ".join(f"{slot}: {it.get('name')}" for slot, it in new))
        else:
            lines.append("Nothing in the lists beats what you have in this tribe.")
        self.header(f"<span style='font-family:GROBOLD; font-size:18px; color:#ffd54f'>{tribe}</span> "
                    f"<span style='color:{colour}'>{TRIBE_NAMES[tribe]} · {el or 'blunt'}</span> · {badge}", lines, new)

        def weapon_line(r: dict, cls: str) -> str:
            t_now = now["hits"][cls]["time"]
            return (f"hit {dmg_text(r['hit'])} · {r['hits']} hits · kills in {secs(r['hits_by'][cls]['time'])} "
                    + grey(f"(now {t_now:.1f} s)"))

        def accessory_line(r: dict) -> str:
            hits = " · ".join(f"{cls} hit {dmg_text(h['hit'])} ({h['hits']} hits)" for cls, h in r["hits_by"].items())
            return f"{hits} · kills in {secs(r['kill_time'])}"
        for cls in self.weapons:
            label = cls.capitalize()
            rows = t["weapons"].get(label, [])
            self.section(f"{label} · {el or 'blunt'} weapons", f"with your accessories; now kills in {now['hits'][cls]['time']:.1f} s")
            if rows:
                self.rows(rows, label, lambda r, cls=cls: weapon_line(r, cls))
            else:
                self.note(f"No {el or 'blunt'} {cls} weapon with a known way to get it beats yours up to level {p.level + look}.")
            self.missing(t["missing"].get(label, []))
        ww = t["with_weapons"]
        for label in ("Ears", "Wrist", "Tail"):
            rows = t["accessories"].get(label, [])
            self.section(label, f"with the tribe's best weapons from above; they kill in {ww['kill_time']:.1f} s alone")
            if rows:
                self.rows(rows, label, accessory_line)
            else:
                self.note(f"Nothing beats your {label.lower()} piece for {el or 'blunt'} weapons up to level {p.level + look}.")
            self.missing(t["missing"].get(label, []))

    def build_armour(self) -> None:
        key = None if self.group == "blunt" else self.group
        a = self.shop["armour"][key]
        p = self.profile
        look = self.shop["ahead"]
        now = self.shop["now"]["taken_by"]
        what = {"blunt": "blunt attackers (Crossroads enemies), where every resist counts",
                "any": "anything, by defence alone"}.get(self.group, f"{self.group} attackers ({self.group} resist counts)")
        self.about.setText(f"Armour against {what}, ranked by what counts there; damage taken is a hit from a level "
                           f"{p.level} enemy, as if you wore the piece now with the rest of your gear (never below "
                           f"10 % of the enemy's power in this model: MQReborn's real minimum is unknown). ★ no other "
                           f"is cheaper, stronger and usable sooner at once. Up to level {p.level + look}, then the "
                           f"next ones as \"later\". Click a row for details and how to get it.")

        def taken(tb: dict, ref: dict | None = None) -> str:
            cols = [self.group] if self.group in ELEMENTS else []
            cols += [None, "mix"]
            names = {None: "blunt", "mix": "where you fight"}
            bits = [f"{c('def', f'{tb[el]:,.0f}')} from {names.get(el, el)}" for el in cols]
            text = "takes " + ", ".join(bits)
            if ref:
                text += " " + grey("(now " + ", ".join(f"{ref[el]:,.0f}" for el in cols) + ")")
            return text
        s = a["set"]
        picks = [(slot, it) for slot, it in s["picks"].items() if it]
        new = [(slot, it) for slot, it in picks if not p.owned.get(it["prefab"])]
        lines = [taken(s["taken_by"], now)]
        if new:
            lines.append(f"<b>{duration(s['hours'])}</b> to get · " + ", ".join(f"{slot}: {it.get('name')}" for slot, it in new))
        else:
            lines.append("Nothing in the lists beats what you wear.")
        self.header(f"<span style='font-family:GROBOLD; font-size:18px; color:#ffd54f'>Best set</span> "
                    f"<span style='color:{COLOURS.get(self.group, GREY)}'>against {dict(GROUPS)[self.group].lower()}</span>", lines, new)
        for label in ("Hat", "Body", "Legs", "Backpack"):
            rows = a["slots"].get(label, [])
            have = self.now_picks.get(label)
            self.section(label, f"now: {have.get('name')}" if have else "now: nothing")
            if rows:
                self.rows(rows, label, lambda r: taken(r["taken_by"], now))
            else:
                self.note(f"Nothing beats your {label.lower()} here up to level {p.level + look}.")
            self.missing(a["missing"].get(label, []))
