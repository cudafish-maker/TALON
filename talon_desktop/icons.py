"""Custom PySide6 icons for TALON desktop surfaces."""
from __future__ import annotations

from PySide6 import QtCore, QtGui

NAV_ICON_KEYS = frozenset(
    {
        "dashboard",
        "map",
        "sitreps",
        "assets",
        "missions",
        "assignments",
        "incidents",
        "chat",
        "documents",
        "operators",
        "enrollment",
        "clients",
        "audit",
        "keys",
    }
)
ASSET_ICON_CATEGORIES = frozenset(
    {"person", "safe_house", "cache", "rally_point", "vehicle", "custom"}
)

_NAV_ICON_CACHE: dict[tuple[str, int], QtGui.QIcon] = {}
_ASSET_PIXMAP_CACHE: dict[tuple[str, bool, bool, int], QtGui.QPixmap] = {}


def desktop_nav_icon(key: str, *, size: int = 24) -> QtGui.QIcon:
    """Return a purpose-built monochrome nav icon for a desktop section."""
    _require_gui_application()
    cache_key = (key, int(size))
    cached = _NAV_ICON_CACHE.get(cache_key)
    if cached is not None:
        return cached

    normal, active, selected, disabled = _nav_icon_colors(key)
    icon = QtGui.QIcon()
    icon.addPixmap(
        _nav_icon_pixmap(key, size=size, color=normal),
        QtGui.QIcon.Mode.Normal,
        QtGui.QIcon.State.Off,
    )
    icon.addPixmap(
        _nav_icon_pixmap(key, size=size, color=active),
        QtGui.QIcon.Mode.Active,
        QtGui.QIcon.State.Off,
    )
    icon.addPixmap(
        _nav_icon_pixmap(key, size=size, color=active),
        QtGui.QIcon.Mode.Selected,
        QtGui.QIcon.State.Off,
    )
    icon.addPixmap(
        _nav_icon_pixmap(key, size=size, color=disabled),
        QtGui.QIcon.Mode.Disabled,
        QtGui.QIcon.State.Off,
    )
    for mode in (
        QtGui.QIcon.Mode.Normal,
        QtGui.QIcon.Mode.Active,
        QtGui.QIcon.Mode.Selected,
    ):
        icon.addPixmap(
            _nav_icon_pixmap(key, size=size, color=selected),
            mode,
            QtGui.QIcon.State.On,
        )
    icon.addPixmap(
        _nav_icon_pixmap(key, size=size, color=disabled),
        QtGui.QIcon.Mode.Disabled,
        QtGui.QIcon.State.On,
    )
    _NAV_ICON_CACHE[cache_key] = icon
    return icon


def asset_marker_pixmap(
    category: str,
    *,
    verified: bool,
    selected: bool = False,
    size: int = 32,
) -> QtGui.QPixmap:
    """Return a framed map marker pixmap for an asset category and state."""
    _require_gui_application()
    normalized_category = category if category in ASSET_ICON_CATEGORIES else "custom"
    cache_key = (normalized_category, bool(verified), bool(selected), int(size))
    cached = _ASSET_PIXMAP_CACHE.get(cache_key)
    if cached is not None:
        return QtGui.QPixmap(cached)

    pixmap = QtGui.QPixmap(size, size)
    pixmap.fill(QtCore.Qt.GlobalColor.transparent)
    painter = QtGui.QPainter(pixmap)
    painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
    painter.scale(size / 64.0, size / 64.0)

    if selected:
        selection_pen = QtGui.QPen(
            QtGui.QColor("#f6fbfb"),
            3,
            QtCore.Qt.PenStyle.SolidLine,
            QtCore.Qt.PenCapStyle.RoundCap,
            QtCore.Qt.PenJoinStyle.RoundJoin,
        )
        painter.setPen(selection_pen)
        painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(QtCore.QRectF(5, 9, 54, 46), 2, 2)

    frame_pen = QtGui.QPen(
        QtGui.QColor("#5aa9e6" if verified else "#d6b85a"),
        4,
        QtCore.Qt.PenStyle.SolidLine,
        QtCore.Qt.PenCapStyle.RoundCap,
        QtCore.Qt.PenJoinStyle.RoundJoin,
    )
    if not verified:
        frame_pen.setDashPattern([7, 5])
    painter.setPen(frame_pen)
    painter.setBrush(
        QtGui.QColor(35, 78, 108, 200)
        if verified
        else QtGui.QColor(86, 72, 28, 200)
    )
    painter.drawRoundedRect(QtCore.QRectF(8, 12, 48, 40), 2, 2)

    glyph_pen = QtGui.QPen(
        QtGui.QColor("#f6fbfb"),
        3,
        QtCore.Qt.PenStyle.SolidLine,
        QtCore.Qt.PenCapStyle.RoundCap,
        QtCore.Qt.PenJoinStyle.RoundJoin,
    )
    painter.setPen(glyph_pen)
    painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
    _draw_asset_glyph(painter, normalized_category)
    painter.end()

    _ASSET_PIXMAP_CACHE[cache_key] = QtGui.QPixmap(pixmap)
    return pixmap


def _nav_icon_colors(key: str) -> tuple[str, str, str, str]:
    if key == "incidents":
        return ("#ff5555", "#ff7777", "#ff7777", "#526068")
    return ("#aebbc2", "#d8dee9", "#8fbcbb", "#526068")


def _require_gui_application() -> None:
    app = QtGui.QGuiApplication.instance()
    if not isinstance(app, QtGui.QGuiApplication):
        raise RuntimeError(
            "TALON desktop icons require a live QGuiApplication/QApplication "
            "before QPixmap-backed icons can be rendered."
        )


def _nav_icon_pixmap(key: str, *, size: int, color: str) -> QtGui.QPixmap:
    pixmap = QtGui.QPixmap(size, size)
    pixmap.fill(QtCore.Qt.GlobalColor.transparent)
    painter = QtGui.QPainter(pixmap)
    painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
    painter.scale(size / 24.0, size / 24.0)
    painter.setPen(
        QtGui.QPen(
            QtGui.QColor(color),
            2.1,
            QtCore.Qt.PenStyle.SolidLine,
            QtCore.Qt.PenCapStyle.RoundCap,
            QtCore.Qt.PenJoinStyle.RoundJoin,
        )
    )
    painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
    _draw_nav_glyph(painter, key if key in NAV_ICON_KEYS else "documents")
    painter.end()
    return pixmap


def _draw_nav_glyph(painter: QtGui.QPainter, key: str) -> None:
    if key == "dashboard":
        _rounded_rect(painter, 3, 4, 7, 7, 1.5)
        _rounded_rect(painter, 14, 4, 7, 5, 1.5)
        _rounded_rect(painter, 3, 15, 7, 5, 1.5)
        _line(painter, 15, 18, 20, 18)
        _line(painter, 17.5, 15.5, 17.5, 20.5)
    elif key == "map":
        path = QtGui.QPainterPath(QtCore.QPointF(4, 6))
        path.lineTo(9, 4)
        path.lineTo(15, 6)
        path.lineTo(20, 4)
        path.lineTo(20, 18)
        path.lineTo(15, 20)
        path.lineTo(9, 18)
        path.lineTo(4, 20)
        path.closeSubpath()
        painter.drawPath(path)
        _line(painter, 9, 4, 9, 18)
        _line(painter, 15, 6, 15, 20)
        painter.drawEllipse(QtCore.QPointF(12, 12), 2, 2)
    elif key == "sitreps":
        path = QtGui.QPainterPath(QtCore.QPointF(6, 3))
        path.lineTo(15, 3)
        path.lineTo(18, 6)
        path.lineTo(18, 21)
        path.lineTo(6, 21)
        path.closeSubpath()
        painter.drawPath(path)
        _line(painter, 14, 3, 14, 7)
        _line(painter, 14, 7, 18, 7)
        _line(painter, 9, 10, 15, 10)
        _line(painter, 9, 14, 13, 14)
        painter.drawEllipse(QtCore.QPointF(18.5, 15.5), 2.2, 2.2)
        _line(painter, 18.5, 17.5, 20.5, 20.5)
    elif key == "assets":
        _rounded_rect(painter, 4, 6, 16, 12, 1.5)
        _line(painter, 8, 10, 16, 10)
        _line(painter, 8, 14, 11, 14)
        painter.drawEllipse(QtCore.QPointF(16.5, 14), 1.7, 1.7)
    elif key == "missions":
        _line(painter, 5, 20, 5, 5)
        path = QtGui.QPainterPath(QtCore.QPointF(5, 6))
        path.lineTo(15, 6)
        path.lineTo(12.5, 9)
        path.lineTo(15, 12)
        path.lineTo(5, 12)
        painter.drawPath(path)
        route = QtGui.QPainterPath(QtCore.QPointF(8, 19))
        route.cubicTo(10, 16, 13, 15, 18, 15)
        painter.drawPath(route)
        painter.drawEllipse(QtCore.QPointF(18, 15), 2, 2)
    elif key == "assignments":
        _line(painter, 8, 5, 16, 5)
        _rounded_rect(painter, 6, 4, 12, 17, 2)
        path = QtGui.QPainterPath(QtCore.QPointF(9, 10))
        path.lineTo(10.5, 11.5)
        path.lineTo(14, 8)
        painter.drawPath(path)
        _line(painter, 9, 16, 15, 16)
    elif key == "incidents":
        path = QtGui.QPainterPath(QtCore.QPointF(12, 4))
        path.lineTo(21, 20)
        path.lineTo(3, 20)
        path.closeSubpath()
        painter.drawPath(path)
        _line(painter, 12, 9, 12, 14)
        _line(painter, 12, 17.5, 12.01, 17.5)
    elif key == "chat":
        path = QtGui.QPainterPath(QtCore.QPointF(4, 5))
        path.lineTo(16, 5)
        path.cubicTo(17.8, 5, 19, 6.2, 19, 8)
        path.lineTo(19, 12)
        path.cubicTo(19, 13.8, 17.8, 15, 16, 15)
        path.lineTo(9, 15)
        path.lineTo(4, 19)
        path.closeSubpath()
        painter.drawPath(path)
        _line(painter, 8, 9, 15, 9)
        _line(painter, 8, 12, 13, 12)
    elif key == "documents":
        path = QtGui.QPainterPath(QtCore.QPointF(7, 3))
        path.lineTo(15, 3)
        path.lineTo(19, 7)
        path.lineTo(19, 21)
        path.lineTo(7, 21)
        path.closeSubpath()
        painter.drawPath(path)
        _line(painter, 15, 3, 15, 8)
        _line(painter, 15, 8, 19, 8)
        _line(painter, 10, 12, 16, 12)
        _line(painter, 10, 16, 15, 16)
        _line(painter, 5, 6, 5, 21)
    elif key == "operators":
        painter.drawEllipse(QtCore.QPointF(9, 8), 3, 3)
        path = QtGui.QPainterPath(QtCore.QPointF(4, 19))
        path.cubicTo(4.7, 15, 13.3, 15, 14, 19)
        painter.drawPath(path)
        arc = QtCore.QRectF(12.5, 4.5, 5, 5)
        painter.drawArc(arc, -90 * 16, 180 * 16)
        path = QtGui.QPainterPath(QtCore.QPointF(16, 15))
        path.cubicTo(18.2, 15.4, 19.6, 16.7, 20, 19)
        painter.drawPath(path)
    elif key == "enrollment":
        _rounded_rect(painter, 4, 5, 12, 14, 2)
        _line(painter, 8, 9, 12, 9)
        _line(painter, 8, 13, 11, 13)
        painter.drawEllipse(QtCore.QPointF(17, 16), 4, 4)
        _line(painter, 17, 14, 17, 18)
        _line(painter, 15, 16, 19, 16)
    elif key == "clients":
        _rounded_rect(painter, 3, 5, 8, 6, 1.5)
        _rounded_rect(painter, 13, 5, 8, 6, 1.5)
        _rounded_rect(painter, 8, 15, 8, 5, 1.5)
        _line(painter, 7, 11, 7, 13)
        _line(painter, 7, 13, 12, 13)
        _line(painter, 12, 13, 12, 15)
        _line(painter, 17, 11, 17, 13)
        _line(painter, 17, 13, 12, 13)
    elif key == "audit":
        path = QtGui.QPainterPath(QtCore.QPointF(6, 4))
        path.lineTo(16, 4)
        path.lineTo(16, 20)
        path.lineTo(6, 20)
        path.closeSubpath()
        painter.drawPath(path)
        _line(painter, 9, 8, 14, 8)
        _line(painter, 9, 12, 13, 12)
        painter.drawEllipse(QtCore.QPointF(16.5, 16.5), 2.5, 2.5)
        _line(painter, 18.5, 18.5, 21, 21)
    elif key == "keys":
        painter.drawEllipse(QtCore.QPointF(8, 12), 4, 4)
        _line(painter, 12, 12, 21, 12)
        _line(painter, 18, 12, 18, 15)
        _line(painter, 15, 12, 15, 14)


def _draw_asset_glyph(painter: QtGui.QPainter, category: str) -> None:
    if category == "person":
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        painter.setBrush(QtGui.QColor("#f6fbfb"))
        painter.drawEllipse(QtCore.QPointF(32, 27), 5, 5)
        painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        painter.setPen(
            QtGui.QPen(
                QtGui.QColor("#f6fbfb"),
                3,
                QtCore.Qt.PenStyle.SolidLine,
                QtCore.Qt.PenCapStyle.RoundCap,
                QtCore.Qt.PenJoinStyle.RoundJoin,
            )
        )
        path = QtGui.QPainterPath(QtCore.QPointF(22, 44))
        path.cubicTo(23.5, 36, 40.5, 36, 42, 44)
        painter.drawPath(path)
        _line(painter, 32, 32, 32, 40)
    elif category == "safe_house":
        path = QtGui.QPainterPath(QtCore.QPointF(19, 34))
        path.lineTo(32, 23)
        path.lineTo(45, 34)
        painter.drawPath(path)
        path = QtGui.QPainterPath(QtCore.QPointF(24, 34))
        path.lineTo(24, 44)
        path.lineTo(40, 44)
        path.lineTo(40, 34)
        painter.drawPath(path)
        path = QtGui.QPainterPath(QtCore.QPointF(31, 44))
        path.lineTo(31, 37)
        path.lineTo(37, 37)
        path.lineTo(37, 44)
        painter.drawPath(path)
    elif category == "cache":
        painter.drawRect(QtCore.QRectF(20, 27, 24, 18))
        _line(painter, 20, 32, 44, 32)
        _line(painter, 27, 27, 27, 45)
        _line(painter, 37, 27, 37, 45)
        _line(painter, 25, 23, 39, 23)
    elif category == "rally_point":
        _line(painter, 25, 45, 25, 22)
        path = QtGui.QPainterPath(QtCore.QPointF(25, 24))
        path.lineTo(44, 24)
        path.lineTo(39, 31)
        path.lineTo(44, 38)
        path.lineTo(25, 38)
        painter.drawPath(path)
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        painter.setBrush(QtGui.QColor("#f6fbfb"))
        painter.drawEllipse(QtCore.QPointF(25, 45), 3, 3)
    elif category == "vehicle":
        _line(painter, 18, 39, 25, 39)
        _line(painter, 31, 39, 38, 39)
        path = QtGui.QPainterPath(QtCore.QPointF(44, 39))
        path.lineTo(46, 39)
        path.lineTo(46, 32)
        path.lineTo(39, 25)
        path.lineTo(24, 25)
        path.lineTo(24, 39)
        painter.drawPath(path)
        _line(painter, 24, 30, 35, 30)
        _line(painter, 35, 30, 35, 39)
        path = QtGui.QPainterPath(QtCore.QPointF(35, 30))
        path.lineTo(40, 30)
        path.lineTo(44, 34)
        painter.drawPath(path)
        painter.drawEllipse(QtCore.QPointF(28, 40), 3.5, 3.5)
        painter.drawEllipse(QtCore.QPointF(41, 40), 3.5, 3.5)
    else:
        painter.drawEllipse(QtCore.QPointF(32, 32), 9, 9)
        _line(painter, 32, 20, 32, 27)
        _line(painter, 32, 37, 32, 44)
        _line(painter, 20, 32, 27, 32)
        _line(painter, 37, 32, 44, 32)


def _rounded_rect(
    painter: QtGui.QPainter,
    x: float,
    y: float,
    width: float,
    height: float,
    radius: float,
) -> None:
    painter.drawRoundedRect(QtCore.QRectF(x, y, width, height), radius, radius)


def _line(
    painter: QtGui.QPainter,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
) -> None:
    painter.drawLine(QtCore.QPointF(x1, y1), QtCore.QPointF(x2, y2))
