"""Desktop chat view models and payload helpers."""
from __future__ import annotations

import dataclasses
import datetime
import typing

from talon_core.constants import DEFAULT_CHANNELS

_DEFAULT_CHANNEL_SET = frozenset(DEFAULT_CHANNELS)


@dataclasses.dataclass(frozen=True)
class DesktopChannelItem:
    id: int
    name: str
    mission_id: int | None
    is_dm: bool
    group_type: str
    display_name: str
    group_label: str
    is_default: bool


@dataclasses.dataclass(frozen=True)
class DesktopMessageItem:
    id: int
    channel_id: int
    sender_id: int
    callsign: str
    body: str
    sent_at: int
    sent_time: str
    is_urgent: bool
    grid_ref: str


@dataclasses.dataclass(frozen=True)
class DesktopOperatorItem:
    id: int
    callsign: str
    role: str
    online: bool


@dataclasses.dataclass(frozen=True)
class DesktopGridReferenceItem:
    kind: str
    label: str
    reference: str
    lat: float
    lon: float
    detail: str


def item_from_channel(
    channel: object,
    *,
    operator_lookup: typing.Mapping[int, str] | None = None,
) -> DesktopChannelItem:
    name = str(getattr(channel, "name", "")).strip()
    is_dm = bool(getattr(channel, "is_dm", False))
    group_type = str(getattr(channel, "group_type", "") or ("direct" if is_dm else "squad"))
    return DesktopChannelItem(
        id=int(getattr(channel, "id")),
        name=name,
        mission_id=_optional_int(getattr(channel, "mission_id", None)),
        is_dm=is_dm,
        group_type=group_type,
        display_name=_display_channel_name(
            name,
            is_dm=is_dm,
            operator_lookup=operator_lookup or {},
        ),
        group_label=_group_label(group_type),
        is_default=name in _DEFAULT_CHANNEL_SET,
    )


def items_from_channels(
    channels: typing.Iterable[object],
    *,
    operator_lookup: typing.Mapping[int, str] | None = None,
) -> list[DesktopChannelItem]:
    return [
        item_from_channel(channel, operator_lookup=operator_lookup)
        for channel in channels
    ]


def item_from_message(entry: object) -> DesktopMessageItem:
    if isinstance(entry, tuple):
        message = entry[0]
        callsign = str(entry[1]) if len(entry) > 1 else "UNKNOWN"
    else:
        message = entry
        callsign = str(getattr(message, "callsign", "UNKNOWN"))
    sent_at = int(getattr(message, "sent_at", 0) or 0)
    grid_ref = str(getattr(message, "grid_ref", "") or "").strip()
    return DesktopMessageItem(
        id=int(getattr(message, "id")),
        channel_id=int(getattr(message, "channel_id")),
        sender_id=int(getattr(message, "sender_id")),
        callsign=callsign,
        body=_as_text(getattr(message, "body", "")),
        sent_at=sent_at,
        sent_time=_format_sent_at(sent_at),
        is_urgent=bool(getattr(message, "is_urgent", False)),
        grid_ref=grid_ref,
    )


def items_from_messages(entries: typing.Iterable[object]) -> list[DesktopMessageItem]:
    return [item_from_message(entry) for entry in entries]


def operator_item_from_mapping(operator: typing.Mapping[str, object]) -> DesktopOperatorItem:
    return DesktopOperatorItem(
        id=int(operator["id"]),
        callsign=str(operator.get("callsign", "UNKNOWN")),
        role=str(operator.get("role", "") or ""),
        online=bool(operator.get("online", False)),
    )


def items_from_operators(
    operators: typing.Iterable[typing.Mapping[str, object]],
) -> list[DesktopOperatorItem]:
    return [operator_item_from_mapping(operator) for operator in operators]


def grid_reference_items_from_context(
    context: object,
    *,
    sitrep_entries: typing.Iterable[object] = (),
) -> list[DesktopGridReferenceItem]:
    """Build chat-attachable location references from the map read model."""
    items: list[DesktopGridReferenceItem] = []
    assets = list(_field(context, "assets", default=[]) or [])
    asset_locations: dict[int, tuple[float, float, str]] = {}
    for asset in assets:
        lat = _optional_float(_field(asset, "lat", default=None))
        lon = _optional_float(_field(asset, "lon", default=None))
        if lat is None or lon is None:
            continue
        asset_id = int(_field(asset, "id"))
        label = str(_field(asset, "label", default=f"Asset #{asset_id}"))
        category = str(_field(asset, "category", default="asset")).replace("_", " ")
        asset_locations[asset_id] = (lat, lon, label)
        items.append(
            _grid_item(
                "ASSET",
                label,
                lat,
                lon,
                detail=f"{category.title()} #{asset_id}",
            )
        )

    for waypoint in list(_field(context, "waypoints", default=[]) or []):
        lat = _optional_float(_field(waypoint, "lat", default=None))
        lon = _optional_float(_field(waypoint, "lon", default=None))
        if lat is None or lon is None:
            continue
        waypoint_id = int(_field(waypoint, "id"))
        mission_id = int(_field(waypoint, "mission_id"))
        label = str(_field(waypoint, "label", default=f"Waypoint #{waypoint_id}"))
        sequence = int(_field(waypoint, "sequence", default=0))
        items.append(
            _grid_item(
                "WAYPOINT",
                label,
                lat,
                lon,
                detail=f"Mission {mission_id} waypoint {sequence}",
            )
        )

    for zone in list(_field(context, "zones", default=[]) or []):
        centroid = _polygon_centroid(_field(zone, "polygon", default=[]) or [])
        if centroid is None:
            continue
        lat, lon = centroid
        zone_id = int(_field(zone, "id"))
        zone_type = str(_field(zone, "zone_type", default="zone"))
        label = str(_field(zone, "label", default=f"Zone #{zone_id}"))
        items.append(
            _grid_item(
                "ZONE",
                label,
                lat,
                lon,
                detail=f"{zone_type.title()} centroid #{zone_id}",
            )
        )

    for entry in sitrep_entries:
        sitrep = entry[0] if isinstance(entry, tuple) else entry
        asset_id = _optional_int(_field(sitrep, "asset_id", default=None))
        if asset_id is None or asset_id not in asset_locations:
            continue
        lat, lon, asset_label = asset_locations[asset_id]
        sitrep_id = int(_field(sitrep, "id"))
        level = str(_field(sitrep, "level", default="SITREP"))
        items.append(
            _grid_item(
                "SITREP",
                f"{level} #{sitrep_id}",
                lat,
                lon,
                detail=f"Linked to {asset_label}",
            )
        )

    return sorted(items, key=lambda item: (item.kind, item.label.lower(), item.reference))


def build_create_channel_payload(name: str) -> dict[str, object]:
    value = name.strip()
    if not value:
        raise ValueError("Channel name is required.")
    return {"name": value}


def build_dm_payload(
    *,
    current_operator_id: int,
    peer_operator_id: int,
) -> dict[str, object]:
    current = int(current_operator_id)
    peer = int(peer_operator_id)
    if current <= 0 or peer <= 0:
        raise ValueError("A valid operator is required.")
    if current == peer:
        raise ValueError("Cannot create a DM with yourself.")
    return {"operator_a_id": current, "operator_b_id": peer}


def build_message_payload(
    *,
    channel_id: int,
    body: str,
    is_urgent: bool = False,
    grid_ref: str = "",
) -> dict[str, object]:
    cid = int(channel_id)
    if cid <= 0:
        raise ValueError("A channel is required.")
    message_body = body.strip()
    if not message_body:
        raise ValueError("Message body is required.")
    grid_value = grid_ref.strip()
    return {
        "channel_id": cid,
        "body": message_body,
        "is_urgent": bool(is_urgent),
        "grid_ref": grid_value or None,
    }


def can_delete_channel(mode: str, item: DesktopChannelItem | None) -> bool:
    if mode != "server" or item is None:
        return False
    return not item.is_default and item.group_type != "mission"


def can_delete_message(mode: str, item: DesktopMessageItem | None) -> bool:
    return mode == "server" and item is not None


def operator_lookup_from_items(
    operators: typing.Iterable[DesktopOperatorItem],
) -> dict[int, str]:
    return {operator.id: operator.callsign for operator in operators}


def _display_channel_name(
    name: str,
    *,
    is_dm: bool,
    operator_lookup: typing.Mapping[int, str],
) -> str:
    if not is_dm:
        return name
    try:
        _, left_raw, right_raw = name.split(":", 2)
        left = int(left_raw)
        right = int(right_raw)
    except (TypeError, ValueError):
        return name
    left_label = operator_lookup.get(left, f"#{left}")
    right_label = operator_lookup.get(right, f"#{right}")
    return f"DM {left_label} / {right_label}"


def _group_label(group_type: str) -> str:
    return {
        "emergency": "Emergency",
        "allhands": "All Hands",
        "mission": "Mission",
        "squad": "Squad",
        "direct": "Direct",
    }.get(group_type, group_type.replace("_", " ").title() or "Channel")


def _format_sent_at(sent_at: int) -> str:
    if sent_at <= 0:
        return "--:--"
    return datetime.datetime.fromtimestamp(sent_at).strftime("%H:%M")


def _as_text(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if value is None:
        return ""
    return str(value)


def _field(obj: object, name: str, *, default: object = None) -> object:
    if isinstance(obj, dict) and name in obj:
        return obj[name]
    if hasattr(obj, name):
        return getattr(obj, name)
    return default


def _optional_int(value: object) -> int | None:
    if value in (None, ""):
        return None
    return int(typing.cast(int, value))


def _optional_float(value: object) -> float | None:
    if value in (None, ""):
        return None
    return float(typing.cast(float, value))


def _polygon_centroid(polygon: typing.Iterable[object]) -> tuple[float, float] | None:
    points: list[tuple[float, float]] = []
    for point in polygon:
        try:
            lat, lon = typing.cast(typing.Sequence[object], point)[:2]
            points.append((float(lat), float(lon)))
        except (TypeError, ValueError):
            continue
    if not points:
        return None
    return (
        sum(lat for lat, _lon in points) / len(points),
        sum(lon for _lat, lon in points) / len(points),
    )


def _grid_item(
    kind: str,
    label: str,
    lat: float,
    lon: float,
    *,
    detail: str,
) -> DesktopGridReferenceItem:
    reference = f"{kind} {label} {lat:.6f}, {lon:.6f}"
    return DesktopGridReferenceItem(
        kind=kind,
        label=label,
        reference=reference,
        lat=lat,
        lon=lon,
        detail=detail,
    )
