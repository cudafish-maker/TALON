"""
Asset management screen — browse, create, and edit assets.

Assets represent real-world entities: people, safe houses, caches, rally
points, vehicles, and custom items.  They are unverified until a second
operator or the server physically confirms them.
"""
import typing

from kivy.app import App
from kivy.metrics import dp
from kivy.uix.modalview import ModalView
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDButton, MDButtonText, MDIconButton
from kivymd.uix.label import MDLabel
from kivymd.uix.menu import MDDropdownMenu
from kivymd.uix.screen import MDScreen
from kivymd.uix.textfield import MDTextField, MDTextFieldHintText

from talon.constants import ASSET_CATEGORIES
from talon.ui.widgets.map_draw import PointPickerModal
from talon.utils.logging import get_logger

_log = get_logger("ui.assets")

# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

from talon.assets import CATEGORY_COLOR as _CATEGORY_COLOR, CATEGORY_LABEL as _CATEGORY_LABEL

_ALL_CATEGORIES: tuple = (*ASSET_CATEGORIES, "custom")


def _parse_float(text: str) -> typing.Optional[float]:
    """Return float from a text field value, or None if empty / invalid."""
    stripped = text.strip()
    if not stripped:
        return None
    try:
        return float(stripped)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Main screen class
# ---------------------------------------------------------------------------

class AssetScreen(MDScreen):
    """Asset list screen with inline create/edit dialogs."""

    def on_kv_post(self, base_widget) -> None:
        self._category_filter: typing.Optional[str] = None
        self._build_filter_menu()

    def on_pre_enter(self) -> None:
        App.get_running_app().clear_badge("assets")
        self._load_assets()

    def on_back_pressed(self) -> None:
        self.manager.current = "main"

    def on_refresh_pressed(self) -> None:
        self._load_assets()

    def on_add_pressed(self) -> None:
        self._open_create_dialog()

    # ------------------------------------------------------------------
    # Category filter
    # ------------------------------------------------------------------

    def _build_filter_menu(self) -> None:
        items = [{"text": "All", "on_release": lambda: self._set_filter(None)}]
        for cat in _ALL_CATEGORIES:
            label = _CATEGORY_LABEL.get(cat, cat.capitalize())
            items.append({
                "text": label,
                "on_release": lambda c=cat: self._set_filter(c),
            })
        self._filter_menu = MDDropdownMenu(
            caller=self.ids.filter_button,
            items=items,
            position="bottom",
            width_mult=3,
        )

    def on_filter_pressed(self) -> None:
        self._filter_menu.open()

    def _set_filter(self, category: typing.Optional[str]) -> None:
        self._category_filter = category
        label = _CATEGORY_LABEL.get(category, "All") if category else "All"
        self.ids.filter_button_text.text = label
        self._filter_menu.dismiss()
        self._load_assets()

    # ------------------------------------------------------------------
    # Asset list
    # ------------------------------------------------------------------

    def _load_assets(self) -> None:
        app = App.get_running_app()
        if not app.core_session.is_unlocked:
            return
        try:
            assets = app.core_session.read_model(
                "assets.list",
                {"category": self._category_filter},
            )
            lst = self.ids.asset_list
            lst.clear_widgets()
            if not assets:
                msg = "No assets." if self._category_filter is None else "No assets in this category."
                lst.add_widget(MDLabel(
                    text=msg,
                    theme_text_color="Secondary",
                    halign="center",
                    size_hint_y=None,
                    height=dp(48),
                ))
                return
            for asset in assets:
                lst.add_widget(_AssetRow(asset=asset, screen=self))
        except Exception as exc:
            _log.error("Failed to load assets: %s", exc)

    # ------------------------------------------------------------------
    # Create dialog
    # ------------------------------------------------------------------

    def _open_create_dialog(self) -> None:
        category_ref = [_ALL_CATEGORIES[2]]  # default: cache

        label_field = MDTextField(MDTextFieldHintText(text="Label *"), mode="outlined")
        desc_field = MDTextField(MDTextFieldHintText(text="Description (optional)"), mode="outlined")
        lat_field = MDTextField(MDTextFieldHintText(text="Latitude (optional)"), mode="outlined")
        lon_field = MDTextField(MDTextFieldHintText(text="Longitude (optional)"), mode="outlined")
        status_label = MDLabel(text="", theme_text_color="Error",
                               size_hint_y=None, height=dp(20))

        # Category picker
        cat_btn_text = MDButtonText(
            text=_CATEGORY_LABEL.get(category_ref[0], category_ref[0])
        )
        cat_btn = MDButton(cat_btn_text, style="outlined", size_hint_x=None, width=dp(140))
        cat_menu_items = [
            {
                "text": _CATEGORY_LABEL.get(c, c.capitalize()),
                "on_release": lambda c=c, btn_text=cat_btn_text, ref=category_ref: (
                    ref.__setitem__(0, c)
                    or setattr(btn_text, "text", _CATEGORY_LABEL.get(c, c.capitalize()))
                    or cat_menu[0].dismiss()
                ),
            }
            for c in _ALL_CATEGORIES
        ]
        cat_menu = [None]  # mutable ref

        def open_cat_menu(_btn):
            cat_menu[0] = MDDropdownMenu(
                caller=cat_btn, items=cat_menu_items, position="bottom", width_mult=3
            )
            cat_menu[0].open()

        cat_btn.bind(on_release=open_cat_menu)

        modal = ModalView(size_hint=(0.65, None), height=dp(520), auto_dismiss=False)
        content = MDBoxLayout(
            orientation="vertical",
            padding=dp(24),
            spacing=dp(12),
        )

        content.add_widget(MDLabel(
            text="New Asset",
            font_style="Headline",
            size_hint_y=None,
            height=dp(40),
        ))

        cat_row = MDBoxLayout(orientation="horizontal", size_hint_y=None,
                              height=dp(48), spacing=dp(12))
        cat_row.add_widget(MDLabel(text="Category:", size_hint_x=None, width=dp(80),
                                   theme_text_color="Secondary", valign="center"))
        cat_row.add_widget(cat_btn)
        content.add_widget(cat_row)

        content.add_widget(label_field)
        content.add_widget(desc_field)
        content.add_widget(lat_field)
        content.add_widget(lon_field)

        # ── map picker button ──────────────────────────────────────────
        def _open_map_picker_create(_btn=None):
            def _on_picked(lat: float, lon: float) -> None:
                lat_field.text = f"{lat:.6f}"
                lon_field.text = f"{lon:.6f}"

            PointPickerModal(
                on_confirm=_on_picked,
                label="Asset location",
                initial_lat=_parse_float(lat_field.text),
                initial_lon=_parse_float(lon_field.text),
            ).open()

        pick_btn = MDButton(
            MDButtonText(text="PICK ON MAP"),
            style="outlined",
            size_hint_x=None,
            width=dp(160),
        )
        pick_btn.bind(on_release=_open_map_picker_create)
        content.add_widget(pick_btn)
        # ──────────────────────────────────────────────────────────────

        content.add_widget(status_label)

        btn_row = MDBoxLayout(orientation="horizontal", size_hint_y=None,
                              height=dp(48), spacing=dp(8))
        cancel_btn = MDButton(MDButtonText(text="CANCEL"), style="text")
        cancel_btn.bind(on_release=lambda _: modal.dismiss())
        create_btn = MDButton(MDButtonText(text="CREATE"), style="filled")
        create_btn.bind(on_release=lambda _: self._do_create(
            modal, status_label, category_ref[0],
            label_field.text, desc_field.text,
            lat_field.text, lon_field.text,
        ))
        btn_row.add_widget(cancel_btn)
        btn_row.add_widget(create_btn)
        content.add_widget(btn_row)

        modal.add_widget(content)
        modal.open()

    def _do_create(
        self, modal: ModalView, status_label: MDLabel,
        category: str, label: str, description: str,
        lat_str: str, lon_str: str,
    ) -> None:
        if not label.strip():
            status_label.text = "Label is required."
            return

        lat: typing.Optional[float] = None
        lon: typing.Optional[float] = None
        if lat_str.strip():
            lat = _parse_float(lat_str)
            if lat is None:
                status_label.text = "Latitude must be a number."
                return
        if lon_str.strip():
            lon = _parse_float(lon_str)
            if lon is None:
                status_label.text = "Longitude must be a number."
                return
        if (lat is None) != (lon is None):
            status_label.text = "Both latitude and longitude are required together."
            return

        app = App.get_running_app()
        if not app.core_session.is_unlocked:
            status_label.text = "No database connection."
            return

        try:
            app.core_session.command(
                "assets.create",
                category=category,
                label=label,
                description=description,
                lat=lat,
                lon=lon,
            )
            modal.dismiss()
            self._load_assets()
            self._refresh_map()
        except Exception as exc:
            _log.error("Failed to create asset: %s", exc)
            status_label.text = f"Error: {exc}"

    # ------------------------------------------------------------------
    # Edit dialog
    # ------------------------------------------------------------------

    def _open_edit_dialog(self, asset) -> None:
        label_field = MDTextField(
            MDTextFieldHintText(text="Label *"),
            text=asset.label, mode="outlined",
        )
        desc_field = MDTextField(
            MDTextFieldHintText(text="Description (optional)"),
            text=asset.description, mode="outlined",
        )
        lat_field = MDTextField(
            MDTextFieldHintText(text="Latitude (optional)"),
            text="" if asset.lat is None else str(asset.lat),
            mode="outlined",
        )
        lon_field = MDTextField(
            MDTextFieldHintText(text="Longitude (optional)"),
            text="" if asset.lon is None else str(asset.lon),
            mode="outlined",
        )
        status_label = MDLabel(text="", theme_text_color="Error",
                               size_hint_y=None, height=dp(20))

        modal = ModalView(size_hint=(0.65, None), height=dp(500), auto_dismiss=False)
        content = MDBoxLayout(orientation="vertical", padding=dp(24), spacing=dp(12))

        content.add_widget(MDLabel(
            text=f"Edit — {asset.label}",
            font_style="Headline",
            size_hint_y=None,
            height=dp(40),
        ))
        content.add_widget(label_field)
        content.add_widget(desc_field)
        content.add_widget(lat_field)
        content.add_widget(lon_field)

        # ── map picker button ──────────────────────────────────────────
        def _open_map_picker_edit(_btn=None):
            def _on_picked(lat: float, lon: float) -> None:
                lat_field.text = f"{lat:.6f}"
                lon_field.text = f"{lon:.6f}"

            PointPickerModal(
                on_confirm=_on_picked,
                label="Asset location",
                initial_lat=_parse_float(lat_field.text),
                initial_lon=_parse_float(lon_field.text),
            ).open()

        pick_btn = MDButton(
            MDButtonText(text="PICK ON MAP"),
            style="outlined",
            size_hint_x=None,
            width=dp(160),
        )
        pick_btn.bind(on_release=_open_map_picker_edit)
        content.add_widget(pick_btn)
        # ──────────────────────────────────────────────────────────────

        content.add_widget(status_label)

        app = App.get_running_app()
        is_server = app.mode == "server"
        local_operator_id = app.resolve_local_operator_id(
            allow_server_sentinel=is_server
        )
        is_own_asset = (
            local_operator_id is not None and asset.created_by == local_operator_id
        )

        btn_row = MDBoxLayout(orientation="horizontal", size_hint_y=None,
                              height=dp(48), spacing=dp(8))

        if is_server:
            delete_btn = MDButton(MDButtonText(text="DELETE"), style="text",
                                  size_hint_x=None, width=dp(80))
            delete_btn.bind(on_release=lambda _: self._confirm_delete_asset(modal, asset.id))
            btn_row.add_widget(delete_btn)
        elif not asset.deletion_requested:
            req_del_btn = MDButton(MDButtonText(text="REQUEST DEL"), style="text",
                                   size_hint_x=None, width=dp(120))
            req_del_btn.bind(on_release=lambda _: self._do_request_deletion(modal, asset.id))
            btn_row.add_widget(req_del_btn)

        cancel_btn = MDButton(MDButtonText(text="CANCEL"), style="text")
        cancel_btn.bind(on_release=lambda _: modal.dismiss())
        btn_row.add_widget(cancel_btn)

        if is_server or not is_own_asset:
            verify_label = "UNVERIFY" if asset.verified else "VERIFY"
            verify_btn = MDButton(MDButtonText(text=verify_label), style="text")
            verify_btn.bind(on_release=lambda _: self._do_verify(
                modal, asset.id, not asset.verified
            ))
            btn_row.add_widget(verify_btn)

        save_btn = MDButton(MDButtonText(text="SAVE"), style="filled")
        save_btn.bind(on_release=lambda _: self._do_edit(
            modal, status_label, asset.id,
            label_field.text, desc_field.text,
            lat_field.text, lon_field.text,
        ))
        btn_row.add_widget(save_btn)
        content.add_widget(btn_row)

        modal.add_widget(content)
        modal.open()

    def _do_edit(
        self, modal: ModalView, status_label: MDLabel,
        asset_id: int, label: str, description: str,
        lat_str: str, lon_str: str,
    ) -> None:
        if not label.strip():
            status_label.text = "Label is required."
            return

        lat: typing.Optional[float] = None
        lon: typing.Optional[float] = None
        if lat_str.strip():
            lat = _parse_float(lat_str)
            if lat is None:
                status_label.text = "Latitude must be a number."
                return
        if lon_str.strip():
            lon = _parse_float(lon_str)
            if lon is None:
                status_label.text = "Longitude must be a number."
                return
        if (lat is None) != (lon is None):
            status_label.text = "Both latitude and longitude are required together."
            return

        app = App.get_running_app()
        if not app.core_session.is_unlocked:
            return
        try:
            app.core_session.command(
                "assets.update",
                asset_id=asset_id,
                label=label,
                description=description,
                lat=lat,
                lon=lon,
            )
            modal.dismiss()
            self._load_assets()
            self._refresh_map()
        except Exception as exc:
            _log.error("Failed to update asset: %s", exc)
            status_label.text = f"Error: {exc}"

    def _do_verify(self, modal: ModalView, asset_id: int, verified: bool) -> None:
        app = App.get_running_app()
        if not app.core_session.is_unlocked:
            return
        is_server = app.mode == "server"
        try:
            if verified:
                confirmer = app.require_local_operator_id(
                    allow_server_sentinel=is_server
                )
            else:
                confirmer = None
            app.core_session.command(
                "assets.verify",
                asset_id=asset_id,
                verified=verified,
                confirmer_id=confirmer,
            )
            modal.dismiss()
            self._load_assets()
            self._refresh_map()
        except Exception as exc:
            _log.error("Failed to update verified status: %s", exc)

    # ------------------------------------------------------------------
    # Asset deletion
    # ------------------------------------------------------------------

    def _do_request_deletion(self, edit_modal: ModalView, asset_id: int) -> None:
        """Client-mode: flag asset for deletion; server operator reviews and hard-deletes."""
        app = App.get_running_app()
        if not app.core_session.is_unlocked:
            return
        try:
            app.core_session.command("assets.request_delete", asset_id=asset_id)
            edit_modal.dismiss()
            self._load_assets()
            self._refresh_map()
        except Exception as exc:
            _log.error("Failed to request asset deletion: %s", exc)

    def _confirm_delete_asset(self, edit_modal: ModalView, asset_id: int) -> None:
        confirm = ModalView(size_hint=(0.5, None), height=dp(160), auto_dismiss=False)
        content = MDBoxLayout(orientation="vertical", padding=dp(20), spacing=dp(12))
        content.add_widget(MDLabel(
            text="Delete this asset?\nThis cannot be undone.",
            halign="center",
            size_hint_y=None,
            height=dp(56),
        ))
        btn_row = MDBoxLayout(orientation="horizontal", size_hint_y=None,
                              height=dp(48), spacing=dp(8))
        cancel_btn = MDButton(MDButtonText(text="CANCEL"), style="text")
        cancel_btn.bind(on_release=lambda _: confirm.dismiss())
        delete_btn = MDButton(MDButtonText(text="DELETE"), style="filled")
        delete_btn.bind(
            on_release=lambda _: self._do_delete_asset(confirm, edit_modal, asset_id)
        )
        btn_row.add_widget(cancel_btn)
        btn_row.add_widget(delete_btn)
        content.add_widget(btn_row)
        confirm.add_widget(content)
        confirm.open()

    def _do_delete_asset(
        self, confirm_modal: ModalView, edit_modal: ModalView, asset_id: int
    ) -> None:
        app = App.get_running_app()
        if not app.core_session.is_unlocked:
            return
        try:
            app.core_session.command("assets.hard_delete", asset_id=asset_id)
            confirm_modal.dismiss()
            edit_modal.dismiss()
            self._load_assets()
            self._refresh_map()
        except Exception as exc:
            _log.error("Failed to delete asset: %s", exc)

    # ------------------------------------------------------------------
    # Map refresh helper
    # ------------------------------------------------------------------

    def _refresh_map(self) -> None:
        """Push updated asset list to the map widget if it's on screen."""
        try:
            app = App.get_running_app()
            if not app.core_session.is_unlocked:
                return
            main = app.root.get_screen("main")
            if not hasattr(main, "map_widget"):
                return
            main.map_widget.refresh_asset_markers(
                app.core_session.read_model("assets.list")
            )
        except Exception:
            pass  # non-critical


# ---------------------------------------------------------------------------
# Asset list row widget
# ---------------------------------------------------------------------------

class _AssetRow(MDBoxLayout):
    """One row in the asset list: category badge | label + coords + status | edit btn."""

    def __init__(self, asset, screen: AssetScreen, **kwargs):
        super().__init__(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(64),
            spacing=dp(8),
            padding=(dp(4), dp(4)),
            **kwargs,
        )
        color = _CATEGORY_COLOR.get(asset.category, _CATEGORY_COLOR["custom"])
        cat_label = _CATEGORY_LABEL.get(asset.category, asset.category.capitalize())

        # ── Category badge ───────────────────────────────────────────────
        badge = MDBoxLayout(
            size_hint_x=None,
            width=dp(96),
            md_bg_color=(*color[:3], 0.2),
            padding=(dp(4), dp(4)),
        )
        badge.add_widget(MDLabel(
            text=cat_label,
            halign="center",
            theme_text_color="Custom",
            text_color=color,
            bold=True,
        ))
        self.add_widget(badge)

        # ── Info column ──────────────────────────────────────────────────
        info = MDBoxLayout(orientation="vertical", spacing=dp(2))

        info.add_widget(MDLabel(
            text=asset.label,
            bold=True,
            size_hint_y=None,
            height=dp(24),
        ))

        if asset.lat is not None and asset.lon is not None:
            coord_text = (
                f"{abs(asset.lat):.4f}° {'N' if asset.lat >= 0 else 'S'}, "
                f"{abs(asset.lon):.4f}° {'E' if asset.lon >= 0 else 'W'}"
            )
        else:
            coord_text = "No coordinates"

        if asset.deletion_requested:
            status_text = "⚠ DELETION REQUESTED"
        elif asset.verified:
            status_text = "✓ VERIFIED"
        else:
            status_text = "⚠ UNVERIFIED"
        detail_line = f"{coord_text}   {status_text}"
        info.add_widget(MDLabel(
            text=detail_line,
            theme_text_color="Secondary",
            size_hint_y=None,
            height=dp(20),
        ))
        self.add_widget(info)

        # ── Edit button ──────────────────────────────────────────────────
        edit_btn = MDButton(MDButtonText(text="EDIT"), style="text",
                            size_hint_x=None, width=dp(60))
        edit_btn.bind(on_release=lambda _: screen._open_edit_dialog(asset))
        self.add_widget(edit_btn)
