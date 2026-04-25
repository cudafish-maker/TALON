"""
Context panel — right-side detail / status pane in the three-column layout.

Default state  : Situation Summary — operators online, active mission, latest SITREP.
Detail state   : pushed when the user taps an asset, zone, or waypoint on the map.
                 A back-arrow header button always returns to the summary.

Public API
----------
show_summary()
    Render (or return to) the situation summary view.
show_asset(asset)
    Push asset detail for a tapped marker.
show_zone(zone)
    Push zone detail.
show_waypoint(waypoint)
    Push waypoint detail.
update_summary(operators_online, active_mission, latest_sitrep)
    Refresh live data; if the summary is currently displayed it re-renders
    immediately.  Called by the sync engine on state changes.
"""
import datetime
import typing

from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.scrollview import ScrollView
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDIconButton
from kivymd.uix.divider import MDDivider
from kivymd.uix.label import MDLabel

from talon.assets import CATEGORY_COLOR as _CATEGORY_COLOR, CATEGORY_LABEL as _CATEGORY_LABEL
from talon.ui.theme import SITREP_COLORS as _SITREP_COLOUR  # BUG-019
from talon.ui.widgets.info_row import InfoRow as _InfoRow

_ZONE_TYPE_LABEL: dict[str, str] = {
    "AO":         "Area of Operations",
    "DANGER":     "Danger Area",
    "RESTRICTED": "Restricted",
    "FRIENDLY":   "Friendly",
    "OBJECTIVE":  "Objective",
}


# ---------------------------------------------------------------------------
# Internal helper: tappable asset row for the situation summary
# ---------------------------------------------------------------------------

class _AssetListRow(ButtonBehavior, MDBoxLayout):
    """One tappable row in the ASSETS section of the situation summary.

    Layout:  [CAT]  Label                  lat, lon / No GPS
    Pressing the row fires ``on_tap(asset)``.
    """

    def __init__(
        self,
        asset,
        on_tap: typing.Callable,
        **kwargs,
    ):
        super().__init__(
            orientation="horizontal",
            adaptive_height=True,
            spacing="6dp",
            padding=("0dp", "4dp"),
            **kwargs,
        )
        self._asset = asset
        self._on_tap = on_tap

        color = _CATEGORY_COLOR.get(asset.category, _CATEGORY_COLOR["custom"])
        cat_abbr = _CATEGORY_LABEL.get(asset.category, asset.category)[:3].upper()

        self.add_widget(MDLabel(
            text=cat_abbr,
            font_style="Label",
            role="small",
            theme_text_color="Custom",
            text_color=color,
            bold=True,
            size_hint_x=None,
            width="36dp",
            adaptive_height=True,
        ))
        self.add_widget(MDLabel(
            text=asset.label,
            font_style="Body",
            role="small",
            adaptive_height=True,
        ))

        if asset.lat is not None and asset.lon is not None:
            coord_text = f"{asset.lat:.3f}, {asset.lon:.3f}"
        else:
            coord_text = "No GPS"
        self.add_widget(MDLabel(
            text=coord_text,
            font_style="Label",
            role="small",
            theme_text_color="Secondary",
            halign="right",
            size_hint_x=None,
            width="90dp",
            adaptive_height=True,
        ))

    def on_release(self) -> None:
        self._on_tap(self._asset)


# ---------------------------------------------------------------------------
# ContextPanel
# ---------------------------------------------------------------------------

class ContextPanel(MDBoxLayout):
    """Right-column context panel — situation summary or map-item detail."""

    def __init__(self, **kwargs):
        super().__init__(
            orientation="vertical",
            padding="8dp",
            spacing="4dp",
            **kwargs,
        )
        self._summary_data: dict[str, str] = {
            "operators_online": "--",
            "active_mission":   "--",
            "latest_sitrep":    "--",
        }
        self._assets: typing.Optional[list] = None       # None = not yet loaded
        self._on_asset_selected: typing.Optional[typing.Callable] = None
        self._current_view: str = "summary"  # BUG-024
        self._build_chrome()
        self.show_summary()

    # ------------------------------------------------------------------
    # Permanent chrome (header + scroll container)
    # ------------------------------------------------------------------

    def _build_chrome(self) -> None:
        header = MDBoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height="40dp",
            spacing="4dp",
        )
        self._back_btn = MDIconButton(
            icon="arrow-left",
            style="standard",
            size_hint=(None, None),
            size=("40dp", "40dp"),
            opacity=0,
        )
        self._back_btn.disabled = True
        self._back_btn.bind(on_release=lambda *_: self.show_summary())

        self._header_label = MDLabel(
            text="",
            font_style="Title",
            role="small",
            valign="center",
        )
        header.add_widget(self._back_btn)
        header.add_widget(self._header_label)
        self.add_widget(header)
        self.add_widget(MDDivider())

        scroll = ScrollView(size_hint=(1, 1))
        self._content = MDBoxLayout(
            orientation="vertical",
            spacing="6dp",
            padding=("0dp", "8dp"),
            adaptive_height=True,
        )
        scroll.add_widget(self._content)
        self.add_widget(scroll)

    # ------------------------------------------------------------------
    # Content helpers
    # ------------------------------------------------------------------

    def _set_header(self, title: str, show_back: bool = False) -> None:
        self._header_label.text = title
        self._back_btn.opacity = 1.0 if show_back else 0.0
        self._back_btn.disabled = not show_back

    def _clear_content(self) -> None:
        self._content.clear_widgets()

    def _add_section(self, title: str) -> None:
        self._content.add_widget(MDLabel(
            text=title,
            font_style="Label",
            role="small",
            theme_text_color="Secondary",
            adaptive_height=True,
        ))
        self._content.add_widget(MDDivider())

    def _add_row(
        self,
        label: str,
        value: str,
        value_color: tuple | None = None,
    ) -> None:
        self._content.add_widget(_InfoRow(label, value, value_color))

    def _add_text(self, text: str) -> None:
        lbl = MDLabel(
            text=text,
            font_style="Body",
            role="small",
            theme_text_color="Secondary",
            adaptive_height=True,
        )
        # Enable word-wrap once the widget has a known width.
        lbl.bind(width=lambda inst, w: setattr(inst, "text_size", (w, None)))
        self._content.add_widget(lbl)

    # ------------------------------------------------------------------
    # Public views
    # ------------------------------------------------------------------

    def set_assets(
        self,
        assets: list,
        on_asset_selected: typing.Optional[typing.Callable] = None,
    ) -> None:
        """Replace the asset list shown in the summary.

        ``on_asset_selected(asset)`` is called when the user taps a row.
        Re-renders immediately if the summary is currently visible.
        """
        self._assets = list(assets)
        self._on_asset_selected = on_asset_selected
        if self._current_view == "summary":
            self.show_summary()

    def show_summary(self) -> None:
        """Render (or return to) the situation summary."""
        self._current_view = "summary"
        self._set_header("SITUATION", show_back=False)
        self._clear_content()
        d = self._summary_data
        self._add_section("STATUS")
        self._add_row("Operators", d["operators_online"])
        self._add_row("Mission",   d["active_mission"])
        sitrep = d["latest_sitrep"]
        level = sitrep.split()[0] if sitrep != "--" else "--"
        self._add_row(
            "SITREP",
            sitrep,
            value_color=_SITREP_COLOUR.get(level),
        )

        if self._assets is not None:
            count = len(self._assets)
            section_title = f"ASSETS ({count})" if count else "ASSETS"
            self._add_section(section_title)
            if self._assets:
                for asset in self._assets:
                    self._content.add_widget(_AssetListRow(
                        asset=asset,
                        on_tap=self._on_asset_selected or (lambda _: None),
                    ))
            else:
                self._add_text("No assets.")

    def update_summary(
        self,
        operators_online: int | str = "--",
        active_mission: str = "--",
        latest_sitrep: str = "--",
    ) -> None:
        """Refresh live data from the sync engine.

        If the summary is currently on screen it re-renders immediately.
        Safe to call from a background thread via ``Clock.schedule_once``.
        """
        self._summary_data = {
            "operators_online": str(operators_online),
            "active_mission":   active_mission,
            "latest_sitrep":    latest_sitrep,
        }
        if self._current_view == "summary":  # BUG-024
            self.show_summary()

    def show_asset(self, asset, linked_sitreps: list | None = None) -> None:
        """Push asset detail for a tapped map marker.

        linked_sitreps: list of (Sitrep, callsign) pairs for SITREPs that
        reference this asset.  Pass an empty list or None to show nothing.
        """
        self._current_view = "asset"
        self._set_header("ASSET", show_back=True)
        self._clear_content()

        cat_label = _CATEGORY_LABEL.get(asset.category, asset.category).upper()
        self._add_section(cat_label)
        self._add_row("Label", asset.label or "—")

        if asset.verified:
            self._add_row("Status", "✓  VERIFIED",
                          value_color=(0.20, 0.90, 0.20, 1.0))
        else:
            self._add_row("Status", "⚠  UNVERIFIED",
                          value_color=(1.00, 0.65, 0.00, 1.0))

        if asset.lat is not None and asset.lon is not None:
            lat_str = f"{abs(asset.lat):.5f}° {'N' if asset.lat >= 0 else 'S'}"
            lon_str = f"{abs(asset.lon):.5f}° {'E' if asset.lon >= 0 else 'W'}"
            self._add_row("Lat", lat_str)
            self._add_row("Lon", lon_str)
        else:
            self._add_row("Location", "No coordinates")

        if asset.description:
            self._add_section("DESCRIPTION")
            self._add_text(asset.description)

        created = datetime.datetime.fromtimestamp(asset.created_at)
        self._add_row("Created", created.strftime("%Y-%m-%d %H:%M"))

        self._add_section("ACTIONS")
        self._add_text("Edit / Verify actions available in the Asset screen.")

        if linked_sitreps:
            self._add_section(f"LINKED SITREPS ({len(linked_sitreps)})")
            for sitrep, callsign in linked_sitreps:
                body_text = (
                    sitrep.body.decode("utf-8", errors="replace")
                    if isinstance(sitrep.body, bytes) else str(sitrep.body)
                )
                if len(body_text) > 80:
                    body_text = body_text[:77] + "\u2026"
                color = _SITREP_COLOUR.get(sitrep.level)
                self._add_row(sitrep.level, body_text, value_color=color)

    def show_zone(self, zone) -> None:
        """Push zone detail."""
        self._current_view = "zone"
        self._set_header("ZONE", show_back=True)
        self._clear_content()

        heading = zone.label.upper() if zone.label else "ZONE"
        self._add_section(heading)
        self._add_row(
            "Type",
            _ZONE_TYPE_LABEL.get(zone.zone_type, zone.zone_type),
        )
        mission_text = (
            f"Mission #{zone.mission_id}" if zone.mission_id else "Standalone"
        )
        self._add_row("Mission",  mission_text)
        self._add_row("Vertices", str(len(zone.polygon) if zone.polygon else 0))

        created = datetime.datetime.fromtimestamp(zone.created_at)
        self._add_row("Created", created.strftime("%Y-%m-%d %H:%M"))

    def show_waypoint(self, waypoint) -> None:
        """Push waypoint detail."""
        self._current_view = "waypoint"
        self._set_header("WAYPOINT", show_back=True)
        self._clear_content()

        heading = f"{waypoint.sequence}.  {(waypoint.label or 'Waypoint').upper()}"
        self._add_section(heading)
        self._add_row("Mission", f"Mission #{waypoint.mission_id}")

        if waypoint.lat is not None and waypoint.lon is not None:  # BUG-018
            lat_str = f"{abs(waypoint.lat):.5f}° {'N' if waypoint.lat >= 0 else 'S'}"
            lon_str = f"{abs(waypoint.lon):.5f}° {'E' if waypoint.lon >= 0 else 'W'}"
            self._add_row("Lat", lat_str)
            self._add_row("Lon", lon_str)
        else:
            self._add_row("Location", "No coordinates")
