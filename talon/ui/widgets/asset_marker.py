"""
Asset map marker widget.

Renders a category-coloured circle at the asset's lat/lon on the MapWidget.
Verified assets   : solid dark border.
Unverified assets : dashed amber border — pending physical confirmation by a
                    second operator.

``source=""`` suppresses MapMarker's default pin image so we can draw our own
circle on canvas.before.  ``_redraw`` is bound to ``on_pos`` / ``on_size`` so
the shape stays correctly positioned as the map pans.
"""
from kivy.graphics import Color, Ellipse, Line
from kivy.properties import ObjectProperty
from kivy_garden.mapview import MapMarker

# Category fill colours (RGBA) — matches context_panel.py _CATEGORY_LABEL order
_FILL: dict[str, tuple] = {
    "person":      (0.20, 0.80, 0.20, 1.0),   # green
    "safe_house":  (0.20, 0.60, 1.00, 1.0),   # blue
    "cache":       (1.00, 0.70, 0.00, 1.0),   # amber
    "rally_point": (0.00, 0.90, 0.90, 1.0),   # cyan
    "vehicle":     (0.80, 0.40, 0.00, 1.0),   # orange
    "custom":      (0.70, 0.70, 0.70, 1.0),   # grey
}

_MARKER_SIZE = (32, 32)


class AssetMarker(MapMarker):
    """Circular asset pin with category colour and verified / unverified styling."""

    asset = ObjectProperty(None)

    def __init__(self, asset, **kwargs):
        kwargs["source"] = ""           # suppress default pin image
        kwargs["anchor_x"] = 0.5
        kwargs["anchor_y"] = 0.5
        super().__init__(**kwargs)
        self.asset = asset
        self.size = _MARKER_SIZE
        self.bind(pos=self._redraw, size=self._redraw)
        self._redraw()

    def _redraw(self, *_) -> None:
        x, y = self.pos
        w, h = self.size
        fill = _FILL.get(
            self.asset.category if self.asset else "custom",
            (0.7, 0.7, 0.7, 1.0),
        )
        self.canvas.before.clear()
        with self.canvas.before:
            # Fill circle
            Color(*fill)
            Ellipse(pos=(x, y), size=(w, h))
            # Border — dashed amber for unverified, solid dark for verified
            if self.asset and not self.asset.verified:
                Color(1.0, 0.65, 0.0, 1.0)
                Line(
                    ellipse=(x, y, w, h),
                    width=2.0,
                    dash_offset=3,
                    dash_length=5,
                )
            else:
                Color(0.0, 0.0, 0.0, 0.55)
                Line(ellipse=(x, y, w, h), width=1.5)
