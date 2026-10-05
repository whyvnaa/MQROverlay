"""Side view of one zone, like the zone maps on the wiki: terrain and water per path (front/back), invisible walls,
markers that keep their size on screen. One path is on show (set_path): drawn on top in full colour, the other one
faded behind it with smaller, faded markers; bridges between the paths are always in full. Wheel zooms, dragging moves, double-click resets; clicking a marker opens its wiki page."""

import html

from PySide6.QtCore import QByteArray, QPointF, QRectF, Qt, QUrl, Signal
from PySide6.QtGui import (QBrush, QColor, QDesktopServices, QImage, QPainter, QPainterPath, QPen, QPixmap,
                           QPolygonF, QTransform)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QGraphicsItem, QGraphicsPathItem, QGraphicsScene, QGraphicsView

from .data import GameData, marker_matches

MARKER = 26  # marker box in screen pixels (shapes are drawn around 0,0 within +-13)
PLANE_STYLE = {  # fill, outline (wiki: .lm-geo, dark scheme): the path on show as solid blocks, the other one as a
    True: (QColor(127, 165, 72, 245), QColor("#b7d27a")),  # grey shadow outline
    False: (QColor(176, 181, 168, 18), QColor(142, 148, 134, 200)),
}
OTHER_PATH_OPACITY, OTHER_MARKER_OPACITY, OTHER_MARKER_SCALE = 0.55, 0.45, 0.75
OBSTACLE_FILL, OBSTACLE_LINE = QColor(161, 136, 127, 90), QColor(141, 110, 99, 140)  # wiki: .lm-obst
WATER_FILL, WATER_LINE = QColor(41, 182, 246, 77), QColor(79, 195, 247, 160)  # wiki: .lm-water
HIGHLIGHT = QColor("#ffd54f")


def pct(chance) -> str:
    return "" if chance is None else f"{chance * 100:.1f} %" if chance < 1 else f"{chance * 100:.0f} %"


class Sprites:
    """Marker images rendered from the exported SVG shapes, with portraits for enemies and NPCs, per pixel ratio."""

    def __init__(self, data: GameData):
        self.data = data
        self.cache: dict[tuple, QPixmap] = {}
        self.scale = 1.0  # marker size (smaller on the corner map)

    def get(self, cat: str, art: str | None, dpr: float) -> QPixmap:
        key = (cat, art, dpr)
        if key not in self.cache:
            self.cache[key] = self._render(cat, art, dpr)
        return self.cache[key]

    def _render(self, cat: str, art: str | None, dpr: float) -> QPixmap:
        size = round(MARKER * dpr)
        img = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        shape = self.data.shapes.get(cat + "_art" if art else cat, self.data.shapes.get(cat, ""))
        svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="-13 -13 26 26" width="26" height="26">{shape}</svg>'
        QSvgRenderer(QByteArray(svg.encode())).render(p)
        portrait = QPixmap(str(self.data.art(art))) if art else QPixmap()
        if not portrait.isNull():
            clip = QPainterPath()
            r = 9.8 * dpr
            clip.addEllipse(QPointF(size / 2, size / 2), r, r)
            p.setClipPath(clip)
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            p.drawPixmap(QRectF(size / 2 - r, size / 2 - r, 2 * r, 2 * r), portrait, QRectF(portrait.rect()))
        p.end()
        pix = QPixmap.fromImage(img)
        pix.setDevicePixelRatio(dpr)
        return pix


class Marker(QGraphicsItem):
    def __init__(self, m: dict, sprites: Sprites, z: float):
        super().__init__()
        self.m = m
        self.sprites = sprites
        self.state = ""  # "", "hl" (search match) or "dim"
        self.other_path = False  # on the path that is not on show: smaller and faded
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
        self.setPos(m["x"], -m["y"])
        self.setZValue(z)
        self.setToolTip(self.tooltip())
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def tooltip(self) -> str:
        m = self.m
        lines = [f"<b>{html.escape(m['tip'])}</b>"]
        for name, chance in m.get("drops", ()):
            lines.append(f"{html.escape(name)} <span style='color:#ffd54f'>{pct(chance)}</span>")
        hint = "Click: show the way" + (" · right-click: wiki page" if m.get("url") else "")
        lines.append(f"<i style='color:#a9bf8e'>{hint}</i>")
        return "<br>".join(lines)

    def set_state(self, state: str, other_path: bool | None = None) -> None:
        other = self.other_path if other_path is None else other_path
        if state != self.state or other != self.other_path:
            self.prepareGeometryChange()
            self.state, self.other_path = state, other
            self.setOpacity((0.25 if state == "dim" else 1.0) * (OTHER_MARKER_OPACITY if other else 1.0))
            self.update()

    def k(self) -> float:
        return (1.6 if self.state == "hl" else 1.0) * (OTHER_MARKER_SCALE if self.other_path else 1.0) * self.sprites.scale

    def boundingRect(self) -> QRectF:
        s = MARKER * self.k()
        return QRectF(-s / 2 - 4, -s / 2 - 4, s + 8, s + 8)

    def paint(self, p: QPainter, option, widget=None) -> None:
        dpr = widget.devicePixelRatioF() if widget else 1.0
        k = self.k()
        if self.state == "hl":
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setPen(QPen(HIGHLIGHT, 3))
            p.setBrush(QColor(255, 213, 79, 60))
            p.drawEllipse(QPointF(0, 0), 13 * k + 1, 13 * k + 1)
        s = MARKER * k
        p.drawPixmap(QRectF(-s / 2, -s / 2, s, s), self.sprites.get(self.m["cat"], self.m.get("art"), dpr * k),
                     QRectF(0, 0, round(MARKER * dpr * k), round(MARKER * dpr * k)))


class PlayerMarker(QGraphicsItem):
    """You (banana-yellow ring with a dot) or another player (small blue dot), live from the game's traffic."""

    def __init__(self, me: bool):
        super().__init__()
        self.me = me
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
        self.setZValue(1000 if me else 900)
        self.setToolTip("You" if me else "Another player")

    def boundingRect(self) -> QRectF:
        return QRectF(-16, -16, 32, 32)

    def paint(self, p: QPainter, option, widget=None) -> None:
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.me:
            p.setPen(QPen(QColor(0, 0, 0, 160), 5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(0, 0), 11, 11)
            p.setPen(QPen(HIGHLIGHT, 3))
            p.drawEllipse(QPointF(0, 0), 11, 11)
            p.setPen(QPen(QColor("#5d4000"), 1.5))
            p.setBrush(HIGHLIGHT)
            p.drawEllipse(QPointF(0, 0), 5, 5)
        else:
            p.setPen(QPen(QColor("#ffffff"), 2))
            p.setBrush(QColor("#29b6f6"))
            p.drawEllipse(QPointF(0, 0), 6, 6)


class GoalMarker(QGraphicsItem):
    """The end of a route: a banana-yellow flag."""

    def __init__(self):
        super().__init__()
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
        self.setZValue(1100)

    def boundingRect(self) -> QRectF:
        return QRectF(-6, -26, 24, 30)

    def paint(self, p: QPainter, option, widget=None) -> None:
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor(0, 0, 0, 170), 4))
        p.drawLine(QPointF(0, 2), QPointF(0, -22))
        p.setPen(QPen(QColor("#fff6e0"), 2))
        p.drawLine(QPointF(0, 2), QPointF(0, -22))
        flag = QPolygonF([QPointF(1, -22), QPointF(15, -17), QPointF(1, -12)])
        p.setPen(QPen(QColor("#5d4000"), 1.5))
        p.setBrush(HIGHLIGHT)
        p.drawPolygon(flag)


class MapView(QGraphicsView):
    MAX_ZOOM = 12
    markerClicked = Signal(object)  # marker dict (left click)
    pointClicked = Signal(float, float, bool)  # world x, y of a left click on the map, Shift held

    def __init__(self, data: GameData, parent=None):
        super().__init__(parent)
        self.data = data
        self.sprites = Sprites(data)
        self.setScene(QGraphicsScene(self))
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.setStyleSheet("background: transparent")
        self.viewport().setAutoFillBackground(False)
        self.zone: dict | None = None
        self.extent = QRectF()
        self.markers: list[Marker] = []
        self.planes: dict[int, list[QGraphicsItem]] = {}  # path -> its items (the ground first)
        self.hidden_cats: set[str] = set()
        self.path = 0  # the path on show
        self.query = ""
        self.user_zoomed = False
        self.always_fit = False  # the corner map shows the whole zone (or follows you, see follow_span)
        self.follow_span: float | None = None  # corner map: world units across when it follows you
        self.me_item: PlayerMarker | None = None
        self.others: dict[str, PlayerMarker] = {}
        self.route_items: list[QGraphicsItem] = []
        self._press = None

    # ---------------------------------------------------------------- content

    def show_zone(self, zone: dict | None) -> None:
        scene = self.scene()
        scene.clear()
        self.markers, self.planes, self.zone = [], {}, zone
        self.me_item, self.others, self.route_items = PlayerMarker(True), {}, []
        self.me_item.hide()
        scene.addItem(self.me_item)
        if not zone:
            return
        for plane in (1, 0):
            name = f"Plane{plane}"
            path = QPainterPath()  # the ground's merged outlines with the invisible walls (LevelMap.ground), holes odd-even
            path.setFillRule(Qt.FillRule.OddEvenFill)
            for poly in zone.get("ground", {}).get(name, []):
                for ring in poly:
                    path.addPolygon(QPolygonF([QPointF(x, -y) for x, y in ring]))
                    path.closeSubpath()
            if path.isEmpty() and not zone.get("water", {}).get(name):
                continue
            item = QGraphicsPathItem(path)  # styled by set_path
            scene.addItem(item)
            items = [item]
            obst = QPainterPath()  # doors, breakable blocks, crushers: in the way only now and then
            for poly in zone.get("obstacles", {}).get(name, []):
                obst.addPolygon(QPolygonF([QPointF(x, -y) for x, y in poly]))
                obst.closeSubpath()
            if not obst.isEmpty():
                ob = scene.addPath(obst, QPen(OBSTACLE_LINE, 0), QBrush(OBSTACLE_FILL))
                ob.setData(0, 4)
                items.append(ob)
            water = QPainterPath()  # water you swim in: under the ground of its path
            water.setFillRule(Qt.FillRule.WindingFill)
            for poly in zone.get("water", {}).get(name, []):
                water.addPolygon(QPolygonF([QPointF(x, -y) for x, y in poly]))
                water.closeSubpath()
            if not water.isEmpty():
                wa = scene.addPath(water.simplified(), QPen(WATER_LINE, 0), QBrush(WATER_FILL))  # one outline, not one per cube
                wa.setData(0, -2)  # under the path's ground
                items.append(wa)
            self.planes[plane] = items
        order = {c["key"]: i for i, c in enumerate(self.data.categories)}
        for m in zone["markers"]:
            mk = Marker(m, self.sprites, len(order) - order.get(m["cat"], 0))  # enemies on top (set_path adds the path)
            scene.addItem(mk)
            self.markers.append(mk)
        self.set_path(self.path if self.path in self.planes else min(self.planes, default=0))
        x0, y0, x1, y1 = zone["extent"]
        self.extent = QRectF(x0, -y1, x1 - x0, y1 - y0)
        w, h = self.extent.width(), self.extent.height()
        self.setSceneRect(self.extent.adjusted(-w, -h, w, h))  # room to drag past the edges
        self.apply_filters()
        self.highlight(self.query)
        self.fit()

    def fit(self) -> None:
        if self.extent.isEmpty():
            return
        if self.follow_span and self.me_item and self.me_item.isVisible():
            self.center_on_me(self.follow_span)
            return
        self.resetTransform()
        self.fitInView(self.extent, Qt.AspectRatioMode.KeepAspectRatio)
        self.user_zoomed = False

    def center_on_me(self, span: float) -> None:
        """Zoom so that span world units fit across, centred on your position."""
        if not (self.me_item and self.me_item.isVisible()) or self.viewport().width() <= 0:
            return
        s = self.viewport().width() / span
        self.setTransform(QTransform.fromScale(s, s))
        self.centerOn(self.me_item.pos())

    def set_live(self, me: tuple[float, float] | None, others: dict[str, tuple[float, float]]) -> None:
        """Live positions in world units (x, y up)."""
        if not self.zone:
            return
        was_visible = self.me_item.isVisible()
        if me:
            self.me_item.setPos(me[0], -me[1])
            self.me_item.show()
        else:
            self.me_item.hide()
        for k in [k for k in self.others if k not in others]:
            self.scene().removeItem(self.others.pop(k))
        for k, (x, y) in others.items():
            if k not in self.others:
                self.others[k] = PlayerMarker(False)
                self.scene().addItem(self.others[k])
            self.others[k].setPos(x, -y)
        if self.follow_span:
            if me:
                self.center_on_me(self.follow_span)
            elif was_visible:
                self.fit()

    def set_waypoint(self, goal: tuple[float, float] | None, me: tuple[float, float] | None = None) -> None:
        """The waypoint (or the portal or bridge toward it) as a banana-yellow flag, with a dashed line from you."""
        self.clear_waypoint()
        if not self.zone or goal is None:
            return
        if me:
            line = QPainterPath()
            line.moveTo(me[0], -me[1])
            line.lineTo(goal[0], -goal[1])
            for pen, z in ((QPen(QColor(0, 0, 0, 140), 5), 950), (QPen(HIGHLIGHT, 2.5, Qt.PenStyle.DashLine), 951)):
                pen.setCosmetic(True)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                item = self.scene().addPath(line, pen)
                item.setZValue(z)
                self.route_items.append(item)
        flag = GoalMarker()
        flag.setPos(goal[0], -goal[1])
        self.scene().addItem(flag)
        self.route_items.append(flag)

    def clear_waypoint(self) -> None:
        for item in self.route_items:
            if item.scene():
                self.scene().removeItem(item)
        self.route_items = []

    def set_filters(self, hidden_cats: set[str]) -> None:
        self.hidden_cats = set(hidden_cats)
        self.apply_filters()

    def set_path(self, path: int) -> None:
        """Show this path on top in full colour; the other one fades behind it, with smaller, faded markers."""
        self.path = path
        for plane, items in self.planes.items():
            on = plane == path
            base = 0 if on else -40  # the other path's ground, water and walls below this path's
            fill, line = PLANE_STYLE[on]
            items[0].setBrush(QBrush(fill))
            pen = QPen(line, 1.2 if on else 1.5)
            pen.setCosmetic(True)  # the same width at every zoom
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            items[0].setPen(pen)
            for it in items:
                it.setZValue(base - 10 + (it.data(0) or 0))
                it.setOpacity(1.0 if on or it is items[0] else OTHER_PATH_OPACITY)  # the outline has its own grey
        for mk in self.markers:
            other = not mk.m.get("both") and mk.m["plane"] != path and len(self.planes) > 1
            mk.setZValue((mk.zValue() % 100) + (0 if other else 100) + (200 if mk.m.get("both") else 0))
            mk.set_state(mk.state, other)

    def apply_filters(self) -> None:
        for mk in self.markers:
            mk.setVisible(mk.state == "hl" or mk.m["cat"] not in self.hidden_cats)

    def highlight(self, query: str) -> int:
        """Search matches stand out (and show even if their kind is filtered out), the rest fade. Returns the count."""
        self.query = q = query.strip().lower()
        hits = [bool(q) and marker_matches(mk.m, q) for mk in self.markers]
        n = sum(hits)
        for mk, hit in zip(self.markers, hits):
            # nothing found here: the map stays as it is; a match on the other path stays faded and smaller
            mk.set_state("hl" if hit else "dim" if n else "")
        self.apply_filters()
        return n

    def set_marker_scale(self, scale: float) -> None:
        if scale != self.sprites.scale:
            for mk in self.markers:
                mk.prepareGeometryChange()
            self.sprites.scale = scale
            self.viewport().update()

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for mk in self.markers:
            out[mk.m["cat"]] = out.get(mk.m["cat"], 0) + 1
        return out

    def planes_present(self) -> list[int]:
        return sorted(self.planes)

    # ---------------------------------------------------------------- interaction

    def wheelEvent(self, event) -> None:
        if self.extent.isEmpty():
            return
        factor = 1.2 ** (event.angleDelta().y() / 120)
        fit = min(self.viewport().width() / self.extent.width(), self.viewport().height() / self.extent.height())
        new = self.transform().m11() * factor
        if fit / 1.5 <= new <= fit * self.MAX_ZOOM:
            self.scale(factor, factor)
            self.user_zoomed = True

    def mouseDoubleClickEvent(self, event) -> None:
        self.fit()

    def mousePressEvent(self, event) -> None:
        self._press = event.position()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        super().mouseReleaseEvent(event)
        if self._press is not None and (event.position() - self._press).manhattanLength() < 5:
            item = self.itemAt(event.position().toPoint())
            marker = item if isinstance(item, Marker) and item.isVisible() else None
            if event.button() == Qt.MouseButton.RightButton:
                if marker and marker.m.get("url"):
                    QDesktopServices.openUrl(QUrl(marker.m["url"]))
            elif marker:
                self.markerClicked.emit(marker.m)
            else:
                pt = self.mapToScene(event.position().toPoint())
                self.pointClicked.emit(pt.x(), -pt.y(),
                                       bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier))
        self._press = None

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.always_fit or not self.user_zoomed:
            self.fit()
