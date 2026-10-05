"""The item card of the Build tab: an item in the game's words (stats, effects, description), what it adds to your
build compared with what you have in that slot now, how to get it, and the other upgrades for that slot."""

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from .builder import duration

COLOURS = {"dmg": "#ffab61", "def": "#7cc4ff", "t": "#b8c7cf", "hp": "#8fd694", "gain": "#a5d66b", "loss": "#ff8a80",
           "Air": "#c9b8ff", "Earth": "#b8d47a", "Fire": "#ff8a5c", "Ice": "#8ee3f0", "Lightning": "#ffe36b"}
RARITY = {"Common": "#d9d9d9", "Uncommon": "#8fd694", "Rare": "#7cc4ff", "Epic": "#c9a0ff", "Legendary": "#ffb74d"}


def c(kind: str, text) -> str:
    return f'<span style="color:{COLOURS.get(kind, "#f3ead2")}">{text}</span>'


def stats_html(it: dict) -> str:
    """The stats in the game's words: "165 blunt damage · 62 Air damage · cooldown 0.8 s"."""
    el = it.get("element")
    bits = []
    if it.get("is_weapon") or it.get("slot") in ("Ears", "Wrist", "Tail"):
        if it.get("scaled_blunt"):
            bits.append(c("dmg", f"{it['scaled_blunt']} blunt damage"))
        if it.get("scaled_element") and el:
            bits.append(c(el, f"{it['scaled_element']} {el} damage"))
        if it.get("cooldown") and it.get("is_weapon"):
            bits.append(c("t", f"cooldown {it['cooldown']:g} s"))
    else:
        if it.get("scaled_defence"):
            bits.append(c("def", f"defence {it['scaled_defence']}"))
        if it.get("scaled_resist") and el:
            bits.append(c(el, f"{el} resist {it['scaled_resist']}"))
    return " · ".join(bits)


def diff(now: float, new: float, fmt: str, lower_is_better: bool = False) -> str:
    """"220 → 562 (+342)" with the change coloured."""
    if abs(new - now) < 1e-9:
        return f"{fmt.format(now)} <span style='color:#a9bf8e'>same</span>"
    better = (new < now) if lower_is_better else (new > now)
    sign = "+" if new > now else "−"
    return f"{fmt.format(now)} → {c('gain' if better else 'loss', fmt.format(new))} " \
           f"<span style='color:#a9bf8e'>({sign}{fmt.format(abs(new - now))})</span>"


class ItemCard(QWidget):
    back = Signal()
    openItem = Signal(str)  # another item's card (other upgrades for the slot)
    excludeClicked = Signal(str)  # the item's prefab: leave it out of every list, or take it back in

    def __init__(self, icon_for, fill_ways, back_text: str = "← Back"):
        """icon_for(prefab) -> QIcon; fill_ways(tree root item, item, level) adds the ways to get it."""
        super().__init__()
        self.icon_for, self.fill_ways = icon_for, fill_ways
        self.prefab: str | None = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 4, 0, 0)
        top = QHBoxLayout()
        self.exclude = QPushButton(objectName="small")
        self.exclude.clicked.connect(lambda: self.prefab and self.excludeClicked.emit(self.prefab))
        top.addWidget(self.exclude)
        top.addStretch(1)
        back = QPushButton(back_text, objectName="small")
        back.clicked.connect(self.back.emit)
        top.addWidget(back)
        outer.addLayout(top)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        self.lay = QVBoxLayout(body)
        self.lay.setContentsMargins(2, 2, 6, 2)
        self.lay.setSpacing(6)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        head = QHBoxLayout()
        self.pic = QLabel()
        self.pic.setFixedSize(52, 52)
        head.addWidget(self.pic, 0, Qt.AlignmentFlag.AlignTop)
        names = QVBoxLayout()
        self.name = QLabel(objectName="title")
        self.name.setStyleSheet("font-size: 20px;")
        self.name.setWordWrap(True)
        self.kind = QLabel(objectName="sub")
        self.kind.setWordWrap(True)
        names.addWidget(self.name)
        names.addWidget(self.kind)
        head.addLayout(names, 1)
        self.lay.addLayout(head)
        self.stats = QLabel()
        self.stats.setWordWrap(True)
        self.stats.setTextFormat(Qt.TextFormat.RichText)
        self.lay.addWidget(self.stats)
        self.desc = QLabel()
        self.desc.setWordWrap(True)
        self.desc.setStyleSheet("color: #d8cfb4; font-style: italic;")
        self.lay.addWidget(self.desc)
        self.lay.addWidget(QLabel("What it adds to you", objectName="section"))
        self.adds = QLabel()
        self.adds.setTextFormat(Qt.TextFormat.RichText)
        self.adds.setWordWrap(True)
        self.lay.addWidget(self.adds)
        self.lay.addWidget(QLabel("How to get it", objectName="section"))
        self.ways = QTreeWidget()
        self.ways.setHeaderHidden(True)
        self.ways.setIndentation(14)
        self.ways.setIconSize(QSize(22, 22))
        self.ways.setWordWrap(True)
        self.ways.setMinimumHeight(170)
        self.lay.addWidget(self.ways)
        self.other_title = QLabel(objectName="section")
        self.lay.addWidget(self.other_title)
        self.others = QVBoxLayout()
        self.others.setSpacing(2)
        self.lay.addLayout(self.others)
        self.lay.addStretch(1)

    def set_excluded(self, excluded: bool) -> None:
        self.exclude.setText("↩ Include again" if excluded else "🚫 Exclude")
        self.exclude.setToolTip("Excluded: nothing suggests this item. Click to take it back in" if excluded else
                                "Don't suggest this item any more: the progression, the shop list and the upgrades "
                                "leave it out (the left column lists what you excluded)")

    def show_item(self, item: dict, level: int, explain: dict | None, others: list[dict], now_level: int,
                  excluded: bool = False) -> None:
        """explain: Planner.explain() at `level`; others: slot_upgrades rows for the item's slot."""
        self.prefab = item["prefab"]
        self.set_excluded(excluded)
        icon = self.icon_for(item["prefab"])
        self.pic.setPixmap(icon.pixmap(48, 48) if not icon.isNull() else QPixmap())
        self.name.setText(item.get("name") or item["prefab"])
        rarity = item.get("rarity")
        kind = [f"Level {item.get('level_req') or 1}"]
        if rarity:
            kind.append(f"<span style='color:{RARITY.get(rarity, '#d9d9d9')}'>{rarity}</span>")
        if item.get("slot"):
            kind.append(item["slot"] + (" (thrown)" if item.get("action_type") == "Throw" else
                                        " (damage zone)" if item.get("action_type") == "DamageZone" else ""))
        if item.get("element"):
            kind.append(c(item["element"], item["element"]))
        if item.get("tribe") and item.get("tribe") != "Crossroads":
            kind.append(item["tribe"])
        self.kind.setText(" · ".join(kind))
        stats = stats_html(item)
        effects = [c("hp", e) for e in item.get("effects", [])]
        self.stats.setText("<br>".join(x for x in [stats, " · ".join(effects)] if x) or "No stats")
        self.desc.setText(item.get("description") or "")
        self.desc.setVisible(bool(item.get("description")))
        self.adds.setText(self.adds_html(item, level, explain, now_level))
        self.ways.clear()
        self.fill_ways(self.ways.invisibleRootItem(), item, level)
        self.ways.expandToDepth(0)
        while self.others.count():
            w = self.others.takeAt(0).widget()
            if w:
                w.deleteLater()
        rows = [r for r in others if r["item"]["prefab"] != item["prefab"]]
        self.other_title.setText(f"Other {item.get('slot', '').lower()} upgrades" if rows else "")
        self.other_title.setVisible(bool(rows))
        for r in rows:
            when = "now" if r["level"] <= now_level else f"level {r['level']}"
            b = QPushButton(f"{r['item'].get('name')} · +{r['gain'] * 100:.0f} % · {duration(r['hours'])} · {when}",
                            objectName="toggle")
            b.setIcon(self.icon_for(r["item"]["prefab"]))
            b.setIconSize(QSize(20, 20))
            b.clicked.connect(lambda _=False, p=r["item"]["prefab"]: self.openItem.emit(p))
            self.others.addWidget(b)

    @staticmethod
    def adds_html(item: dict, level: int, x: dict | None, now_level: int) -> str:
        if not x:
            return "<span style='color:#a9bf8e'>Not part of the damage and defence model (a utility item).</span>"
        now, new = x["now"], x["with"]
        slot = item.get("slot") or ""
        had = now.get("item")
        rows = [("In this slot now", f"{had.get('name') if had else 'nothing'}", "")]
        cls = slot.lower() if slot in ("Melee", "Ranged") else None
        for k in ([cls] if cls else []) + [k for k in now["hits"] if k != cls]:
            if k in now["hits"] and k in new["hits"]:
                a, b = now["hits"][k], new["hits"][k]
                rows.append((f"Your {k} hit", diff(a["hit"], b["hit"], "{:,.0f}"), ""))
                rows.append((f"Hits to kill ({k})", diff(a["hits"], b["hits"], "{:.0f}", True), ""))
        rows.append(("Kill time", diff(now["kill_time"], new["kill_time"], "{:.1f} s", True), ""))
        for el, t in now["taken_by"].items():
            label = f"Damage taken ({el or 'blunt'})" if len(now["taken_by"]) > 1 else "Damage taken a hit"
            rows.append((label, diff(t, new["taken_by"][el], "{:,.0f}", True), ""))
        gain = new["strength"] / now["strength"] - 1 if now["strength"] else 0
        rows.append(("Strength", diff(now["strength"], new["strength"], "{:.2f}×")
                     + f" {c('gain' if gain > 0 else 'loss', f'{gain * 100:+.0f} %')}", ""))
        if new.get("tribe") != now.get("tribe"):
            rows.append(("Best tribe", f"{now.get('tribe') or '-'} → {new.get('tribe') or '-'}", ""))
        head = (f"<span style='color:#a9bf8e'>Against level {level} enemies"
                + ("" if level == now_level else f" (you can use it from level {level})") + ":</span>")
        body = "".join(f"<tr><td style='color:#a9bf8e; padding-right:10px'>{a}</td><td>{b}</td></tr>" for a, b, _ in rows)
        return head + f"<table cellspacing='0' cellpadding='2'>{body}</table>"
