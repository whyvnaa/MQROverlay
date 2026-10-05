"""Build mode's Progression view: the best gear at every level, without any guess at how fast you level.

- direction: the tribe your badge is in (its element's weapons get the badge damage, so the best weapons change with
  it), or Auto: at every level the tribe whose set kills fastest (switching is free; a Badge lane shows which);
  under the level's numbers what each tribe's best set reaches at that level;
- three lists next to the badge chips: effort per item (a hard limit, off by default), when an item is replaced
  (the search over all levels: a change must pay over the levels you keep the item) and whether time to get
  counts (off by default). The utility slots of your hotbar (Stun, Heal, ...) get lanes too. Items nobody knows how to get join in when Build mode's "No known way" source is on
  (dashed bars);
- the timeline: one lane per slot over levels 1 to 60, a bar per item from the level it becomes the best to the
  level something replaces it (Planner.progression). A click picks a level, a click on a bar also opens its card;
- everything under the choices scrolls together. The level's card: that level's set with its numbers, then per slot the best item and every other one you could
  wear there (Planner.stage), each with what it costs you against the best, how hard it is to get and the way;
  📍 jumps to the place on the map.

No game logic here: everything comes from build_planner.py."""

import math

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (QApplication, QButtonGroup, QComboBox, QFrame, QHBoxLayout, QLabel, QPushButton,
                               QScrollArea, QSizePolicy, QToolTip, QVBoxLayout, QWidget)

from .build_planner import DEFENCE_SLOTS, SLOT_NAMES, TRIBE_ELEMENT, effort
from .builder import duration, way_short
from .item_card import COLOURS, c, stats_html
from .shop_list import GREY, TRIBE_NAMES, Row, chip, clear, grey, secs

AUTO = "Auto"
REAL_TRIBES = ["Shadow", "Bone", "Outlaw", "Wild", "Grease", "Crossroads"]
TRIBES = [AUTO] + REAL_TRIBES
EFFORTS = [(None, "Any effort"), (1.0, "Up to 1 h an item"), (3.0, "Up to 3 h an item"), (10.0, "Up to 10 h an item"),
           (30.0, "Up to 30 h an item")]
# what a change of an item must bring, in percent of strength times levels (Planner.progression's switch_cost)
SWITCHES = [(0.0, "Every upgrade"), (5.0, "Small upgrades too"), (15.0, "Clear upgrades"), (40.0, "Big upgrades only")]
# what an hour of getting an item weighs, in the same unit (hour_cost)
TIMES = [(0.0, "Time is irrelevant"), (1.0, "Time counts a little"), (4.0, "Time counts"), (15.0, "Time counts a lot")]
ARMOUR = {SLOT_NAMES[s] for s in DEFENCE_SLOTS}
SHOWN = 4  # alternatives on show per slot before "Show all"
BANANA = QColor("#ffd54f")


class Timeline(QWidget):
    """One lane per slot, a bar per item over the levels it is the best for (and a Badge lane when it changes)."""
    levelPicked = Signal(int)
    itemClicked = Signal(str, int, str)  # prefab, level, slot label

    LEFT, TOP, LANE = 78, 24, 30

    def __init__(self, icon_for):
        super().__init__()
        self.icon_for = icon_for
        self.prog, self.level, self.mine, self.owned, self.rows = None, 1, 1, {}, []
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(self.TOP + 9 * self.LANE + 8)

    def set_data(self, prog: dict, level: int, mine: int, owned: dict) -> None:
        self.prog, self.level, self.mine, self.owned = prog, level, mine, owned
        self.rows = ([("Badge", prog["badges"])] if prog["tribe"] == AUTO else []) + list(prog["lanes"].items())
        self.setFixedHeight(self.TOP + len(self.rows) * self.LANE + 8)
        self.update()

    def span(self) -> tuple[int, int, float]:
        lo, hi = self.prog["lo"], self.prog["hi"]
        return lo, hi, (self.width() - self.LEFT - 6) / (hi - lo + 1)

    def x(self, level: float) -> float:
        lo, _, step = self.span()
        return self.LEFT + (level - lo) * step

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 90))
        p.drawRoundedRect(QRectF(0, 0, self.width(), self.height()), 8, 8)
        if not self.prog:
            return
        lo, hi, step = self.span()
        bottom = self.TOP + len(self.rows) * self.LANE
        small = QFont(self.font())
        small.setPixelSize(11)
        p.setFont(small)
        for lv in range(lo, hi + 1):  # the level axis
            if lv % 5 == 0 or lv == lo:
                p.setPen(QColor(169, 191, 142))
                p.drawText(QRectF(self.x(lv), 2, step * 3, 14), Qt.AlignmentFlag.AlignLeft, str(lv))
                p.setPen(QPen(QColor(169, 191, 142, 40), 1))
                p.drawLine(int(self.x(lv)), self.TOP - 4, int(self.x(lv)), bottom)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 213, 79, 200))
        for lv in self.prog["changes"]:  # where the set changes
            p.drawRect(QRectF(self.x(lv), self.TOP - 6, max(step - 1, 1), 3))
        p.setBrush(QColor(255, 255, 255, 34))  # the level on show
        p.drawRect(QRectF(self.x(self.level), self.TOP - 6, step, bottom - self.TOP + 8))
        for i, (label, lane) in enumerate(self.rows):
            y = self.TOP + i * self.LANE
            p.setPen(QColor("#f3ead2"))
            p.drawText(QRectF(8, y, self.LEFT - 12, self.LANE), Qt.AlignmentFlag.AlignVCenter, label)
            for seg in lane:
                r = QRectF(self.x(seg["from"]) + 0.5, y + 3, (seg["to"] - seg["from"] + 1) * step - 1.5, self.LANE - 6)
                if "tribe" in seg:  # the Badge lane
                    colour = QColor(COLOURS.get(TRIBE_ELEMENT.get(seg["tribe"]), "#a9a48f"))
                    p.setPen(QPen(colour, 1))
                    p.setBrush(QColor(colour.red(), colour.green(), colour.blue(), 110))
                    p.drawRoundedRect(r, 4, 4)
                    if r.width() > 30:
                        p.setPen(QColor("#f3ead2"))
                        text = p.fontMetrics().elidedText(seg["tribe"], Qt.TextElideMode.ElideRight, int(r.width() - 8))
                        p.drawText(r.adjusted(5, 0, 0, 0), Qt.AlignmentFlag.AlignVCenter, text)
                    continue
                it = seg["item"]
                colour = QColor(COLOURS.get(it.get("element"), "#a9a48f"))
                owned = bool(self.owned.get(it["prefab"]))
                pen = QPen(BANANA if owned else colour, 2 if owned else 1)
                if math.isinf(seg["hours"]):  # nobody knows how to get it
                    pen.setStyle(Qt.PenStyle.DashLine)
                p.setPen(pen)
                p.setBrush(QColor(colour.red(), colour.green(), colour.blue(), 70))
                p.drawRoundedRect(r, 4, 4)
                left = r.left() + 2
                size = int(min(20, r.width() - 3))
                if size >= 8:  # a narrow bar still gets a small icon
                    self.icon_for(it["prefab"]).paint(p, int(left), int(y + (self.LANE - size) / 2), size, size)
                    left += size + 3
                if r.right() - left > 34:
                    p.setPen(QColor("#f3ead2"))
                    text = p.fontMetrics().elidedText(it["name"], Qt.TextElideMode.ElideRight, int(r.right() - left - 3))
                    p.drawText(QRectF(left, y, r.right() - left, self.LANE), Qt.AlignmentFlag.AlignVCenter, text)
        if lo <= self.mine <= hi:  # you
            p.setPen(QPen(BANANA, 2))
            mx = self.x(self.mine + 0.5)
            p.drawLine(int(mx), self.TOP - 8, int(mx), bottom + 2)

    def at(self, pos) -> tuple[int | None, str | None, dict | None]:
        if not self.prog or pos.x() < self.LEFT:
            return None, None, None
        lo, hi, step = self.span()
        level = max(lo, min(hi, lo + int((pos.x() - self.LEFT) / step)))
        i = int((pos.y() - self.TOP) // self.LANE)
        if 0 <= i < len(self.rows) and pos.y() >= self.TOP:
            for seg in self.rows[i][1]:
                if seg["from"] <= level <= seg["to"]:
                    return level, self.rows[i][0], seg
        return level, None, None

    def mouseMoveEvent(self, event) -> None:
        level, label, seg = self.at(event.position())
        if seg:
            span = f"level {seg['from']}" + (f" to {seg['to']}" if seg["to"] > seg["from"] else "")
            if "tribe" in seg:
                text = f"Badge in {seg['tribe']}: {span}"
            else:
                it = seg["item"]
                have = ("you have it" if self.owned.get(it["prefab"]) else "no known way to get it"
                        if math.isinf(seg["hours"]) else f"{duration(seg['hours'])} to get")
                text = f"{label}: {it['name']}\nBest from {span} · {have}"
            QToolTip.showText(event.globalPosition().toPoint(), text, self)
        elif level:
            QToolTip.showText(event.globalPosition().toPoint(), f"Level {level}", self)

    def mousePressEvent(self, event) -> None:
        level, label, seg = self.at(event.position())
        if level:
            self.levelPicked.emit(level)
            if seg and "item" in seg:
                self.itemClicked.emit(seg["item"]["prefab"], level, label)


class Progression(QWidget):
    itemClicked = Signal(str, int, str)  # prefab, level, slot label
    placeClicked = Signal(dict)
    changed = Signal()  # an option or the level picked: Build mode saves them

    def __init__(self, icon_for, crest_for, tribe: str | None = None, effort: float | None = None, switch: float = 5.0,
                 level: int | None = None, time: float = 0.0):
        """icon_for(prefab), crest_for(tribe) -> QIcon."""
        super().__init__()
        self.icon_for = icon_for
        self.tribe, self.effort, self.switch, self.level, self.time, self.unknown = tribe, effort, switch, level, time, False
        self.utility: tuple[str, ...] = ()
        self.planner = self.costs = self.profile = self.prices = self.prog = None
        self.now, self.where, self.open, self.cache = {}, lambda level: "", set(), {}
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)
        row = QHBoxLayout()  # the one row of choices: the badge, then three lists
        row.setSpacing(3)
        row.addWidget(QLabel("<b>Badge</b>"))
        self.tribe_buttons = self.chips(row, [(t, t) for t in TRIBES], self.set_tribe, lambda t: (
            "At every level the tribe whose best set kills fastest (switching tribes is free)" if t == AUTO else
            f"All skill points in {t} ({TRIBE_NAMES[t]}): {TRIBE_ELEMENT[t]} weapons get the badge damage"
            if t in TRIBE_ELEMENT else "No badge: blunt weapons only get what your accessories add"))
        for t, b in self.tribe_buttons.items():
            if t != AUTO:
                b.setIcon(crest_for(t))
                b.setIconSize(QSize(18, 18))
        row.addStretch(1)
        self.effort_box = self.combo(row, EFFORTS, self.set_effort,
                                     "Leave out items that take longer than this to get")
        self.switch_box = self.combo(row, SWITCHES, self.set_switch, (
            "When an item is replaced. The search looks at all levels at once: a new item must make up for the "
            "change over the levels you keep it (small: 5 % better for one level or 1 % for five; clear: three "
            "times that; big: eight times). \"Every upgrade\" shows the strongest set of every level"))
        self.time_box = self.combo(row, TIMES, self.set_time, (
            "Whether the hours it takes to get an item count. Irrelevant: only strength decides. Otherwise an item "
            "must also earn its hours over the levels you keep it"))
        v.addLayout(row)
        scroll = QScrollArea()  # everything below scrolls together: the timeline, the level's card
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        inner = QWidget()
        page = QVBoxLayout(inner)
        page.setContentsMargins(0, 0, 8, 0)
        page.setSpacing(6)
        scroll.setWidget(inner)
        v.addWidget(scroll, 1)
        self.timeline = Timeline(icon_for)
        self.timeline.levelPicked.connect(self.set_level)
        self.timeline.itemClicked.connect(self.itemClicked.emit)
        page.addWidget(self.timeline)
        self.head = QLabel("Working out your gear…")
        self.head.setTextFormat(Qt.TextFormat.RichText)
        self.head.setWordWrap(True)
        page.addWidget(self.head)
        self.compare = QLabel(objectName="sub")
        self.compare.setTextFormat(Qt.TextFormat.RichText)
        self.compare.setWordWrap(True)
        page.addWidget(self.compare)
        self.body = QHBoxLayout()  # two columns: weapons and accessories, armour
        self.body.setSpacing(10)
        page.addLayout(self.body)
        page.addStretch(1)

    def combo(self, row: QHBoxLayout, options: list[tuple], pick, tip: str) -> QComboBox:
        box = QComboBox()
        for key, text in options:
            box.addItem(text, key)
        box.setToolTip(tip)
        box.activated.connect(lambda i: pick(box.itemData(i)))
        row.addWidget(box)
        return box

    @staticmethod
    def select(box: QComboBox, key) -> None:
        for i in range(box.count()):
            if box.itemData(i) == key:
                box.setCurrentIndex(i)

    def chips(self, row: QHBoxLayout, options: list[tuple], pick, tip) -> dict:
        """A row of chips of which one is on: {key: button}."""
        group = QButtonGroup(self)
        buttons = {}
        for key, text in options:
            b = chip(text)
            b.setToolTip(tip(key))
            group.addButton(b)
            buttons[key] = b
            b.clicked.connect(lambda _=False, k=key: pick(k))
            row.addWidget(b)
        return buttons

    # ---------------------------------------------------------------- state

    def set_data(self, planner, costs, profile, prices: dict, now: dict, where, unknown: bool = False,
                 utility: tuple[str, ...] = ()) -> None:
        """planner, costs, profile: Build mode's; prices: Planner.price_table(); now: what you wear (slot -> item);
        where(level): who the numbers are against at that level, in words."""
        self.planner, self.costs, self.profile, self.prices, self.now, self.where = planner, costs, profile, prices, now, where
        self.cache, self.unknown, self.utility = {}, unknown, tuple(utility)
        if self.tribe not in TRIBES:
            self.tribe = AUTO
        if self.effort not in dict(EFFORTS):
            self.effort = None
        self.switch = min((g for g, _ in SWITCHES), key=lambda g: abs(g - self.switch))
        self.time = min((g for g, _ in TIMES), key=lambda g: abs(g - self.time))
        if not self.level:
            self.level = profile.level
        self.tribe_buttons[self.tribe].setChecked(True)
        self.select(self.effort_box, self.effort)
        self.select(self.switch_box, self.switch)
        self.select(self.time_box, self.time)
        self.compute()

    def set_tribe(self, tribe: str) -> None:
        self.tribe = tribe
        self.tribe_buttons[tribe].setChecked(True)
        self.refresh()

    def set_effort(self, hours: float | None) -> None:
        self.effort = hours
        self.select(self.effort_box, hours)
        self.refresh()

    def set_switch(self, cost: float) -> None:
        self.switch = cost
        self.select(self.switch_box, cost)
        self.refresh()

    def set_time(self, cost: float) -> None:
        self.time = cost
        self.select(self.time_box, cost)
        self.refresh()

    def refresh(self) -> None:
        self.compute()
        self.changed.emit()

    def set_level(self, level: int) -> None:
        self.level = max(1, min(60, level))
        if self.prog:
            self.timeline.set_data(self.prog, self.level, self.profile.level, self.profile.owned)
            self.show_stage()
        self.changed.emit()

    def compute(self) -> None:
        if not self.planner:
            return
        key = (self.tribe, self.effort, self.switch, self.time, self.unknown, self.utility)
        if key not in self.cache:  # Auto takes about a second: say so
            self.head.setText("Working out the best gear for every level…")
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            QApplication.processEvents()
            try:
                self.cache[key] = self.planner.progression(self.profile, self.tribe, self.effort, self.prices,
                                                           switch_cost=self.switch, hour_cost=self.time, unknown=self.unknown,
                                                           utility=self.utility)
            finally:
                QApplication.restoreOverrideCursor()
        self.prog = self.cache[key]
        self.timeline.set_data(self.prog, self.level, self.profile.level, self.profile.owned)
        self.show_stage()

    # ---------------------------------------------------------------- the level's card

    def show_stage(self) -> None:
        pl, p, level = self.planner, self.profile, self.level
        row = self.prog["levels"][level - self.prog["lo"]]
        picks, tribe = row["picks"], row["badge_tribe"]
        stage = pl.stage(p, tribe, level, picks, self.prices, self.effort)
        bits = []
        for t in REAL_TRIBES:  # each tribe's best set at this level
            one = pl.progression(p, t, self.effort, self.prices, lo=level, hi=level, switch_cost=0,
                                 unknown=self.unknown)["levels"][0]
            text = f"{t} {secs(one['kill_time'])} (" + " + ".join(format(h["hit"], ",.0f") for h in one["hits"].values()) + ")"
            bits.append(f"<b style='color:#ffd54f'>{text}</b>" if t == tribe else text)
        self.compare.setText(f"Each badge's best set at level {level}, against {self.where(level)}: kill time (hit per "
                             f"hotbar weapon): " + " · ".join(bits))
        el = TRIBE_ELEMENT.get(tribe)
        dmg, dfn = row["badge"]
        badge = (f"badge level {row['points'] // 5}: {c(el, f'+{dmg} {el} damage')}, {c('def', f'+{dfn} defence')}"
                 if el and dmg else "no badge bonus")
        hits = " · ".join(f"{k} {c('dmg', format(h['hit'], ',.0f'))} × {h['hits']}" for k, h in row["hits"].items())
        new = [it["name"] for k, it in picks.items()
               if level > self.prog["lo"] and self.prog["levels"][level - self.prog["lo"] - 1]["picks"].get(k) is not it]
        missing = [k for k, it in picks.items() if not p.owned.get(it["prefab"])]
        lost = [k for k in missing if math.isinf(row["hours"][k])]
        todo = sum(row["hours"][k] for k in missing if k not in lost)
        get = (f"{len(missing)} of {len(picks)} pieces to get, {duration(todo)} in all"
               + (f" plus {len(lost)} with no known way" if lost else "")) if missing else "you have every piece"
        lines = [f"<span style='font-family:GROBOLD; font-size:18px; color:#ffd54f'>Level {level}</span> &nbsp;"
                 + ("Best badge: " if self.tribe == AUTO else "") + f"{tribe}, {badge}",
                 f"Kills in <b>{secs(row['kill_time'])}</b> ({hits}) · takes <b>{row['damage_taken']:,.0f}</b> a hit · {get}"]
        if level == p.level and self.now:
            mine = pl.evaluate(self.now, pl.at_level(p, level), tribe=tribe)
            lines.append(grey(f"What you wear now: kills in {secs(mine['kill_time'])}, takes {mine['damage_taken']:,.0f} a hit"))
        if new:
            lines.append(grey("New at this level: " + ", ".join(new)))
        self.head.setText("<br>".join(lines))
        clear(self.body)
        cols = []
        for _ in range(2):
            col = QVBoxLayout()
            col.setSpacing(5)
            self.body.addLayout(col, 1)
            cols.append(col)
        for label, rows in stage["slots"].items():
            self.slot(cols[label in ARMOUR], label, rows)
        for slot, held in row["utility"].items():
            self.utility_slot(cols[0], slot, held, pl.utility(pl.at_level(p, level), picks, (slot,), tribe=tribe)[slot])
        for col in cols:
            col.addStretch(1)

    def slot(self, body: QVBoxLayout, label: str, rows: list[dict]) -> None:
        ways = [r for r in rows if r["hours"] is not None]
        none = [r for r in rows if r["hours"] is None]
        lab = QLabel(f"{label} <span style='font-family:Nunito; font-size:11px; color:{GREY}'>"
                     f"{len(ways)} to choose from" + (f", {len(none)} more with no known way" if none else "") + "</span>",
                     objectName="section")
        lab.setTextFormat(Qt.TextFormat.RichText)
        body.addWidget(lab)
        if not rows:
            body.addWidget(QLabel(grey("Nothing to wear here at this level."), textFormat=Qt.TextFormat.RichText))
            return
        ref = next((r for r in rows if r["best"]), None)
        order = rows if self.unknown else ways + none  # unknown sources off: those come last
        shown = order if label in self.open else order[:SHOWN]
        for r in shown:
            body.addWidget(self.row(label, r, ref))
        if len(order) > SHOWN:
            b = QPushButton(f"Show fewer {label.lower()} items" if label in self.open else
                            f"Show all {len(order)} {label.lower()} items", objectName="small")
            b.clicked.connect(lambda _=False, k=label: self.toggle(k))
            body.addWidget(b)

    def utility_slot(self, body: QVBoxLayout, slot: str, held: dict, rows: list[dict]) -> None:
        """A utility slot of the hotbar at this level: the item the lane holds first, then the others no other
        beats on hours and effect (strongest first), each with what it does together with this level's set."""
        lab = QLabel(f"{slot} <span style='font-family:Nunito; font-size:11px; color:{GREY}'>with this level's set</span>",
                     objectName="section")
        lab.setTextFormat(Qt.TextFormat.RichText)
        body.addWidget(lab)
        order = [held] + [r for r in reversed(rows) if r["item"] is not held["item"]]
        for r in order:
            it = r["item"]
            owned = bool(self.profile.owned.get(it["prefab"]))
            way = self.costs.best(it["prefab"], self.profile)
            tags = (["<span style='color:#ffd54f'>★ best</span>"] if r is held else []) + (
                [c("gain", "you have it")] if owned else []) + [grey(f"level {it['level_req'] or 1}")]
            right = c("gain", "have") if owned else f"<b>{duration(r['hours'])}</b>"
            w = Row(self.icon_for(it["prefab"]), f"<b>{it['name']}</b> " + " · ".join(tags), right,
                    [r["text"], grey(way_short(way)) if way is not None and way.kind != "owned" else ""])
            w.clicked.connect(lambda p=it["prefab"]: self.itemClicked.emit(p, self.level, ""))
            body.addWidget(w)

    def toggle(self, label: str) -> None:
        (self.open.discard if label in self.open else self.open.add)(label)
        self.show_stage()

    def row(self, label: str, r: dict, ref: dict | None) -> Row:
        it, p = r["item"], self.profile
        tags = []
        if r["best"]:
            tags.append("<span style='color:#ffd54f'>★ best</span>")
        if self.now.get(label) is it:
            tags.append(c("gain", "you wear it"))
        elif r["owned"]:
            tags.append(c("gain", "you have it"))
        if r["over"]:
            tags.append(grey("over your effort limit"))
        tags.append(grey(f"level {it['level_req'] or 1}"))
        way = None if r["hours"] is None else self.costs.best(it["prefab"], p)
        kind, grade = effort(way, r["hours"])
        if r["owned"]:
            right = c("gain", "have")
        elif r["hours"] is None:
            right = c("loss", "no known way")
        else:
            right = f"<b>{duration(r['hours'])}</b> {grey(kind)}"
        if label in ARMOUR:
            line = f"takes {r['damage_taken']:,.0f} a hit"
            if ref and not r["best"]:
                d = r["damage_taken"] - ref["damage_taken"]
                line += " " + (grey("same as the best") if abs(d) < 0.5 else c("loss" if d > 0 else "gain", f"{d:+,.0f}"))
        else:
            cls = label.lower() if label in ("Melee", "Ranged") else None
            parts = [f"{k} {h['hit']:,.0f} × {h['hits']}" for k, h in r["hits"].items() if cls in (None, k)]
            line = "hits " + " · ".join(parts) + f" · kills in {secs(r['kill_time'])}"
            if ref and not r["best"] and ref["smooth"] > 0:
                d = r["smooth"] / ref["smooth"] - 1
                line += " " + (grey("as fast as the best") if abs(d) < 0.005
                               else c("loss" if d > 0 else "gain", f"{abs(d) * 100:.0f} % {'slower' if d > 0 else 'faster'}"))
        how = ""
        if way is not None and way.kind != "owned":
            how = grey((f"{grade}: " if grade else "") + way_short(way))
        place = None
        if way is not None and way.where and way.where[0].get("zone"):
            place = dict(way.where[0])
            if way.kind in ("chest", "enemy", "tribe_drop"):
                place["search"] = it["name"]
        w = Row(self.icon_for(it["prefab"]), f"<b>{it['name']}</b> " + " · ".join(tags), right,
                [stats_html(it) + grey(" · ") + line, how], pin="Show on the map" if place else "")
        w.clicked.connect(lambda p=it["prefab"], k=label: self.itemClicked.emit(p, self.level, k))
        if place:
            w.pinned.connect(lambda pl=place: self.placeClicked.emit(pl))
        return w
