"""Qt-free map projection and overlay helpers for desktop."""
from __future__ import annotations

import dataclasses
import typing


@dataclasses.dataclass(frozen=True)
class MapBounds:
    min_lat: float
    max_lat: float
    min_lon: float
    max_lon: float


@dataclasses.dataclass(frozen=True)
class ProjectedPoint:
    lat: float
    lon: float
    x: float
    y: float


@dataclasses.dataclass(frozen=True)
class AssetOverlay:
    id: int
    label: str
    category: str
    verified: bool
    mission_id: int | None
    point: ProjectedPoint


@dataclasses.dataclass(frozen=True)
class ZoneOverlay:
    id: int
    label: str
    zone_type: str
    mission_id: int | None
    points: tuple[ProjectedPoint, ...]


@dataclasses.dataclass(frozen=True)
class WaypointOverlay:
    id: int
    label: str
    sequence: int
    mission_id: int
    point: ProjectedPoint


@dataclasses.dataclass(frozen=True)
class RouteOverlay:
    mission_id: int
    mission_label: str
    points: tuple[ProjectedPoint, ...]


@dataclasses.dataclass(frozen=True)
class SitrepOverlay:
    id: int
    level: str
    body: str
    asset_id: int
    mission_id: int | None
    point: ProjectedPoint


@dataclasses.dataclass(frozen=True)
class MapOverlayBundle:
    bounds: MapBounds
    assets: tuple[AssetOverlay, ...]
    zones: tuple[ZoneOverlay, ...]
    waypoints: tuple[WaypointOverlay, ...]
    routes: tuple[RouteOverlay, ...]
    sitreps: tuple[SitrepOverlay, ...]


SCENE_WIDTH = 1000.0
SCENE_HEIGHT = 700.0
SCENE_MARGIN = 48.0


def build_map_overlays(
    context: object,
    *,
    sitrep_entries: typing.Iterable[object] = (),
) -> MapOverlayBundle:
    assets = list(_field(context, "assets", default=[]) or [])
    zones = list(_field(context, "zones", default=[]) or [])
    waypoints = list(_field(context, "waypoints", default=[]) or [])
    missions = list(_field(context, "missions", default=[]) or [])

    bounds = bounds_for_context(
        assets=assets,
        zones=zones,
        waypoints=waypoints,
    )
    mission_labels = {
        int(_field(mission, "id")): str(_field(mission, "title", default="Mission"))
        for mission in missions
    }

    asset_overlays = tuple(
        AssetOverlay(
            id=int(_field(asset, "id")),
            label=str(_field(asset, "label", default="Asset")),
            category=str(_field(asset, "category", default="custom")),
            verified=bool(_field(asset, "verified", default=False)),
            mission_id=_optional_int(_field(asset, "mission_id", default=None)),
            point=project_lat_lon(
                bounds,
                float(_field(asset, "lat")),
                float(_field(asset, "lon")),
            ),
        )
        for asset in assets
        if _has_coordinates(asset)
    )

    zone_overlays = tuple(
        ZoneOverlay(
            id=int(_field(zone, "id")),
            label=str(_field(zone, "label", default="Zone")),
            zone_type=str(_field(zone, "zone_type", default="custom")),
            mission_id=_optional_int(_field(zone, "mission_id", default=None)),
            points=tuple(
                project_lat_lon(bounds, float(lat), float(lon))
                for lat, lon in (_field(zone, "polygon", default=[]) or [])
            ),
        )
        for zone in zones
        if len(_field(zone, "polygon", default=[]) or []) >= 3
    )

    waypoint_overlays = tuple(
        WaypointOverlay(
            id=int(_field(point, "id")),
            label=str(_field(point, "label", default="Waypoint")),
            sequence=int(_field(point, "sequence", default=0)),
            mission_id=int(_field(point, "mission_id")),
            point=project_lat_lon(
                bounds,
                float(_field(point, "lat")),
                float(_field(point, "lon")),
            ),
        )
        for point in waypoints
    )

    route_groups: dict[int, list[WaypointOverlay]] = {}
    for waypoint in waypoint_overlays:
        route_groups.setdefault(waypoint.mission_id, []).append(waypoint)
    routes = tuple(
        RouteOverlay(
            mission_id=mission_id,
            mission_label=mission_labels.get(mission_id, f"Mission {mission_id}"),
            points=tuple(item.point for item in sorted(group, key=lambda item: item.sequence)),
        )
        for mission_id, group in sorted(route_groups.items())
        if len(group) >= 2
    )

    asset_by_id = {item.id: item for item in asset_overlays}
    sitrep_items = []
    for entry in sitrep_entries:
        overlay = _sitrep_overlay(entry, asset_by_id)
        if overlay is not None:
            sitrep_items.append(overlay)

    return MapOverlayBundle(
        bounds=bounds,
        assets=asset_overlays,
        zones=zone_overlays,
        waypoints=waypoint_overlays,
        routes=routes,
        sitreps=tuple(sitrep_items),
    )


def bounds_for_context(
    *,
    assets: typing.Iterable[object],
    zones: typing.Iterable[object],
    waypoints: typing.Iterable[object],
) -> MapBounds:
    coords: list[tuple[float, float]] = []
    for asset in assets:
        if _has_coordinates(asset):
            coords.append((float(_field(asset, "lat")), float(_field(asset, "lon"))))
    for zone in zones:
        for lat, lon in (_field(zone, "polygon", default=[]) or []):
            coords.append((float(lat), float(lon)))
    for waypoint in waypoints:
        coords.append((float(_field(waypoint, "lat")), float(_field(waypoint, "lon"))))

    if not coords:
        return MapBounds(min_lat=-0.01, max_lat=0.01, min_lon=-0.01, max_lon=0.01)

    lats = [lat for lat, _lon in coords]
    lons = [lon for _lat, lon in coords]
    min_lat, max_lat = min(lats), max(lats)
    min_lon, max_lon = min(lons), max(lons)
    if min_lat == max_lat:
        min_lat -= 0.01
        max_lat += 0.01
    if min_lon == max_lon:
        min_lon -= 0.01
        max_lon += 0.01
    lat_pad = (max_lat - min_lat) * 0.08
    lon_pad = (max_lon - min_lon) * 0.08
    return MapBounds(
        min_lat=min_lat - lat_pad,
        max_lat=max_lat + lat_pad,
        min_lon=min_lon - lon_pad,
        max_lon=max_lon + lon_pad,
    )


def project_lat_lon(bounds: MapBounds, lat: float, lon: float) -> ProjectedPoint:
    x_span = bounds.max_lon - bounds.min_lon
    y_span = bounds.max_lat - bounds.min_lat
    usable_width = SCENE_WIDTH - (SCENE_MARGIN * 2)
    usable_height = SCENE_HEIGHT - (SCENE_MARGIN * 2)
    x = SCENE_MARGIN + ((lon - bounds.min_lon) / x_span) * usable_width
    y = SCENE_MARGIN + ((bounds.max_lat - lat) / y_span) * usable_height
    return ProjectedPoint(lat=lat, lon=lon, x=x, y=y)


def _sitrep_overlay(
    entry: object,
    assets_by_id: dict[int, AssetOverlay],
) -> SitrepOverlay | None:
    sitrep = entry[0] if isinstance(entry, tuple) else entry
    asset_id = _optional_int(_field(sitrep, "asset_id", default=None))
    if asset_id is None:
        return None
    asset = assets_by_id.get(asset_id)
    if asset is None:
        return None
    return SitrepOverlay(
        id=int(_field(sitrep, "id")),
        level=str(_field(sitrep, "level", default="ROUTINE")),
        body=_text(_field(sitrep, "body", default="")),
        asset_id=asset_id,
        mission_id=_optional_int(_field(sitrep, "mission_id", default=None)),
        point=asset.point,
    )


def _has_coordinates(obj: object) -> bool:
    return _field(obj, "lat", default=None) is not None and _field(
        obj,
        "lon",
        default=None,
    ) is not None


def _field(obj: object, name: str, *, default: object = None) -> object:
    if isinstance(obj, dict) and name in obj:
        return obj[name]
    if hasattr(obj, name):
        return getattr(obj, name)
    return default


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    return int(value)


def _text(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if value is None:
        return ""
    return str(value)
