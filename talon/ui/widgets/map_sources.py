"""Shared tile source definitions for all TALON map views."""

from __future__ import annotations

from kivy_garden.mapview import MapSource

DEFAULT_MAP_LAYER = "osm"

MAP_SOURCES: dict[str, MapSource] = {
    "osm": MapSource(
        url="https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        attribution="OpenStreetMap contributors",
        max_zoom=19,
    ),
    "satellite": MapSource(
        url="https://server.arcgisonline.com/ArcGIS/rest/services/"
            "World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attribution="Esri - World Imagery",
        max_zoom=19,
    ),
    "topo": MapSource(
        url="https://tile.opentopomap.org/{z}/{x}/{y}.png",
        attribution="OpenTopoMap contributors",
        max_zoom=17,
    ),
}
