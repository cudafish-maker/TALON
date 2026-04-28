"""Raster tile layer definitions and Web Mercator helpers for desktop maps."""
from __future__ import annotations

import dataclasses
import math

from talon_desktop.map_data import (
    SCENE_HEIGHT,
    SCENE_MARGIN,
    SCENE_WIDTH,
    MapBounds,
)

TILE_SIZE = 256
MAX_TILE_REQUESTS = 72
WEB_MERCATOR_MAX_LAT = 85.05112878


@dataclasses.dataclass(frozen=True)
class TileLayer:
    key: str
    label: str
    url_template: str
    attribution: str
    min_zoom: int = 2
    max_zoom: int = 18

    def url(self, *, zoom: int, x: int, y: int) -> str:
        return self.url_template.format(z=zoom, x=x, y=y)


@dataclasses.dataclass(frozen=True)
class TileRequest:
    url: str
    zoom: int
    x: int
    y: int
    scene_x: float
    scene_y: float
    scene_width: float
    scene_height: float


@dataclasses.dataclass(frozen=True)
class TilePlan:
    layer: TileLayer
    bounds: MapBounds
    zoom: int
    requests: tuple[TileRequest, ...]


TILE_LAYERS: tuple[TileLayer, ...] = (
    TileLayer(
        key="osm",
        label="OSM",
        url_template="https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        attribution="OpenStreetMap contributors",
        max_zoom=19,
    ),
    TileLayer(
        key="topo",
        label="TOPO",
        url_template="https://tile.openmaps.fr/opentopomap/{z}/{x}/{y}.png",
        attribution="OpenStreetMap contributors, OpenTopoMap style",
        max_zoom=17,
    ),
    TileLayer(
        key="satellite",
        label="Satellite",
        url_template=(
            "https://server.arcgisonline.com/ArcGIS/rest/services/"
            "World_Imagery/MapServer/tile/{z}/{y}/{x}"
        ),
        attribution="Source: Esri World Imagery",
        max_zoom=18,
    ),
)

TILE_LAYERS_BY_KEY = {layer.key: layer for layer in TILE_LAYERS}


def normalise_bounds(bounds: MapBounds) -> MapBounds:
    min_lat = _clamp_lat(min(bounds.min_lat, bounds.max_lat))
    max_lat = _clamp_lat(max(bounds.min_lat, bounds.max_lat))
    min_lon = max(-180.0, min(bounds.min_lon, bounds.max_lon))
    max_lon = min(180.0, max(bounds.min_lon, bounds.max_lon))
    if min_lat == max_lat:
        min_lat = _clamp_lat(min_lat - 0.01)
        max_lat = _clamp_lat(max_lat + 0.01)
    if min_lon == max_lon:
        min_lon = max(-180.0, min_lon - 0.01)
        max_lon = min(180.0, max_lon + 0.01)
    return MapBounds(
        min_lat=min_lat,
        max_lat=max_lat,
        min_lon=min_lon,
        max_lon=max_lon,
    )


def world_pixel(lat: float, lon: float, zoom: int) -> tuple[float, float]:
    lat = _clamp_lat(lat)
    lon = max(-180.0, min(180.0, lon))
    scale = TILE_SIZE * (2**zoom)
    x = (lon + 180.0) / 360.0 * scale
    lat_rad = math.radians(lat)
    y = (
        1.0
        - math.log(math.tan(lat_rad) + (1.0 / math.cos(lat_rad))) / math.pi
    ) / 2.0 * scale
    return x, y


def scene_point_for_lat_lon(
    bounds: MapBounds,
    lat: float,
    lon: float,
    *,
    zoom: int | None = None,
    scene_width: float = SCENE_WIDTH,
    scene_height: float = SCENE_HEIGHT,
    scene_margin: float = SCENE_MARGIN,
) -> tuple[float, float]:
    bounds = normalise_bounds(bounds)
    z = zoom if zoom is not None else choose_zoom(
        bounds,
        scene_width=scene_width,
        scene_height=scene_height,
        scene_margin=scene_margin,
    )
    left, top, span_x, span_y = _world_view(bounds, z)
    point_x, point_y = world_pixel(lat, lon, z)
    margin, usable_width, usable_height = _scene_metrics(
        scene_width,
        scene_height,
        scene_margin,
    )
    x = margin + ((point_x - left) / span_x) * usable_width
    y = margin + ((point_y - top) / span_y) * usable_height
    return x, y


def lat_lon_for_scene_point(
    bounds: MapBounds,
    x: float,
    y: float,
    *,
    zoom: int | None = None,
    scene_width: float = SCENE_WIDTH,
    scene_height: float = SCENE_HEIGHT,
    scene_margin: float = SCENE_MARGIN,
) -> tuple[float, float]:
    bounds = normalise_bounds(bounds)
    z = zoom if zoom is not None else choose_zoom(
        bounds,
        scene_width=scene_width,
        scene_height=scene_height,
        scene_margin=scene_margin,
    )
    left, top, span_x, span_y = _world_view(bounds, z)
    margin, usable_width, usable_height = _scene_metrics(
        scene_width,
        scene_height,
        scene_margin,
    )
    ratio_x = max(0.0, min(1.0, (x - margin) / usable_width))
    ratio_y = max(0.0, min(1.0, (y - margin) / usable_height))
    world_x = left + (ratio_x * span_x)
    world_y = top + (ratio_y * span_y)
    return lat_lon_for_world_pixel(world_x, world_y, z)


def lat_lon_for_world_pixel(x: float, y: float, zoom: int) -> tuple[float, float]:
    scale = TILE_SIZE * (2**zoom)
    lon = (x / scale * 360.0) - 180.0
    mercator = math.pi - ((2.0 * math.pi * y) / scale)
    lat = math.degrees(math.atan(math.sinh(mercator)))
    return _clamp_lat(lat), max(-180.0, min(180.0, lon))


def zoom_bounds_around_scene_point(
    bounds: MapBounds,
    x: float,
    y: float,
    factor: float,
    *,
    scene_width: float = SCENE_WIDTH,
    scene_height: float = SCENE_HEIGHT,
    scene_margin: float = SCENE_MARGIN,
) -> MapBounds:
    if factor <= 0:
        raise ValueError("Map zoom factor must be positive.")
    bounds = normalise_bounds(bounds)
    projection_zoom = 20
    left, top, span_x, span_y = _world_view(bounds, projection_zoom)
    margin, usable_width, usable_height = _scene_metrics(
        scene_width,
        scene_height,
        scene_margin,
    )
    ratio_x = max(0.0, min(1.0, (x - margin) / usable_width))
    ratio_y = max(0.0, min(1.0, (y - margin) / usable_height))
    anchor_x = left + (ratio_x * span_x)
    anchor_y = top + (ratio_y * span_y)
    next_span_x = max(1.0, span_x / factor)
    next_span_y = max(1.0, span_y / factor)
    world_size = TILE_SIZE * (2**projection_zoom)
    next_left = _clamp(
        anchor_x - (ratio_x * next_span_x),
        0.0,
        world_size - next_span_x,
    )
    next_top = _clamp(anchor_y - (ratio_y * next_span_y), 0.0, world_size - next_span_y)
    max_lat, min_lon = lat_lon_for_world_pixel(next_left, next_top, projection_zoom)
    min_lat, max_lon = lat_lon_for_world_pixel(
        next_left + next_span_x,
        next_top + next_span_y,
        projection_zoom,
    )
    return normalise_bounds(
        MapBounds(
            min_lat=min_lat,
            max_lat=max_lat,
            min_lon=min_lon,
            max_lon=max_lon,
        )
    )


def pan_bounds_by_scene_delta(
    bounds: MapBounds,
    delta_x: float,
    delta_y: float,
    *,
    scene_width: float = SCENE_WIDTH,
    scene_height: float = SCENE_HEIGHT,
    scene_margin: float = SCENE_MARGIN,
) -> MapBounds:
    """Move map bounds so dragged content follows the cursor."""
    bounds = normalise_bounds(bounds)
    projection_zoom = 20
    left, top, span_x, span_y = _world_view(bounds, projection_zoom)
    _margin, usable_width, usable_height = _scene_metrics(
        scene_width,
        scene_height,
        scene_margin,
    )
    world_size = TILE_SIZE * (2**projection_zoom)
    next_left = _clamp(
        left - ((delta_x / usable_width) * span_x),
        0.0,
        world_size - span_x,
    )
    next_top = _clamp(
        top - ((delta_y / usable_height) * span_y),
        0.0,
        world_size - span_y,
    )
    max_lat, min_lon = lat_lon_for_world_pixel(next_left, next_top, projection_zoom)
    min_lat, max_lon = lat_lon_for_world_pixel(
        next_left + span_x,
        next_top + span_y,
        projection_zoom,
    )
    return normalise_bounds(
        MapBounds(
            min_lat=min_lat,
            max_lat=max_lat,
            min_lon=min_lon,
            max_lon=max_lon,
        )
    )


def build_tile_plan(
    layer: TileLayer,
    bounds: MapBounds,
    *,
    scene_width: float = SCENE_WIDTH,
    scene_height: float = SCENE_HEIGHT,
    scene_margin: float = SCENE_MARGIN,
) -> TilePlan:
    bounds = normalise_bounds(bounds)
    zoom = choose_zoom(
        bounds,
        min_zoom=layer.min_zoom,
        max_zoom=layer.max_zoom,
        scene_width=scene_width,
        scene_height=scene_height,
        scene_margin=scene_margin,
    )
    requests = _requests_for_zoom(
        layer,
        bounds,
        zoom,
        scene_width=scene_width,
        scene_height=scene_height,
        scene_margin=scene_margin,
    )
    while len(requests) > MAX_TILE_REQUESTS and zoom > layer.min_zoom:
        zoom -= 1
        requests = _requests_for_zoom(
            layer,
            bounds,
            zoom,
            scene_width=scene_width,
            scene_height=scene_height,
            scene_margin=scene_margin,
        )
    return TilePlan(layer=layer, bounds=bounds, zoom=zoom, requests=tuple(requests))


def choose_zoom(
    bounds: MapBounds,
    *,
    min_zoom: int = 2,
    max_zoom: int = 18,
    scene_width: float = SCENE_WIDTH,
    scene_height: float = SCENE_HEIGHT,
    scene_margin: float = SCENE_MARGIN,
) -> int:
    bounds = normalise_bounds(bounds)
    _margin, usable_width, usable_height = _scene_metrics(
        scene_width,
        scene_height,
        scene_margin,
    )
    chosen = min_zoom
    for zoom in range(min_zoom, max_zoom + 1):
        _left, _top, span_x, span_y = _world_view(bounds, zoom)
        chosen = zoom
        if span_x >= usable_width or span_y >= usable_height:
            break
    return chosen


def _requests_for_zoom(
    layer: TileLayer,
    bounds: MapBounds,
    zoom: int,
    *,
    scene_width: float = SCENE_WIDTH,
    scene_height: float = SCENE_HEIGHT,
    scene_margin: float = SCENE_MARGIN,
) -> list[TileRequest]:
    left, top, span_x, span_y = _world_view(bounds, zoom)
    right = left + span_x
    bottom = top + span_y
    tile_count = 2**zoom
    min_x = max(0, int(math.floor(left / TILE_SIZE)))
    max_x = min(tile_count - 1, int(math.floor((right - 0.001) / TILE_SIZE)))
    min_y = max(0, int(math.floor(top / TILE_SIZE)))
    max_y = min(tile_count - 1, int(math.floor((bottom - 0.001) / TILE_SIZE)))
    margin, usable_width, usable_height = _scene_metrics(
        scene_width,
        scene_height,
        scene_margin,
    )
    requests: list[TileRequest] = []
    for tile_y in range(min_y, max_y + 1):
        for tile_x in range(min_x, max_x + 1):
            tile_left = tile_x * TILE_SIZE
            tile_top = tile_y * TILE_SIZE
            scene_x = margin + ((tile_left - left) / span_x) * usable_width
            scene_y = margin + ((tile_top - top) / span_y) * usable_height
            scene_w = (TILE_SIZE / span_x) * usable_width
            scene_h = (TILE_SIZE / span_y) * usable_height
            requests.append(
                TileRequest(
                    url=layer.url(zoom=zoom, x=tile_x, y=tile_y),
                    zoom=zoom,
                    x=tile_x,
                    y=tile_y,
                    scene_x=scene_x,
                    scene_y=scene_y,
                    scene_width=scene_w,
                    scene_height=scene_h,
                )
            )
    return requests


def _world_view(bounds: MapBounds, zoom: int) -> tuple[float, float, float, float]:
    left, top = world_pixel(bounds.max_lat, bounds.min_lon, zoom)
    right, bottom = world_pixel(bounds.min_lat, bounds.max_lon, zoom)
    return left, top, max(1.0, right - left), max(1.0, bottom - top)


def _scene_metrics(
    scene_width: float,
    scene_height: float,
    scene_margin: float,
) -> tuple[float, float, float]:
    width = max(1.0, float(scene_width))
    height = max(1.0, float(scene_height))
    margin = max(0.0, min(float(scene_margin), (min(width, height) / 2.0) - 0.5))
    usable_width = max(1.0, width - (margin * 2.0))
    usable_height = max(1.0, height - (margin * 2.0))
    return margin, usable_width, usable_height


def _clamp_lat(lat: float) -> float:
    return max(-WEB_MERCATOR_MAX_LAT, min(WEB_MERCATOR_MAX_LAT, lat))


def _clamp(value: float, minimum: float, maximum: float) -> float:
    if maximum < minimum:
        return minimum
    return max(minimum, min(maximum, value))
