"""Globally scoped mission location icons for desktop map surfaces."""
from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

MISSION_LOCATION_ICON_KEYS: tuple[str, ...] = (
    "command_post",
    "staging_area",
    "demob_point",
    "medical",
    "evacuation",
    "supply",
)

MISSION_LOCATION_ICON_LABELS: dict[str, str] = {
    "command_post": "Command Post",
    "staging_area": "Staging Area",
    "demob_point": "Demob Point",
    "medical": "Medical",
    "evacuation": "Evacuation",
    "supply": "Supply",
}

_ALIASES = {
    "command": "command_post",
    "command post": "command_post",
    "cp": "command_post",
    "staging": "staging_area",
    "staging area": "staging_area",
    "demob": "demob_point",
    "demob point": "demob_point",
    "demobilization": "demob_point",
    "medical": "medical",
    "evac": "evacuation",
    "evacuation": "evacuation",
    "supply": "supply",
}


def mission_location_icon_key(value: str) -> str:
    """Return the globally scoped icon key for a mission location label/key."""
    raw = str(value or "").strip()
    normalised = raw.lower().replace("-", " ").replace("_", " ")
    compact = "_".join(part for part in normalised.split() if part)
    return _ALIASES.get(normalised, compact if compact in MISSION_LOCATION_ICON_KEYS else "")


def draw_mission_location_icon(
    scene: QtWidgets.QGraphicsScene,
    icon_key: str,
    x: float,
    y: float,
    *,
    z: float = 17.0,
    size: float = 12.0,
) -> QtWidgets.QGraphicsItem:
    """Draw a mission location icon and return its primary graphics item."""
    key = mission_location_icon_key(icon_key) or "command_post"
    pen = QtGui.QPen(QtGui.QColor("#edf3f5"), 2)
    x = float(x)
    y = float(y)
    size = float(size)

    if key == "staging_area":
        item = scene.addPolygon(
            QtGui.QPolygonF(
                [
                    QtCore.QPointF(x, y - size),
                    QtCore.QPointF(x + size, y),
                    QtCore.QPointF(x, y + size),
                    QtCore.QPointF(x - size, y),
                ]
            ),
            pen,
            QtGui.QBrush(QtGui.QColor("#3498db")),
        )
        _add_center_text(scene, "STG", x, y, z + 1, QtGui.QColor("#edf3f5"), point_size=6)
    elif key == "demob_point":
        item = scene.addEllipse(
            x - size,
            y - size,
            size * 2,
            size * 2,
            pen,
            QtGui.QBrush(QtGui.QColor("#1f2930")),
        )
        arc = QtGui.QPainterPath()
        arc.arcMoveTo(x - size * 0.58, y - size * 0.58, size * 1.16, size * 1.16, 210)
        arc.arcTo(x - size * 0.58, y - size * 0.58, size * 1.16, size * 1.16, 210, 260)
        arc_item = scene.addPath(arc, QtGui.QPen(QtGui.QColor("#2ecc71"), 3))
        arc_item.setZValue(z + 1)
        arrow = scene.addPolygon(
            QtGui.QPolygonF(
                [
                    QtCore.QPointF(x + size * 0.64, y - size * 0.28),
                    QtCore.QPointF(x + size * 0.95, y - size * 0.78),
                    QtCore.QPointF(x + size * 1.08, y - size * 0.17),
                ]
            ),
            QtGui.QPen(QtCore.Qt.NoPen),
            QtGui.QBrush(QtGui.QColor("#2ecc71")),
        )
        arrow.setZValue(z + 1)
    elif key == "medical":
        item = scene.addRect(
            x - size,
            y - size,
            size * 2,
            size * 2,
            pen,
            QtGui.QBrush(QtGui.QColor("#e74c3c")),
        )
        _add_line(scene, x - size * 0.62, y, x + size * 0.62, y, z + 1, "#ffffff", 3)
        _add_line(scene, x, y - size * 0.62, x, y + size * 0.62, z + 1, "#ffffff", 3)
    elif key == "evacuation":
        item = scene.addPolygon(
            QtGui.QPolygonF(
                [
                    QtCore.QPointF(x, y - size * 1.12),
                    QtCore.QPointF(x + size * 1.12, y + size),
                    QtCore.QPointF(x - size * 1.12, y + size),
                ]
            ),
            pen,
            QtGui.QBrush(QtGui.QColor("#ffdf6e")),
        )
        _add_center_text(scene, "EV", x, y + size * 0.22, z + 1, QtGui.QColor("#151a1d"), point_size=7)
    elif key == "supply":
        item = scene.addPolygon(
            QtGui.QPolygonF(
                [
                    QtCore.QPointF(x - size * 0.85, y - size * 0.75),
                    QtCore.QPointF(x + size * 0.45, y - size * 0.75),
                    QtCore.QPointF(x + size, y),
                    QtCore.QPointF(x + size * 0.45, y + size * 0.75),
                    QtCore.QPointF(x - size * 0.85, y + size * 0.75),
                    QtCore.QPointF(x - size * 1.2, y),
                ]
            ),
            pen,
            QtGui.QBrush(QtGui.QColor("#8fbcbb")),
        )
        _add_center_text(scene, "SUP", x, y, z + 1, QtGui.QColor("#101619"), point_size=6)
    else:
        item = scene.addRect(
            x - size,
            y - size,
            size * 2,
            size * 2,
            pen,
            QtGui.QBrush(QtGui.QColor("#1f2930")),
        )
        _add_line(scene, x, y + size * 0.62, x, y - size * 0.75, z + 1, "#ffdf6e", 3)
        _add_line(scene, x - size * 0.9, y - size * 0.22, x - size * 0.3, y - size * 0.72, z + 1, "#ffdf6e", 2)
        _add_line(scene, x + size * 0.9, y - size * 0.22, x + size * 0.3, y - size * 0.72, z + 1, "#ffdf6e", 2)
        _add_line(scene, x - size * 0.72, y + size * 0.1, x - size * 0.25, y - size * 0.25, z + 1, "#ffdf6e", 2)
        _add_line(scene, x + size * 0.72, y + size * 0.1, x + size * 0.25, y - size * 0.25, z + 1, "#ffdf6e", 2)

    item.setZValue(z)
    item.setData(0, key)
    return item


def mission_location_icon_pixmap(icon_key: str, *, pixel_size: int = 38) -> QtGui.QPixmap:
    """Render a mission location icon to a pixmap for legends and controls."""
    size = max(24, int(pixel_size))
    scene = QtWidgets.QGraphicsScene()
    scene.setSceneRect(0, 0, size, size)
    draw_mission_location_icon(
        scene,
        icon_key,
        size / 2,
        size / 2,
        z=1,
        size=max(8, (size - 10) / 2),
    )
    image = QtGui.QImage(size, size, QtGui.QImage.Format_ARGB32_Premultiplied)
    image.fill(QtCore.Qt.transparent)
    painter = QtGui.QPainter(image)
    try:
        painter.setRenderHints(
            QtGui.QPainter.Antialiasing | QtGui.QPainter.TextAntialiasing
        )
        scene.render(painter, QtCore.QRectF(0, 0, size, size), scene.sceneRect())
    finally:
        painter.end()
    return QtGui.QPixmap.fromImage(image)


def _add_line(
    scene: QtWidgets.QGraphicsScene,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    z: float,
    color: str,
    width: int,
) -> None:
    line = scene.addLine(x1, y1, x2, y2, QtGui.QPen(QtGui.QColor(color), width))
    line.setZValue(z)


def _add_center_text(
    scene: QtWidgets.QGraphicsScene,
    text: str,
    x: float,
    y: float,
    z: float,
    color: QtGui.QColor,
    *,
    point_size: int,
) -> None:
    item = scene.addText(text)
    font = item.font()
    font.setBold(True)
    font.setPointSize(point_size)
    item.setFont(font)
    item.setDefaultTextColor(color)
    rect = item.boundingRect()
    item.setPos(x - rect.width() / 2, y - rect.height() / 2)
    item.setZValue(z)
