# talon/ui/screens/assets.py
# Assets panel — list of tracked assets with map integration.
#
# Layout:
#   ┌─────────────────────────────────┐
#   │  ASSETS              [+ NEW]    │
#   ├─────────────────────────────────┤
#   │  [■] Cache Alpha    VERIFIED ✓  │
#   │      SUPPLY_CACHE · Alpha       │
#   ├─────────────────────────────────┤
#   │  [■] Vehicle Bravo  UNVERIFIED  │
#   │      VEHICLE · Bravo            │
#   └─────────────────────────────────┘
#
# Tapping an asset centres the map on it and opens a detail pane.
# The [+ NEW] button opens the add-asset dialog.
# Operators can verify assets (not their own) from the detail pane.


from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDButton, MDIconButton
from kivymd.uix.dialog import (
    MDDialog,
    MDDialogButtonContainer,
    MDDialogContentContainer,
    MDDialogHeadlineText,
)
from kivymd.uix.label import MDLabel
from kivymd.uix.list import IconLeftWidget, MDList, TwoLineIconListItem
from kivymd.uix.scrollview import MDScrollView
from kivymd.uix.textfield import MDTextField

from talon.db.models import Asset
from talon.models.asset import can_verify, validate_asset, verify_asset

# Colour per verification status
VERIFY_COLORS = {
    "verified": "#00e5a0",
    "unverified": "#f5a623",
    "compromised": "#ff3b3b",
}


class AssetsPanel(MDBoxLayout):
    """Context panel content for the Assets section."""

    def __init__(self, **kwargs):
        super().__init__(orientation="vertical", **kwargs)
        self._talon = None
        self._assets = []
        self._add_dialog = None
        self._build_ui()

    def _build_ui(self):
        # Header
        header = MDBoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height="52dp",
            padding=["16dp", "8dp"],
            md_bg_color="#0f1520",
        )
        header.add_widget(
            MDLabel(
                text="ASSETS",
                font_style="Label", role="large",
                bold=True,
                theme_text_color="Custom",
                text_color="#e8edf4",
            )
        )
        header.add_widget(
            MDIconButton(
                icon="plus",
                theme_icon_color="Custom",
                icon_color="#00e5a0",
                on_release=lambda x: self.open_add_dialog(),
            )
        )
        self.add_widget(header)

        from kivymd.uix.divider import MDDivider

        self.add_widget(MDDivider(color="#1e2d3d"))

        scroll = MDScrollView(size_hint_y=1)
        self._list = MDList(md_bg_color="#0f1520")
        scroll.add_widget(self._list)
        self.add_widget(scroll)

    def refresh(self, talon_client):
        self._talon = talon_client
        self._assets = []
        self._list.clear_widgets()

        if not talon_client or not talon_client.cache:
            return

        try:
            self._assets = talon_client.cache.get_all("assets") or []
        except Exception:
            return

        self._assets.sort(key=lambda a: a.name)

        for asset in self._assets:
            self._add_list_item(asset)

    def _add_list_item(self, asset):
        color = VERIFY_COLORS.get(asset.verification, "#8a9bb0")
        verify_text = asset.verification.upper()
        if asset.verification == "verified":
            verify_text += " ✓"

        item = TwoLineIconListItem(
            text=f"{asset.name}  [color={color}]{verify_text}[/color]",
            secondary_text=f"{asset.category} · {asset.created_by}",
            markup=True,
            on_release=lambda x, a=asset: self.open_asset_detail(a),
            md_bg_color="#151d2b",
        )
        icon = IconLeftWidget(
            icon="package-variant",
            theme_icon_color="Custom",
            icon_color=color,
        )
        item.add_widget(icon)
        self._list.add_widget(item)

    def open_asset_detail(self, asset):
        """Show detail pane and centre map on the asset."""
        # Centre the map
        from kivy.app import App

        app = App.get_running_app()
        main = app.screen_manager.get_screen("main")
        map_widget = main.ids.get("map_widget_desktop") or main.ids.get("map_widget_mobile")
        if map_widget and asset.latitude and asset.longitude:
            map_widget.centre_on(asset.latitude, asset.longitude, zoom=15)

        self.clear_widgets()
        self._build_detail(asset)

    def _build_detail(self, asset):
        color = VERIFY_COLORS.get(asset.verification, "#8a9bb0")

        header = MDBoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height="52dp",
            padding=["8dp", "8dp"],
            md_bg_color="#0f1520",
        )
        header.add_widget(
            MDIconButton(
                icon="arrow-left",
                theme_icon_color="Custom",
                icon_color="#8a9bb0",
                on_release=lambda x: self._back_to_list(),
            )
        )
        header.add_widget(
            MDLabel(
                text=asset.name,
                font_style="Label", role="large",
                bold=True,
                theme_text_color="Custom",
                text_color="#e8edf4",
            )
        )
        self.add_widget(header)

        from kivymd.uix.divider import MDDivider

        self.add_widget(MDDivider(color="#1e2d3d"))

        details = MDBoxLayout(
            orientation="vertical",
            size_hint_y=None,
            padding=["16dp", "12dp"],
            spacing="8dp",
        )
        details.bind(minimum_height=details.setter("height"))

        def detail_row(label, value, value_color=None):
            row = MDBoxLayout(orientation="horizontal", size_hint_y=None, height="24dp")
            row.add_widget(
                MDLabel(
                    text=label,
                    font_style="Body", role="small",
                    theme_text_color="Custom",
                    text_color="#8a9bb0",
                    size_hint_x=0.4,
                )
            )
            row.add_widget(
                MDLabel(
                    text=value,
                    font_style="Body", role="small",
                    theme_text_color="Custom",
                    text_color=value_color or "#e8edf4",
                    size_hint_x=0.6,
                )
            )
            return row

        details.add_widget(detail_row("Category", asset.category))
        details.add_widget(detail_row("Status", asset.status))
        details.add_widget(
            detail_row(
                "Verification",
                asset.verification.upper(),
                color,
            )
        )
        details.add_widget(detail_row("Created by", asset.created_by))
        if asset.verified_by:
            details.add_widget(detail_row("Verified by", asset.verified_by))
        if asset.latitude and asset.longitude:
            coords = f"{asset.latitude:.5f}, {asset.longitude:.5f}"
            details.add_widget(detail_row("Coordinates", coords))
        if asset.notes:
            details.add_widget(detail_row("Notes", asset.notes))

        self.add_widget(details)

        # Verify button — only shown if the current operator can verify
        callsign = self._get_my_callsign()
        if can_verify(asset, callsign, "operator"):
            verify_btn = MDButton(
                style="elevated",
                text="VERIFY ASSET",
                md_bg_color="#00e5a0",
                theme_text_color="Custom",
                text_color="#0a0e14",
                size_hint_x=None,
                pos_hint={"center_x": 0.5},
                on_release=lambda x: self._verify_asset(asset),
            )
            self.add_widget(verify_btn)

    def _verify_asset(self, asset):
        """Mark an asset as verified by the current operator."""
        callsign = self._get_my_callsign()
        updated = verify_asset(asset, callsign)

        if self._talon and self._talon.sync:
            self._talon.sync.queue_change("assets", "update", updated)
        if self._talon and self._talon.cache:
            try:
                self._talon.cache.save_asset(updated)
            except Exception:
                pass

        self._back_to_list()

    def _back_to_list(self):
        self.clear_widgets()
        self._build_ui()
        if self._talon:
            self.refresh(self._talon)

    def open_add_dialog(self):
        content = _AssetAddContent()
        self._add_dialog = MDDialog(
            MDDialogHeadlineText(text="New Asset"),
            MDDialogContentContainer(content),
            MDDialogButtonContainer(
                MDButton(
                    style="elevated",
                    text="CANCEL",
                    md_bg_color="#1c2637",
                    theme_text_color="Custom",
                    text_color="#8a9bb0",
                    on_release=lambda x: self._add_dialog.dismiss(),
                ),
                MDButton(
                    style="elevated",
                    text="ADD",
                    md_bg_color="#00e5a0",
                    theme_text_color="Custom",
                    text_color="#0a0e14",
                    on_release=lambda x: self._submit_new_asset(content),
                ),
            ),
        )
        self._add_dialog.open()

    def _submit_new_asset(self, content):
        callsign = self._get_my_callsign()
        name = content.name_field.text.strip()
        category = content.selected_category
        notes = content.notes_field.text.strip()

        if not name:
            return

        lat_text = content.lat_field.text.strip()
        lon_text = content.lon_field.text.strip()
        latitude = float(lat_text) if lat_text else None
        longitude = float(lon_text) if lon_text else None

        asset = Asset(
            name=name,
            category=category,
            created_by=callsign,
            notes=notes,
            latitude=latitude,
            longitude=longitude,
        )

        errors = validate_asset(asset)
        if errors:
            return  # TODO: show validation errors in dialog

        if self._talon:
            if self._talon.sync:
                self._talon.sync.queue_change("assets", "insert", asset)
            if self._talon.cache:
                try:
                    self._talon.cache.save_asset(asset)
                except Exception:
                    pass

        self._add_dialog.dismiss()
        self._back_to_list()

    def _get_my_callsign(self) -> str:
        if not self._talon or not self._talon.cache:
            return ""
        try:
            return self._talon.cache.get_my_callsign() or ""
        except Exception:
            return ""


class _AssetAddContent(MDBoxLayout):
    """Content for the add-asset dialog."""

    CATEGORIES = ["VEHICLE", "SUPPLY_CACHE", "PERSONNEL", "EQUIPMENT", "POSITION", "OTHER"]

    def __init__(self, **kwargs):
        super().__init__(
            orientation="vertical",
            size_hint_y=None,
            spacing="12dp",
            padding=["8dp", "8dp"],
            **kwargs,
        )
        self.bind(minimum_height=self.setter("height"))
        self.selected_category = "VEHICLE"
        self._build()

    def _build(self):
        self.name_field = MDTextField(
            hint_text="Asset name",
            mode="rectangle",
            fill_color_normal="#151d2b",
            fill_color_focus="#151d2b",
            line_color_focus="#00e5a0",
            size_hint_y=None,
            height="48dp",
        )
        self.add_widget(self.name_field)

        # Category picker (simple row of buttons)
        cat_label = MDLabel(
            text="Category",
            font_style="Body", role="small",
            theme_text_color="Custom",
            text_color="#8a9bb0",
            size_hint_y=None,
            height="20dp",
        )
        self.add_widget(cat_label)

        for cat in self.CATEGORIES:
            btn = MDButton(
                style="elevated",
                text=cat,
                md_bg_color="#00e5a0" if cat == self.selected_category else "#1c2637",
                theme_text_color="Custom",
                text_color="#0a0e14" if cat == self.selected_category else "#8a9bb0",
                size_hint_y=None,
                height="36dp",
                on_release=lambda x, c=cat: self._select_category(c),
            )
            self.add_widget(btn)

        # Coordinate fields
        coord_row = MDBoxLayout(
            size_hint_y=None,
            height="48dp",
            spacing="8dp",
        )
        self.lat_field = MDTextField(
            hint_text="Latitude (optional)",
            mode="rectangle",
            fill_color_normal="#151d2b",
            fill_color_focus="#151d2b",
            line_color_focus="#00e5a0",
            input_filter="float",
        )
        self.lon_field = MDTextField(
            hint_text="Longitude (optional)",
            mode="rectangle",
            fill_color_normal="#151d2b",
            fill_color_focus="#151d2b",
            line_color_focus="#00e5a0",
            input_filter="float",
        )
        coord_row.add_widget(self.lat_field)
        coord_row.add_widget(self.lon_field)
        self.add_widget(coord_row)

        self.notes_field = MDTextField(
            hint_text="Notes (optional)",
            mode="rectangle",
            fill_color_normal="#151d2b",
            fill_color_focus="#151d2b",
            line_color_focus="#00e5a0",
            size_hint_y=None,
            height="48dp",
        )
        self.add_widget(self.notes_field)

    def _select_category(self, cat):
        self.selected_category = cat
        self.clear_widgets()
        self._build()
