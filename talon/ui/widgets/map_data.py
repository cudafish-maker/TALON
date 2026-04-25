"""
Shared operational map context.

Map screens should not each decide which tactical records belong on the map.
This module loads the canonical "map picture" from the database so browse maps,
mission drawing modals, and point pickers can render the same assets, zones,
missions, and routes.
"""
from __future__ import annotations

import dataclasses
import typing

from talon.db.connection import Connection
from talon.db.models import Asset, Mission, Waypoint, Zone


@dataclasses.dataclass
class MapContext:
    """Immutable-ish bundle of records that can be rendered on a map."""

    assets: list[Asset] = dataclasses.field(default_factory=list)
    zones: list[Zone] = dataclasses.field(default_factory=list)
    waypoints: list[Waypoint] = dataclasses.field(default_factory=list)
    missions: list[Mission] = dataclasses.field(default_factory=list)

    @property
    def missions_by_id(self) -> dict[int, Mission]:
        return {mission.id: mission for mission in self.missions}

    def with_assets(self, assets: typing.Iterable[Asset]) -> "MapContext":
        """Return a copy with a caller-selected visible asset set."""
        return dataclasses.replace(self, assets=list(assets))

    def with_visible_assets(
        self,
        asset_ids: typing.Optional[typing.Iterable[int]],
        *,
        selected_mission_id: typing.Optional[int] = None,
    ) -> "MapContext":
        """
        Return a copy with map-visible assets filtered by operator choice.

        ``asset_ids=None`` means show every asset.  When a mission is selected,
        assets linked to that mission are always included even if they are not
        part of the operator-selected baseline set.
        """
        if asset_ids is None:
            return self
        selected = set(asset_ids)
        visible_assets = [
            asset for asset in self.assets
            if asset.id in selected
            or (
                selected_mission_id is not None
                and asset.mission_id == selected_mission_id
            )
        ]
        return dataclasses.replace(self, assets=visible_assets)

    def with_selected_mission_overlays(
        self,
        mission_id: typing.Optional[int],
    ) -> "MapContext":
        """
        Return a copy scoped to the selected mission's route/area overlays.

        Assets and missions remain global. Standalone zones remain visible,
        while mission-linked zones and waypoints are hidden until their mission
        is selected.
        """
        selected_zones = [
            zone for zone in self.zones
            if zone.mission_id is None or zone.mission_id == mission_id
        ]
        selected_waypoints = [
            waypoint for waypoint in self.waypoints
            if mission_id is not None and waypoint.mission_id == mission_id
        ]
        return dataclasses.replace(
            self,
            zones=selected_zones,
            waypoints=selected_waypoints,
        )


def load_map_context(
    conn: Connection,
    *,
    mission_id: typing.Optional[int] = None,
    limit: int = 500,
) -> MapContext:
    """
    Load the shared operational map picture.

    When ``mission_id`` is supplied, mission-scoped overlays (zones/routes) are
    filtered to that mission.  Assets remain global because pickers often need
    surrounding resources for spatial context while drawing or selecting.
    """
    from talon.assets import load_assets
    from talon.missions import load_missions
    from talon.zones import load_zones

    assets = load_assets(conn, limit=limit)
    zones = load_zones(conn, mission_id=mission_id, limit=limit)
    waypoints = load_waypoints_for_map(conn, mission_id=mission_id, limit=limit)
    missions = load_missions(conn, limit=limit)
    return MapContext(
        assets=assets,
        zones=zones,
        waypoints=waypoints,
        missions=missions,
    )


def load_waypoints_for_map(
    conn: Connection,
    *,
    mission_id: typing.Optional[int] = None,
    limit: int = 1000,
) -> list[Waypoint]:
    """Load ordered mission waypoints for route display on map overlays."""
    clauses: list[str] = []
    params: list[object] = []
    if mission_id is not None:
        clauses.append("mission_id = ?")
        params.append(mission_id)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(limit)
    rows = conn.execute(
        "SELECT id, mission_id, sequence, label, lat, lon, version "
        f"FROM waypoints {where} "
        "ORDER BY mission_id ASC, sequence ASC LIMIT ?",
        params,
    ).fetchall()
    return [
        Waypoint(
            id=r[0],
            mission_id=r[1],
            sequence=r[2],
            label=r[3],
            lat=r[4],
            lon=r[5],
            version=r[6],
        )
        for r in rows
    ]
