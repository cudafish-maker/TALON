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
    asset_id: int | None
    assignment_id: int | None
    mission_id: int | None
    status: str
    location_label: str
    location_source: str
    point: ProjectedPoint


@dataclasses.dataclass(frozen=True)
class AssignmentOverlay:
    id: int
    title: str
    assignment_type: str
    status: str
    priority: str
    last_checkin_state: str
    point: ProjectedPoint


@dataclasses.dataclass(frozen=True)
class MissionLocationOverlay:
    mission_id: int
    mission_label: str
    key: str
    label: str
    point: ProjectedPoint


@dataclasses.dataclass(frozen=True)
class OperatorPingOverlay:
    id: int
    operator_id: int
    callsign: str
    source: str
    note: str
    created_at: int
    expires_at: int
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
    assignments: tuple[AssignmentOverlay, ...]
    mission_locations: tuple[MissionLocationOverlay, ...]
    operator_pings: tuple[OperatorPingOverlay, ...]


SCENE_WIDTH = 1000.0
SCENE_HEIGHT = 700.0
SCENE_MARGIN = 48.0
DEFAULT_MAP_BOUNDS = MapBounds(
    min_lat=-60.0,
    max_lat=75.0,
    min_lon=-170.0,
    max_lon=170.0,
)


def build_map_overlays(
    context: object,
    *,
    sitrep_entries: typing.Iterable[object] = (),
    bounds: MapBounds | None = None,
    scene_width: float = SCENE_WIDTH,
    scene_height: float = SCENE_HEIGHT,
    scene_margin: float = SCENE_MARGIN,
) -> MapOverlayBundle:
    assets = list(_field(context, "assets", default=[]) or [])
    zones = list(_field(context, "zones", default=[]) or [])
    waypoints = list(_field(context, "waypoints", default=[]) or [])
    missions = list(_field(context, "missions", default=[]) or [])
    assignments = list(_field(context, "assignments", default=[]) or [])
    operator_pings = list(_field(context, "operator_pings", default=[]) or [])
    selected_mission_id = _optional_int(_field(context, "selected_mission_id", default=None))
    overlay_missions = [
        mission
        for mission in missions
        if selected_mission_id is None or int(_field(mission, "id")) == selected_mission_id
    ]

    if bounds is None:
        bounds = bounds_for_context(
            assets=assets,
            zones=zones,
            waypoints=waypoints,
            assignments=assignments,
            operator_pings=operator_pings,
            missions=overlay_missions,
            sitrep_entries=sitrep_entries,
        )
        bounds = fit_bounds_to_scene_aspect(
            bounds,
            scene_width=scene_width,
            scene_height=scene_height,
            scene_margin=scene_margin,
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
                scene_width=scene_width,
                scene_height=scene_height,
                scene_margin=scene_margin,
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
                project_lat_lon(
                    bounds,
                    float(lat),
                    float(lon),
                    scene_width=scene_width,
                    scene_height=scene_height,
                    scene_margin=scene_margin,
                )
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
                scene_width=scene_width,
                scene_height=scene_height,
                scene_margin=scene_margin,
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
    assignment_overlays = tuple(
        AssignmentOverlay(
            id=int(_field(assignment, "id")),
            title=str(_field(assignment, "title", default="Assignment")),
            assignment_type=str(_field(assignment, "assignment_type", default="")),
            status=str(_field(assignment, "status", default="")),
            priority=str(_field(assignment, "priority", default="ROUTINE")),
            last_checkin_state=str(_field(assignment, "last_checkin_state", default="")),
            point=project_lat_lon(
                bounds,
                float(_field(assignment, "lat")),
                float(_field(assignment, "lon")),
                scene_width=scene_width,
                scene_height=scene_height,
                scene_margin=scene_margin,
            ),
        )
        for assignment in assignments
        if _has_coordinates(assignment)
    )
    assignment_by_id = {item.id: item for item in assignment_overlays}
    sitrep_items = []
    for entry in sitrep_entries:
        overlay = _sitrep_overlay(
            entry,
            asset_by_id,
            assignment_by_id,
            bounds=bounds,
            scene_width=scene_width,
            scene_height=scene_height,
            scene_margin=scene_margin,
        )
        if overlay is not None:
            sitrep_items.append(overlay)
    mission_location_items = _mission_location_overlays(
        overlay_missions,
        bounds=bounds,
        scene_width=scene_width,
        scene_height=scene_height,
        scene_margin=scene_margin,
    )
    operator_ping_items = tuple(
        OperatorPingOverlay(
            id=int(_field(ping, "id")),
            operator_id=int(_field(ping, "operator_id")),
            callsign=str(_field(ping, "operator_callsign", default="UNKNOWN") or "UNKNOWN"),
            source=str(_field(ping, "source", default="") or ""),
            note=str(_field(ping, "note", default="") or ""),
            created_at=int(_field(ping, "created_at", default=0) or 0),
            expires_at=int(_field(ping, "expires_at", default=0) or 0),
            mission_id=_optional_int(_field(ping, "mission_id", default=None)),
            point=project_lat_lon(
                bounds,
                float(_field(ping, "lat")),
                float(_field(ping, "lon")),
                scene_width=scene_width,
                scene_height=scene_height,
                scene_margin=scene_margin,
            ),
        )
        for ping in operator_pings
        if _has_coordinates(ping)
    )

    return MapOverlayBundle(
        bounds=bounds,
        assets=asset_overlays,
        zones=zone_overlays,
        waypoints=waypoint_overlays,
        routes=routes,
        sitreps=tuple(sitrep_items),
        assignments=assignment_overlays,
        mission_locations=mission_location_items,
        operator_pings=operator_ping_items,
    )


def bounds_for_context(
    *,
    assets: typing.Iterable[object],
    zones: typing.Iterable[object],
    waypoints: typing.Iterable[object],
    assignments: typing.Iterable[object] = (),
    operator_pings: typing.Iterable[object] = (),
    missions: typing.Iterable[object] = (),
    sitrep_entries: typing.Iterable[object] = (),
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
    for assignment in assignments:
        if _has_coordinates(assignment):
            coords.append((float(_field(assignment, "lat")), float(_field(assignment, "lon"))))
    for ping in operator_pings:
        if _has_coordinates(ping):
            coords.append((float(_field(ping, "lat")), float(_field(ping, "lon"))))
    for mission in missions:
        coords.extend(_mission_location_points(mission))
    for entry in sitrep_entries:
        sitrep = entry[0] if isinstance(entry, tuple) else entry
        if _has_coordinates(sitrep):
            coords.append((float(_field(sitrep, "lat")), float(_field(sitrep, "lon"))))

    if not coords:
        return DEFAULT_MAP_BOUNDS

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


def fit_bounds_to_scene_aspect(
    bounds: MapBounds,
    *,
    scene_width: float = SCENE_WIDTH,
    scene_height: float = SCENE_HEIGHT,
    scene_margin: float = SCENE_MARGIN,
) -> MapBounds:
    """Expand auto-fit bounds so map tiles do not stretch to the viewport."""
    from talon_desktop.map_tiles import lat_lon_for_world_pixel, normalise_bounds, world_pixel

    bounds = normalise_bounds(bounds)
    usable_width, usable_height = _usable_scene_size(
        scene_width,
        scene_height,
        scene_margin,
    )
    target_aspect = usable_width / usable_height
    projection_zoom = 20
    world_size = 256 * (2**projection_zoom)
    left, top = world_pixel(bounds.max_lat, bounds.min_lon, projection_zoom)
    right, bottom = world_pixel(bounds.min_lat, bounds.max_lon, projection_zoom)
    span_x = max(1.0, right - left)
    span_y = max(1.0, bottom - top)
    current_aspect = span_x / span_y
    if abs(current_aspect - target_aspect) < 0.01:
        return bounds

    if current_aspect < target_aspect:
        span_x = span_y * target_aspect
    else:
        span_y = span_x / target_aspect
    span_x = min(world_size, max(1.0, span_x))
    span_y = min(world_size, max(1.0, span_y))
    center_x = (left + right) / 2.0
    center_y = (top + bottom) / 2.0
    left = _clamp(center_x - (span_x / 2.0), 0.0, world_size - span_x)
    top = _clamp(center_y - (span_y / 2.0), 0.0, world_size - span_y)
    max_lat, min_lon = lat_lon_for_world_pixel(left, top, projection_zoom)
    min_lat, max_lon = lat_lon_for_world_pixel(
        left + span_x,
        top + span_y,
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


def project_lat_lon(
    bounds: MapBounds,
    lat: float,
    lon: float,
    *,
    scene_width: float = SCENE_WIDTH,
    scene_height: float = SCENE_HEIGHT,
    scene_margin: float = SCENE_MARGIN,
) -> ProjectedPoint:
    from talon_desktop.map_tiles import scene_point_for_lat_lon

    x, y = scene_point_for_lat_lon(
        bounds,
        lat,
        lon,
        scene_width=scene_width,
        scene_height=scene_height,
        scene_margin=scene_margin,
    )
    return ProjectedPoint(lat=lat, lon=lon, x=x, y=y)


def _mission_location_overlays(
    missions: typing.Iterable[object],
    *,
    bounds: MapBounds,
    scene_width: float,
    scene_height: float,
    scene_margin: float,
) -> tuple[MissionLocationOverlay, ...]:
    items: list[MissionLocationOverlay] = []
    for mission in missions:
        mission_id = int(_field(mission, "id"))
        mission_label = str(_field(mission, "title", default=f"Mission {mission_id}"))
        for key, label, point in _mission_location_entries(mission):
            items.append(
                MissionLocationOverlay(
                    mission_id=mission_id,
                    mission_label=mission_label,
                    key=key,
                    label=label,
                    point=project_lat_lon(
                        bounds,
                        point[0],
                        point[1],
                        scene_width=scene_width,
                        scene_height=scene_height,
                        scene_margin=scene_margin,
                    ),
                )
            )
    return tuple(items)


def _sitrep_overlay(
    entry: object,
    assets_by_id: dict[int, AssetOverlay],
    assignments_by_id: dict[int, AssignmentOverlay],
    *,
    bounds: MapBounds,
    scene_width: float,
    scene_height: float,
    scene_margin: float,
) -> SitrepOverlay | None:
    sitrep = entry[0] if isinstance(entry, tuple) else entry
    asset_id = _optional_int(_field(sitrep, "asset_id", default=None))
    assignment_id = _optional_int(_field(sitrep, "assignment_id", default=None))
    lat = _optional_float(_field(sitrep, "lat", default=None))
    lon = _optional_float(_field(sitrep, "lon", default=None))
    location_source = str(_field(sitrep, "location_source", default="") or "")
    if lat is not None and lon is not None:
        point = project_lat_lon(
            bounds,
            lat,
            lon,
            scene_width=scene_width,
            scene_height=scene_height,
            scene_margin=scene_margin,
        )
    elif asset_id is not None and asset_id in assets_by_id:
        point = assets_by_id[asset_id].point
        location_source = location_source or "asset"
    elif assignment_id is not None and assignment_id in assignments_by_id:
        point = assignments_by_id[assignment_id].point
        location_source = location_source or "assignment"
    else:
        return None
    return SitrepOverlay(
        id=int(_field(sitrep, "id")),
        level=str(_field(sitrep, "level", default="ROUTINE")),
        body=_text(_field(sitrep, "body", default="")),
        asset_id=asset_id,
        assignment_id=assignment_id,
        mission_id=_optional_int(_field(sitrep, "mission_id", default=None)),
        status=str(_field(sitrep, "status", default="open") or "open"),
        location_label=str(_field(sitrep, "location_label", default="") or ""),
        location_source=location_source,
        point=point,
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


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    return float(value)


def _text(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if value is None:
        return ""
    return str(value)


def _mission_location_points(mission: object) -> list[tuple[float, float]]:
    return [point for _key, _label, point in _mission_location_entries(mission)]


def _mission_location_entries(
    mission: object,
) -> list[tuple[str, str, tuple[float, float]]]:
    entries: list[tuple[str, str, tuple[float, float]]] = []
    for key, label, value in (
        ("staging_area", "Staging Area", _field(mission, "staging_area", default="")),
        ("demob_point", "Demob Point", _field(mission, "demob_point", default="")),
    ):
        point = _coordinate_from_text(value)
        if point is not None:
            entries.append((key, label, point))

    locations = _field(mission, "key_locations", default={}) or {}
    if isinstance(locations, dict):
        for key, label in (
            ("command_post", "Command Post"),
            ("staging_area", "Staging Area"),
            ("medical", "Medical"),
            ("evacuation", "Evacuation"),
            ("supply", "Supply"),
        ):
            point = _coordinate_from_text(locations.get(key))
            if point is not None:
                entries.append((key, label, point))
    return entries


def _coordinate_from_text(value: object) -> tuple[float, float] | None:
    text = str(value or "").strip()
    if not text:
        return None
    parts = [part.strip() for part in text.replace(" ", ",").split(",") if part.strip()]
    if len(parts) != 2:
        return None
    try:
        lat = float(parts[0])
        lon = float(parts[1])
    except ValueError:
        return None
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return None
    return lat, lon


def _usable_scene_size(
    scene_width: float,
    scene_height: float,
    scene_margin: float,
) -> tuple[float, float]:
    width = max(1.0, float(scene_width))
    height = max(1.0, float(scene_height))
    margin = max(0.0, min(float(scene_margin), (min(width, height) / 2.0) - 0.5))
    return max(1.0, width - (margin * 2.0)), max(1.0, height - (margin * 2.0))


def _clamp(value: float, minimum: float, maximum: float) -> float:
    if maximum < minimum:
        return minimum
    return max(minimum, min(maximum, value))
