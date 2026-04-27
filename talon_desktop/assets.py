"""Qt-free asset helpers for the PySide6 desktop client."""
from __future__ import annotations

import dataclasses
import typing

from talon_core.assets import CATEGORY_LABEL


@dataclasses.dataclass(frozen=True)
class AssetFormPayload:
    category: str
    label: str
    description: str
    lat: float | None
    lon: float | None


@dataclasses.dataclass(frozen=True)
class DesktopAssetItem:
    id: int
    category: str
    label: str
    description: str
    lat: float | None
    lon: float | None
    verified: bool
    created_by: int
    confirmed_by: int | None
    mission_id: int | None
    deletion_requested: bool

    @property
    def category_label(self) -> str:
        return CATEGORY_LABEL.get(self.category, self.category)

    @property
    def coordinate_text(self) -> str:
        if self.lat is None or self.lon is None:
            return ""
        return f"{self.lat:.6f}, {self.lon:.6f}"


ASSET_CATEGORY_OPTIONS: tuple[tuple[str, str], ...] = tuple(
    (category, label) for category, label in CATEGORY_LABEL.items()
)


def item_from_asset(asset: object) -> DesktopAssetItem:
    return DesktopAssetItem(
        id=int(_field(asset, "id")),
        category=str(_field(asset, "category")),
        label=str(_field(asset, "label")),
        description=str(_field(asset, "description", default="") or ""),
        lat=_optional_float(_field(asset, "lat", default=None)),
        lon=_optional_float(_field(asset, "lon", default=None)),
        verified=bool(_field(asset, "verified", default=False)),
        created_by=int(_field(asset, "created_by")),
        confirmed_by=_optional_int(_field(asset, "confirmed_by", default=None)),
        mission_id=_optional_int(_field(asset, "mission_id", default=None)),
        deletion_requested=bool(_field(asset, "deletion_requested", default=False)),
    )


def items_from_assets(assets: typing.Iterable[object]) -> list[DesktopAssetItem]:
    return [item_from_asset(asset) for asset in assets]


def build_create_payload(
    *,
    category: str,
    label: str,
    description: str,
    lat_text: str,
    lon_text: str,
) -> dict[str, object]:
    form = _build_form_payload(
        category=category,
        label=label,
        description=description,
        lat_text=lat_text,
        lon_text=lon_text,
    )
    return {
        "category": form.category,
        "label": form.label,
        "description": form.description,
        "lat": form.lat,
        "lon": form.lon,
    }


def build_update_payload(
    *,
    asset_id: int,
    label: str,
    description: str,
    lat_text: str,
    lon_text: str,
) -> dict[str, object]:
    form = _build_form_payload(
        category="custom",
        label=label,
        description=description,
        lat_text=lat_text,
        lon_text=lon_text,
    )
    return {
        "asset_id": int(asset_id),
        "label": form.label,
        "description": form.description,
        "lat": form.lat,
        "lon": form.lon,
    }


def can_verify_asset(
    *,
    mode: str,
    operator_id: int | None,
    asset_created_by: int,
) -> bool:
    if mode == "server":
        return True
    return operator_id is not None and operator_id != asset_created_by


def _build_form_payload(
    *,
    category: str,
    label: str,
    description: str,
    lat_text: str,
    lon_text: str,
) -> AssetFormPayload:
    category = category.strip()
    if category not in CATEGORY_LABEL:
        raise ValueError(f"Unknown asset category: {category!r}")
    label = label.strip()
    if not label:
        raise ValueError("Asset label is required.")

    lat = _parse_coordinate(lat_text, "Latitude", minimum=-90.0, maximum=90.0)
    lon = _parse_coordinate(lon_text, "Longitude", minimum=-180.0, maximum=180.0)
    if (lat is None) != (lon is None):
        raise ValueError("Both latitude and longitude are required together.")

    return AssetFormPayload(
        category=category,
        label=label,
        description=description.strip(),
        lat=lat,
        lon=lon,
    )


def _parse_coordinate(
    value: str,
    label: str,
    *,
    minimum: float,
    maximum: float,
) -> float | None:
    raw = value.strip()
    if not raw:
        return None
    try:
        parsed = float(raw)
    except ValueError as exc:
        raise ValueError(f"{label} must be a number.") from exc
    if parsed < minimum or parsed > maximum:
        raise ValueError(f"{label} must be between {minimum:g} and {maximum:g}.")
    return parsed


def _field(obj: object, name: str, *, default: object = None) -> object:
    if isinstance(obj, dict) and name in obj:
        return obj[name]
    if hasattr(obj, name):
        return getattr(obj, name)
    return default


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    return float(value)


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    return int(value)
