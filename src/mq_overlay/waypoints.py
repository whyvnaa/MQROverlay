"""Waypoints, like the game's arrow for a tracked quest: you pick a marker or a spot on the map (in any zone), and an
arrow around your monkey points the way. In the waypoint's zone it points at the waypoint; anywhere else at the portal
that leads toward that zone (the fewest portals, from the zones' portal markers).

The front and the back path: the game ships its own route data for its quest arrow (a NavMesh per zone: the areas of
each path you can move around in, exported as the zone's "nav"). A path is often cut into several areas, so the way
can go to the back, along it, and to the front again. Nav searches the bridges over these areas the way the game
does, and the arrow points at the next bridge to cross. Zones without that data: the bridge that makes the straight
way shortest when the target is on the other path.

The arrow is drawn in its own click-through window over the game. Where the monkey is on screen isn't known (the
game's camera follows it with some slack), so the arrow circles a point a little below the middle of the game window,
about where the monkey stands."""

import heapq
import math
from collections import deque

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QWidget

from .data import GameData

ARRIVED = 2.5  # units: closer than this, you are there
# marker tips whose name part is too long for a label (tip head -> label)
SHORT = {"Way between the front and back path": "Bridge", "Hazard": "Hazard"}


def short_name(tip: str) -> str:
    """A marker's name for labels: its tip without the extras after " · ", and without drop lists or internal names
    ("Chest: Fanged Mystic Belt 6.7 %, ..." -> "Chest", "Way between the front and back path: ..." -> "Bridge")."""
    name = tip.split(" · ")[0]
    head, sep, rest = name.partition(": ")
    if sep and (head in SHORT or any(c in rest for c in "%_,")):
        name = head
    return SHORT.get(name, name)
CROSS = 4.0  # units a bridge crossing counts as (so the way with fewer crossings wins when the lengths are close)
BRIDGE_REACH = 3.0  # a bridge links the areas at most this far from it
BANANA, EDGE = QColor("#ffd54f"), QColor("#5d4000")
TEXT, DIM = QColor("#fff6e0"), QColor("#e8dcb8")  # label: what the arrow points at, then distance and goal


class ZoneGraph:
    """Which zone's portals lead where (portal markers with "to", exported by the knowledge base)."""

    def __init__(self, data: GameData):
        self.data = data
        self.navs: dict[str, Nav] = {}
        self.links: dict[str, set[str]] = {}
        for key in data.zones:
            zone = data.zone(key)
            for m in zone["markers"] if zone else []:
                if m["cat"] == "portal" and m.get("to"):
                    self.links.setdefault(key, set()).add(m["to"].lower())

    def nav(self, zone: str) -> "Nav":
        """The game's areas of a zone (empty when it has none)."""
        key = zone.lower()
        if key not in self.navs:
            self.navs[key] = Nav(self.data.zone(zone))
        return self.navs[key]

    def path(self, here: str, there: str) -> list[str] | None:
        """Zones from here to there (both included, lower case), fewest portals; None if there is no way."""
        here, there = here.lower(), there.lower()
        prev, queue = {here: None}, deque([here])
        while queue:
            z = queue.popleft()
            if z == there:
                out = []
                while z is not None:
                    out.append(z)
                    z = prev[z]
                return out[::-1]
            for n in sorted(self.links.get(z, ())):
                if n not in prev:
                    prev[n] = z
                    queue.append(n)
        return None


class Nav:
    """The areas of one zone from the game's NavMesh (client NavMesh.cs): per path (0 front, 1 back) whole-unit points
    grouped into areas. Inside an area you get everywhere; "down" links lead one way into another area of the same
    path; a bridge joins the front area and the back area at its position (as the client's LinkNodeOnABridge).
    Empty (false) for a zone without the data, or where a bridge has no area on both sides: the game's data of a
    few zones is older than the zone (the starter zones, Crossroads town square, Trail01, the Sea Dragons teaser)."""

    def __init__(self, zone: dict | None):
        self.cells: list[dict[tuple[int, int], int]] = [{}, {}]  # per path: point -> area
        down: dict[int, list[int]] = {}
        for n in (zone or {}).get("nav") or []:
            down[n["key"]] = n["down"]
            pts = n["points"]
            for i in range(0, len(pts), 2):
                self.cells[n["plane"]][(pts[i], pts[i + 1])] = n["key"]
        self.reach: dict[int, set[int]] = {}  # area -> itself and every area its one-way links lead to
        for key in down:
            seen, todo = {key}, [key]
            while todo:
                for k in down.get(todo.pop(), ()):
                    if k not in seen and k in down:
                        seen.add(k)
                        todo.append(k)
            self.reach[key] = seen
        self.bridges: list[tuple[dict, tuple[int, int]]] = []  # (marker, (front area, back area))
        for m in (zone or {}).get("markers") or []:
            if m["cat"] == "bridge" and self.reach:
                at = (m["x"], m["y"])
                sides = (self.area(at, 0, BRIDGE_REACH), self.area(at, 1, BRIDGE_REACH))
                if None in sides:  # the data is of an older version of this zone (a few zones): don't trust it
                    self.reach, self.bridges = {}, []
                    break
                self.bridges.append((m, sides))

    def __bool__(self) -> bool:
        return bool(self.reach)

    def area(self, at: tuple[float, float], plane: int, within: float | None = None) -> int | None:
        """The area at a spot of a path: its point, else (in the air, on a ledge the data leaves out) the closest
        point of that path, at most `within` units away."""
        cells = self.cells[plane]
        x, y = int(at[0]), int(at[1])
        for cy in (y, int(at[1] + 0.5), y + 1, y - 1):  # the client's own tolerance
            if (x, cy) in cells:
                return cells[(x, cy)]
        if not cells:
            return None
        p = min(cells, key=lambda c: (c[0] - at[0]) ** 2 + (c[1] - at[1]) ** 2)
        return cells[p] if within is None or math.dist(p, at) <= within else None

    def route(self, me: tuple[float, float], plane: int, goal: tuple[float, float],
              goal_plane: int) -> tuple[float, dict | None] | None:
        """The shortest way from you to the goal over the areas and bridges: (length, the first bridge to cross or None
        when no bridge is needed); None when the bridges don't lead there."""
        start, end = self.area(me, plane), self.area(goal, goal_plane)
        if start is None or end is None:
            return None
        if plane == goal_plane and end in self.reach[start]:
            return math.dist(me, goal), None
        spot = [(m["x"], m["y"]) for m, _ in self.bridges]
        # (length so far, bridge just crossed, the path you are on now, the first bridge of this way)
        heap = [(math.dist(me, spot[i]) + CROSS, i, 1 - plane, i)
                for i, (_, sides) in enumerate(self.bridges) if sides[plane] in self.reach[start]]
        heapq.heapify(heap)
        done = set()
        best: tuple[float, dict | None] | None = None
        while heap:
            cost, i, side, first = heapq.heappop(heap)
            if best is not None and cost >= best[0]:
                break
            if (i, side) in done:
                continue
            done.add((i, side))
            reach = self.reach[self.bridges[i][1][side]]
            if side == goal_plane and end in reach:
                total = cost + math.dist(spot[i], goal)
                if best is None or total < best[0]:
                    best = (total, self.bridges[first][0])
            for j, (_, sides) in enumerate(self.bridges):
                if j != i and (j, 1 - side) not in done and sides[side] in reach:
                    heapq.heappush(heap, (cost + math.dist(spot[i], spot[j]) + CROSS, j, 1 - side, first))
        return best


def target(data: GameData, graph: ZoneGraph, here: str | None, waypoint: dict | None,
           me: tuple[float, float] | None, my_plane: int | None = None) -> dict | None:
    """What to point at in zone `here`: the waypoint itself, or the portal toward its zone, or first the next bridge
    to cross when the way there changes between the front and the back path (the game's areas, Nav; of several
    portals to the next zone the one with the shortest way). Without that data: the closest portal, and the bridge
    that makes the straight way shortest when the target is on the other path than you (my_plane).
    {"x", "y", "plane", "label", "goal", "final", "zone"}: label = what is pointed at, goal = the waypoint it leads
    to ("" when it is the waypoint); None without a waypoint or a way there."""
    goals = _goals(data, graph, here, waypoint, me)
    if not goals:
        return None
    nav = graph.nav(here) if me is not None and my_plane is not None else None
    if nav:
        best = None
        for g in goals:
            for plane in (0, 1) if g["plane"] is None else (g["plane"],):
                r = nav.route(me, my_plane, (g["x"], g["y"]), plane)
                if r and (best is None or r[0] < best[0]):
                    best = (r[0], r[1], g)
        if best and best[1] is None:
            return best[2]
        if best:
            side = "front" if my_plane == 1 else "back"
            return {"x": best[1]["x"], "y": best[1]["y"], "plane": None, "zone": here, "final": False,
                    "label": f"Bridge to the {side} path", "goal": best[2]["goal"] or best[2]["label"]}
    t = goals[0]
    if me is None or my_plane is None or t["plane"] is None or t["plane"] == my_plane:
        return t
    bridges = [m for m in data.zone(here)["markers"] if m["cat"] == "bridge"]
    if not bridges:
        return t
    b = min(bridges, key=lambda m: math.dist(me, (m["x"], m["y"])) + math.dist((m["x"], m["y"]), (t["x"], t["y"])))
    side = "back" if t["plane"] == 1 else "front"
    return {"x": b["x"], "y": b["y"], "plane": None, "zone": here, "final": False,
            "label": f"Bridge to the {side} path", "goal": t["goal"] or t["label"]}


def _goals(data: GameData, graph: ZoneGraph, here: str | None, waypoint: dict | None,
           me: tuple[float, float] | None) -> list[dict]:
    """The waypoint in its zone, else the portals toward its zone (the closest to you first)."""
    if not (waypoint and here):
        return []
    if waypoint["zone"].lower() == here.lower():
        return [{**waypoint, "label": short_name(waypoint["label"]), "goal": "", "final": True}]
    path = graph.path(here, waypoint["zone"])
    if not path or len(path) < 2:
        return []
    zone = data.zone(here)
    nxt = path[1]
    portals = [m for m in zone["markers"] if m["cat"] == "portal" and (m.get("to") or "").lower() == nxt]
    if me:
        portals.sort(key=lambda m: math.dist(me, (m["x"], m["y"])))
    title = data.zones.get(waypoint["zone"].lower(), {}).get("title") or waypoint["zone"]
    hops = len(path) - 1
    goal = f"{short_name(waypoint['label'])}, {title}" + (f" · {hops} zones" if hops > 1 else "")
    return [{"x": p["x"], "y": p["y"], "plane": p["plane"], "zone": here, "final": False,
             "label": short_name(p["tip"]), "goal": goal} for p in portals]


class ArrowWindow(QWidget):
    """A banana-yellow arrow around your monkey on the game screen, with what it points at and how far."""

    def __init__(self):
        flags = (Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool
                 | Qt.WindowType.WindowTransparentForInput | Qt.WindowType.WindowDoesNotAcceptFocus)
        super().__init__(None, flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setWindowTitle("MQ Overlay arrow")
        self.direction: tuple[float, float] | None = None  # world units, y up
        self.label = ""
        self.goal = ""
        self.distance = 0.0
        self.other_path = False

    def set_state(self, rect: tuple[int, int, int, int] | None, direction: tuple[float, float] | None,
                  label: str = "", other_path: bool = False, goal: str = "") -> None:
        """Show the arrow over the game's client rect (physical pixels) pointing along direction (world units), or
        hide it."""
        if rect is None or direction is None:
            if self.isVisible():
                self.hide()
            return
        from .overlay import place
        place(self, rect)
        self.direction, self.label, self.other_path, self.goal = direction, label, other_path, goal
        self.distance = math.hypot(*direction)
        if not self.isVisible():
            self.show()
            from .game_window import set_no_activate
            set_no_activate(int(self.winId()), True)
        self.update()

    def paintEvent(self, event) -> None:
        if self.direction is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.paint_arrow(p, self.width(), self.height())
        p.end()

    def paint_arrow(self, p: QPainter, w: int, h: int) -> None:
        cx, cy = w / 2, h * 0.56  # about where the monkey stands
        r = max(60.0, min(140.0, min(w, h) * 0.13))
        dx, dy = self.direction
        font = QFont("Nunito", 11)
        font.setBold(True)
        p.setFont(font)
        if self.distance < ARRIVED:
            text = f"Here: {self.label}"
            self.outlined_text(p, QPointF(cx, cy - r - 10), text, center=True)
            p.setPen(QPen(BANANA, 3))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(cx, cy), r * 0.45, r * 0.45)
            return
        a = math.atan2(-dy, dx)  # screen y goes down
        ux, uy = math.cos(a), math.sin(a)
        nx, ny = -uy, ux
        base = QPointF(cx + ux * r, cy + uy * r)
        tip = QPointF(base.x() + ux * 40, base.y() + uy * 40)
        at = lambda along, side: QPointF(base.x() + ux * along + nx * side, base.y() + uy * along + ny * side)  # noqa: E731
        arrow = QPolygonF([tip, at(14, 26), at(14, 10), at(-20, 10), at(-20, -10), at(14, -10), at(14, -26)])
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 110))
        p.drawPolygon(QPolygonF([q + QPointF(3, 4) for q in arrow]))
        p.setPen(QPen(EDGE, 3))
        p.setBrush(BANANA)
        p.drawPolygon(arrow)
        # the label beside the tip, clear of the arrow: what it points at (bold), how far, and the waypoint it leads to
        small = QFont("Nunito", 10)
        small.setBold(True)
        far = f"{self.distance:.0f} away" + (" · other path" if self.other_path else "")
        lines = [(self.label, font, TEXT), (far, small, DIM)] + ([(f"→ {self.goal}", small, DIM)] if self.goal else [])
        sizes = []
        for t, f, _ in lines:
            p.setFont(f)
            sizes.append((p.fontMetrics().horizontalAdvance(t), p.fontMetrics().height()))
        width = max(w for w, _ in sizes)
        height = sum(h for _, h in sizes)
        x = tip.x() + ux * 16 + (0 if ux > 0.4 else -width if ux < -0.4 else -width / 2)
        y = tip.y() + uy * 16 + (sizes[0][1] / 2 if uy > 0.4 else -height if uy < -0.4 else -height / 2 + sizes[0][1] / 2)
        for (t, f, color), (_, h) in zip(lines, sizes):
            p.setFont(f)
            self.outlined_text(p, QPointF(x, y), t, color=color)
            y += h + 1

    def outlined_text(self, p: QPainter, at: QPointF, text: str, center: bool = False, color: QColor = None) -> None:
        fm = p.fontMetrics()
        width = fm.horizontalAdvance(text)
        x = at.x() - width / 2 if center else at.x()
        x = max(6.0, min(x, self.width() - width - 6.0)) if self.width() else x
        path = QPainterPath()
        path.addText(QPointF(x, at.y() + fm.ascent() / 2), p.font(), text)
        p.setPen(QPen(QColor(20, 30, 14, 230), 4))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color or TEXT)
        p.drawPath(path)

    def render_to(self, path: str, size: tuple[int, int], direction: tuple[float, float], label: str,
                  goal: str = "", other_path: bool = False) -> None:
        """For testing: the arrow over a game-like background into a PNG."""
        from PySide6.QtGui import QPixmap
        self.resize(*size)
        self.direction, self.label, self.goal, self.other_path = direction, label, goal, other_path
        self.distance = math.hypot(*direction)
        img = QPixmap(*size)
        img.fill(QColor("#7fb3d5"))
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(QRectF(0, size[1] * 0.62, size[0], size[1]), QColor("#6b8f3a"))
        self.paint_arrow(p, *size)
        p.end()
        img.save(path)
