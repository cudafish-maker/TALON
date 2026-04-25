# ===========================================================================
# HARD REQUIREMENT — READ BEFORE MODIFYING THIS FILE
#
# Audio alerts for FLASH and FLASH_OVERRIDE SITREPs MUST be opt-in only.
# NEVER call any audio playback automatically, regardless of severity.
# The operator enables audio alerts explicitly in Settings.
# Violating this rule is an operator-safety issue, not a style preference.
# ===========================================================================
"""
SITREP screen — situation report feed and composition.

Display rules:
  - All SITREPs are append-only; operators cannot edit or delete.
  - Server operator can delete via the server-gated delete action.
  - Notification overlays scale with severity (see sitrep_overlay widget).
  - FLASH / FLASH_OVERRIDE: full-screen overlay; audio OPT-IN ONLY.

Severity levels (ascending): ROUTINE → PRIORITY → IMMEDIATE → FLASH → FLASH_OVERRIDE
"""
import datetime
import typing

from kivy.app import App
from kivy.clock import Clock
from kivy.graphics import Color, Line, Rectangle
from kivy.metrics import dp
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.modalview import ModalView
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget
from kivymd.uix.menu import MDDropdownMenu
from kivymd.uix.screen import MDScreen

from talon.constants import SITREP_LEVELS
from talon.ui.font_scale import get_font_scale
from talon.ui.theme import (
    CHAT_AMBER, CHAT_AMBER2, CHAT_BG0, CHAT_BG1, CHAT_BG2, CHAT_BG3, CHAT_BG4,
    CHAT_BORDER, CHAT_G1, CHAT_G2, CHAT_G3, CHAT_G4, CHAT_G5, CHAT_G6,
    CHAT_RED, CHAT_RED2, SITREP_COLORS,
)
from talon.utils.formatting import format_ts as _format_ts
from talon.utils.logging import get_logger

_log = get_logger("ui.sitrep")


def _fs(base: float) -> float:
    return dp(base * get_font_scale())


def _rgba_bg(widget, color):
    with widget.canvas.before:
        Color(*color)
        rect = Rectangle(pos=widget.pos, size=widget.size)
    widget.bind(
        pos=lambda w, _: setattr(rect, 'pos', w.pos),
        size=lambda w, _: setattr(rect, 'size', w.size),
    )
    return rect


def _hline(widget, color=CHAT_BORDER, edge='bottom', thickness=1):
    with widget.canvas.after:
        Color(*color)
        line = Line(points=[], width=thickness)

    def _upd(w, _):
        y = w.y if edge == 'bottom' else (w.top - thickness)
        line.points = [w.x, y, w.right, y]

    widget.bind(pos=_upd, size=_upd)


def _vline(widget, color=CHAT_BORDER, edge='right', thickness=1):
    with widget.canvas.after:
        Color(*color)
        line = Line(points=[], width=thickness)

    def _upd(w, _):
        x = w.right if edge == 'right' else w.x
        line.points = [x, w.y, x, w.top]

    widget.bind(pos=_upd, size=_upd)


def _clip_label(label: Label) -> Label:
    label.shorten = True
    label.shorten_from = 'right'
    label.max_lines = 1

    def _update_text_box(w, _=None):
        w.text_size = (max(0, w.width), max(0, w.height))

    label.bind(size=_update_text_box)
    _update_text_box(label)
    return label


def _lbl(text="", color=CHAT_G4, fsize=11, bold=False, halign='left', **kw):
    label = Label(
        text=text,
        color=color,
        font_size=_fs(fsize),
        bold=bold,
        halign=halign,
        valign='middle',
        **kw,
    )
    label.bind(size=label.setter('text_size'))
    return label


def _btn(text, bg=CHAT_BG3, fg=CHAT_G4, size=10, h=28, w=None, **kw):
    button = Button(
        text=text,
        color=fg,
        font_size=_fs(size),
        background_normal='',
        background_color=bg,
        size_hint_y=None,
        height=dp(h),
        **kw,
    )
    if w is not None:
        button.size_hint_x = None
        button.width = dp(w)
    button.shorten = True
    button.shorten_from = 'right'
    button.max_lines = 1

    def _update_text_box(w, _=None):
        w.text_size = (max(0, w.width), max(0, w.height))

    button.bind(size=_update_text_box)
    _update_text_box(button)
    return button


def _body_text(body) -> str:
    return body.decode("utf-8", errors="replace") if isinstance(body, bytes) else str(body)


def _level_color(level: str) -> tuple:
    return SITREP_COLORS.get(level, SITREP_COLORS["ROUTINE"])


class SitrepScreen(MDScreen):
    """SITREP feed and composition screen."""

    def on_kv_post(self, base_widget) -> None:
        self._compose_level = "ROUTINE"
        self._linked_asset_id: typing.Optional[int] = None
        self._linked_asset_label: str = ""
        self._linked_mission_id: typing.Optional[int] = None
        self._linked_mission_title: str = ""
        self._audio_enabled: bool = False  # loaded from DB in on_pre_enter
        self._entries: list = []
        self._build_layout()
        self._build_level_menu()
        self._update_level_display()
        self._update_link_status()

    def _build_layout(self) -> None:
        self.clear_widgets()
        root = BoxLayout(orientation='vertical')
        _rgba_bg(root, CHAT_BG0)

        root.add_widget(self._make_topbar())

        body = BoxLayout(orientation='horizontal')
        feed_panel = self._make_feed_panel()
        compose_panel = self._make_compose_panel()
        body.add_widget(feed_panel)
        body.add_widget(compose_panel)

        root.add_widget(body)
        self.add_widget(root)

    def on_ui_theme_changed(self) -> None:
        self._build_layout()
        self._build_level_menu()
        self._update_level_display()
        self._update_link_status()
        self._update_audio_display()
        if self.manager and self.manager.current == self.name:
            self.on_pre_enter()

    # ------------------------------------------------------------------
    # Topbar
    # ------------------------------------------------------------------

    def _make_topbar(self) -> BoxLayout:
        bar = BoxLayout(
            orientation='horizontal',
            size_hint_y=None,
            height=dp(42),
            padding=(dp(6), 0, dp(8), 0),
            spacing=0,
        )
        _rgba_bg(bar, CHAT_BG1)
        _hline(bar, CHAT_BORDER, 'bottom')

        back = _btn('◀ TALON', CHAT_BG1, CHAT_G5, 11, h=42, w=80)
        back.bind(on_release=lambda _: self.on_back_pressed())
        bar.add_widget(back)

        sep = Widget(size_hint_x=None, width=dp(1))
        with sep.canvas:
            Color(*CHAT_BORDER)
            sep_rect = Rectangle(pos=sep.pos, size=sep.size)
        sep.bind(
            pos=lambda w, _: setattr(sep_rect, 'pos', w.pos),
            size=lambda w, _: setattr(sep_rect, 'size', w.size),
        )
        bar.add_widget(sep)
        bar.add_widget(Widget(size_hint_x=None, width=dp(10)))

        title = _lbl('SITREP FEED', CHAT_G6, 14, bold=True,
                     size_hint=(None, 1), width=dp(136))
        bar.add_widget(title)

        self._live_lbl = _lbl('LIVE', CHAT_G5, 9, bold=True,
                              size_hint=(None, 1), width=dp(44), halign='center')
        bar.add_widget(self._live_lbl)

        bar.add_widget(Widget())

        self._latest_flash_lbl = _lbl('', CHAT_RED2, 9, bold=True,
                                      size_hint=(None, 1), width=dp(150),
                                      halign='right')
        bar.add_widget(self._latest_flash_lbl)

        refresh = _btn('REFRESH', CHAT_BG3, CHAT_G4, 10, h=28, w=70)
        refresh.bind(on_release=lambda _: self._load_feed())
        bar.add_widget(Widget(size_hint_x=None, width=dp(6)))
        bar.add_widget(refresh)

        self._audio_toggle_btn = _btn('AUDIO OFF', CHAT_BG3, CHAT_G3, 10, h=28, w=86)
        self._audio_toggle_btn.bind(on_release=lambda _: self.on_audio_toggle_pressed())
        bar.add_widget(Widget(size_hint_x=None, width=dp(6)))
        bar.add_widget(self._audio_toggle_btn)

        return bar

    # ------------------------------------------------------------------
    # Feed panel
    # ------------------------------------------------------------------

    def _make_feed_panel(self) -> BoxLayout:
        panel = BoxLayout(orientation='vertical')
        _rgba_bg(panel, CHAT_BG0)

        filter_bar = BoxLayout(
            orientation='horizontal',
            size_hint_y=None,
            height=dp(36),
            padding=(dp(12), 0),
            spacing=dp(8),
        )
        _rgba_bg(filter_bar, CHAT_BG1)
        _hline(filter_bar, CHAT_BORDER, 'bottom')

        filter_bar.add_widget(_lbl('SITUATION REPORTS', CHAT_G4, 10, bold=True,
                                   size_hint=(None, 1), width=dp(142)))
        self._count_lbl = _lbl('', CHAT_G2, 9, size_hint=(None, 1), width=dp(100))
        filter_bar.add_widget(self._count_lbl)

        filter_bar.add_widget(Widget())

        self._severity_summary_lbl = _lbl('', CHAT_G3, 9, halign='right',
                                          size_hint=(None, 1), width=dp(260))
        filter_bar.add_widget(self._severity_summary_lbl)
        panel.add_widget(filter_bar)

        scroll = ScrollView(
            size_hint=(1, 1),
            bar_width=dp(3),
            bar_color=CHAT_G2,
            bar_inactive_color=CHAT_G1,
            do_scroll_x=False,
        )
        self._sitrep_list = GridLayout(cols=1, size_hint_y=None, spacing=0)
        self._sitrep_list.bind(minimum_height=self._sitrep_list.setter('height'))
        scroll.add_widget(self._sitrep_list)
        panel.add_widget(scroll)
        return panel

    # ------------------------------------------------------------------
    # Compose panel
    # ------------------------------------------------------------------

    def _make_compose_panel(self) -> BoxLayout:
        panel = BoxLayout(
            orientation='vertical',
            size_hint_x=None,
            width=dp(320),
        )
        _rgba_bg(panel, CHAT_BG1)
        _vline(panel, CHAT_BORDER, 'left')

        header = BoxLayout(
            orientation='horizontal',
            size_hint_y=None,
            height=dp(38),
            padding=(dp(12), 0),
        )
        _rgba_bg(header, CHAT_BG1)
        _hline(header, CHAT_BORDER, 'bottom')
        header.add_widget(_lbl('NEW SITREP', CHAT_G6, 12, bold=True))
        self._compose_state_lbl = _lbl('', CHAT_G3, 9, halign='right',
                                       size_hint=(None, 1), width=dp(86))
        header.add_widget(self._compose_state_lbl)
        panel.add_widget(header)

        body = BoxLayout(
            orientation='vertical',
            padding=(dp(12), dp(10)),
            spacing=dp(8),
        )

        body.add_widget(_lbl('SEVERITY', CHAT_G3, 9, bold=True,
                             size_hint_y=None, height=dp(16)))
        self._level_button = _btn('', CHAT_BG3, CHAT_G6, 11, h=34)
        self._level_button.bind(on_release=lambda _: self.on_level_button_pressed())
        body.add_widget(self._level_button)

        body.add_widget(_lbl('LINKS', CHAT_G3, 9, bold=True,
                             size_hint_y=None, height=dp(16)))
        self._asset_link_btn = _btn('ASSET: NONE', CHAT_BG3, CHAT_G4, 10, h=32)
        self._asset_link_btn.bind(on_release=lambda _: self.on_asset_link_pressed())
        body.add_widget(self._asset_link_btn)

        self._mission_link_btn = _btn('MISSION: NONE', CHAT_BG3, CHAT_G4, 10, h=32)
        self._mission_link_btn.bind(on_release=lambda _: self.on_mission_link_pressed())
        body.add_widget(self._mission_link_btn)

        body.add_widget(_lbl('BODY', CHAT_G3, 9, bold=True,
                             size_hint_y=None, height=dp(16)))
        self._body_field = TextInput(
            hint_text="COMPOSE SITUATION REPORT...",
            hint_text_color=CHAT_G2,
            foreground_color=CHAT_G5,
            background_color=CHAT_BG3,
            cursor_color=CHAT_G5,
            font_size=_fs(11),
            multiline=True,
            padding=(dp(8), dp(8)),
        )
        body.add_widget(self._body_field)

        self._status_label = _lbl('', CHAT_G2, 9, size_hint_y=None, height=dp(42))
        body.add_widget(self._status_label)

        send_row = BoxLayout(size_hint_y=None, height=dp(38), spacing=dp(8))
        clear_btn = _btn('CLEAR', CHAT_BG3, CHAT_G3, 10, h=38, w=76)
        clear_btn.bind(on_release=lambda _: self._clear_composer())
        self._send_button = _btn('SEND ▶', CHAT_G2, CHAT_G6, 12, h=38)
        self._send_button.bold = True
        self._send_button.bind(on_release=lambda _: self.on_submit_pressed(self._body_field.text))
        send_row.add_widget(clear_btn)
        send_row.add_widget(self._send_button)
        body.add_widget(send_row)

        panel.add_widget(body)
        return panel

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def on_pre_enter(self) -> None:
        App.get_running_app().clear_badge("sitrep")
        self._load_feed()
        self._sync_audio_toggle()

    def on_back_pressed(self) -> None:
        self.manager.current = "main"

    # ------------------------------------------------------------------
    # Audio alert opt-in toggle
    # ------------------------------------------------------------------

    def on_audio_toggle_pressed(self) -> None:
        """Toggle the audio alert opt-in and persist the choice."""
        app = App.get_running_app()
        if app.conn is None:
            return
        from talon.audio_alerts import set_audio_enabled
        self._audio_enabled = not self._audio_enabled
        set_audio_enabled(app.conn, self._audio_enabled)
        self._update_audio_toggle()

    def _sync_audio_toggle(self) -> None:
        """Read audio setting from DB and sync the toggle button state."""
        app = App.get_running_app()
        if app.conn is None:
            return
        from talon.audio_alerts import is_audio_enabled
        self._audio_enabled = is_audio_enabled(app.conn)
        self._update_audio_toggle()

    def _update_audio_toggle(self) -> None:
        if self._audio_enabled:
            self._audio_toggle_btn.text = 'AUDIO ON'
            self._audio_toggle_btn.color = CHAT_AMBER2
            self._audio_toggle_btn.background_color = (*CHAT_AMBER[:3], 0.28)
        else:
            self._audio_toggle_btn.text = 'AUDIO OFF'
            self._audio_toggle_btn.color = CHAT_G3
            self._audio_toggle_btn.background_color = CHAT_BG3

    # ------------------------------------------------------------------
    # Level picker
    # ------------------------------------------------------------------

    def _build_level_menu(self) -> None:
        self._level_menu = MDDropdownMenu(
            caller=self._level_button,
            items=[
                {
                    "text": level,
                    "on_release": lambda x=level: self._select_level(x),
                }
                for level in SITREP_LEVELS
            ],
            position="bottom",
            width_mult=4,
        )

    def on_level_button_pressed(self) -> None:
        self._level_menu.open()

    def _select_level(self, level: str) -> None:
        self._compose_level = level
        self._update_level_display()
        self._level_menu.dismiss()

    def _update_level_display(self) -> None:
        color = _level_color(self._compose_level)
        self._level_button.text = f'▾ {self._compose_level}'
        self._level_button.color = color
        if self._compose_level in ('FLASH', 'FLASH_OVERRIDE'):
            self._level_button.background_color = (*CHAT_RED[:3], 0.25)
        elif self._compose_level == 'IMMEDIATE':
            self._level_button.background_color = (*CHAT_AMBER[:3], 0.22)
        else:
            self._level_button.background_color = CHAT_BG3

    # ------------------------------------------------------------------
    # Compose / submit
    # ------------------------------------------------------------------

    def on_submit_pressed(self, body: str) -> None:
        """Validate and persist a new SITREP."""
        body = body.strip()
        if not body:
            self._set_status("Body is required.", error=True)
            return
        app = App.get_running_app()
        if app.conn is None or app.db_key is None:
            self._set_status("No database connection.", error=True)
            return
        try:
            from talon.sitrep import create_sitrep
            author_id = app.require_local_operator_id(
                allow_server_sentinel=(app.mode == "server")
            )
            sitrep_id = create_sitrep(
                app.conn,
                app.db_key,
                author_id=author_id,
                level=self._compose_level,
                body=body,
                asset_id=self._linked_asset_id,
                mission_id=self._linked_mission_id,
            )
            app.net_notify_change("sitreps", sitrep_id)
            self._body_field.text = ""
            self._linked_asset_id = None
            self._linked_asset_label = ""
            self._linked_mission_id = None
            self._linked_mission_title = ""
            self._update_link_status()
            self._set_status("SITREP sent.", error=False)
            self._load_feed()
        except Exception as exc:
            _log.error("Failed to create SITREP: %s", exc)
            self._set_status(f"Error: {exc}", error=True)

    def _clear_composer(self) -> None:
        self._body_field.text = ""
        self._linked_asset_id = None
        self._linked_asset_label = ""
        self._linked_mission_id = None
        self._linked_mission_title = ""
        self._update_link_status()

    def _set_status(self, text: str, *, error: bool = False) -> None:
        self._status_label.text = text
        self._status_label.color = CHAT_RED2 if error else CHAT_G3

    # ------------------------------------------------------------------
    # Asset link picker
    # ------------------------------------------------------------------

    def on_asset_link_pressed(self) -> None:
        """Build and open an asset picker dropdown."""
        app = App.get_running_app()
        if app.conn is None:
            return
        try:
            from talon.assets import load_assets
            assets = load_assets(app.conn)
        except Exception as exc:
            _log.error("Failed to load assets for picker: %s", exc)
            return

        items = [{"text": "— No asset —",
                  "on_release": lambda: self._select_asset(None, "")}]
        for asset in assets:
            items.append({
                "text": asset.label,
                "on_release": lambda a=asset: self._select_asset(a.id, a.label),
            })
        self._asset_menu = MDDropdownMenu(
            caller=self._asset_link_btn,
            items=items,
            position="bottom",
            width_mult=4,
        )
        self._asset_menu.open()

    def _select_asset(self, asset_id: typing.Optional[int], label: str) -> None:
        self._linked_asset_id = asset_id
        self._linked_asset_label = label
        if hasattr(self, "_asset_menu"):
            self._asset_menu.dismiss()
        self._update_link_status()

    # ------------------------------------------------------------------
    # Mission link picker
    # ------------------------------------------------------------------

    def on_mission_link_pressed(self) -> None:
        """Build and open a mission picker dropdown."""
        app = App.get_running_app()
        if app.conn is None:
            return
        try:
            from talon.missions import load_missions
            missions = load_missions(app.conn, status_filter=None)
            missions = [m for m in missions if m.status in ("pending_approval", "active")]
        except Exception as exc:
            _log.error("Failed to load missions for picker: %s", exc)
            return

        items = [{"text": "— No mission —",
                  "on_release": lambda: self._select_mission(None, "")}]
        for mission in missions:
            label = f"{mission.title}  [{mission.status.upper()}]"
            items.append({
                "text": label,
                "on_release": lambda m=mission: self._select_mission(m.id, m.title),
            })
        self._mission_menu = MDDropdownMenu(
            caller=self._mission_link_btn,
            items=items,
            position="bottom",
            width_mult=5,
        )
        self._mission_menu.open()

    def _select_mission(self, mission_id: typing.Optional[int], title: str) -> None:
        self._linked_mission_id = mission_id
        self._linked_mission_title = title
        if hasattr(self, "_mission_menu"):
            self._mission_menu.dismiss()
        self._update_link_status()

    # ------------------------------------------------------------------
    # Compose status line
    # ------------------------------------------------------------------

    def _update_link_status(self) -> None:
        """Rebuild the compose link controls from current asset + mission state."""
        if self._linked_asset_id is not None:
            label = self._linked_asset_label or f"#{self._linked_asset_id}"
            self._asset_link_btn.text = f"ASSET: {label}"
            self._asset_link_btn.color = CHAT_G6
            self._asset_link_btn.background_color = CHAT_BG4
        else:
            self._asset_link_btn.text = "ASSET: NONE"
            self._asset_link_btn.color = CHAT_G4
            self._asset_link_btn.background_color = CHAT_BG3

        if self._linked_mission_id is not None:
            title = self._linked_mission_title or f"#{self._linked_mission_id}"
            self._mission_link_btn.text = f"MISSION: {title}"
            self._mission_link_btn.color = CHAT_G6
            self._mission_link_btn.background_color = CHAT_BG4
        else:
            self._mission_link_btn.text = "MISSION: NONE"
            self._mission_link_btn.color = CHAT_G4
            self._mission_link_btn.background_color = CHAT_BG3

        parts: list[str] = []
        if self._linked_asset_id is not None:
            parts.append(f"Asset: {self._linked_asset_label}")
        if self._linked_mission_id is not None:
            parts.append(f"Mission: {self._linked_mission_title}")
        if parts:
            self._set_status("  |  ".join(parts), error=False)
        elif not self._status_label.text or self._status_label.text.startswith(("Asset:", "Mission:")):
            self._set_status("No linked asset or mission.", error=False)

    # ------------------------------------------------------------------
    # Sync engine callback
    # ------------------------------------------------------------------

    def on_new_sitrep(self, sitrep) -> None:
        """Called by the sync engine when a SITREP arrives from a client.

        May be called from a background thread — dispatches to the UI thread
        before touching any widgets.
        NOTE: do NOT play audio here — audio is gated by the user opt-in setting.
        """
        Clock.schedule_once(lambda dt: self._on_new_sitrep_ui(sitrep))

    def _on_new_sitrep_ui(self, sitrep) -> None:
        self._load_feed()
        from talon.ui.widgets.sitrep_overlay import SitrepOverlay
        SitrepOverlay().show(sitrep)
        # Audio is gated by opt-in and limited to FLASH / FLASH_OVERRIDE only.
        if (
            getattr(sitrep, "level", "") in ("FLASH", "FLASH_OVERRIDE")
            and self._audio_enabled
        ):
            from talon.audio_alerts import play_alert
            play_alert()

    # ------------------------------------------------------------------
    # SITREP deletion (server operator only)
    # ------------------------------------------------------------------

    def _confirm_delete_sitrep(self, sitrep_id: int) -> None:
        modal = ModalView(
            size_hint=(None, None),
            size=(dp(360), dp(170)),
            auto_dismiss=False,
            background='',
            background_color=(0, 0, 0, 0.7),
        )
        wrap = BoxLayout(orientation='vertical', size_hint=(None, None),
                         size=(dp(360), dp(170)))
        _rgba_bg(wrap, CHAT_BG2)

        hdr = BoxLayout(size_hint_y=None, height=dp(36), padding=(dp(12), 0))
        _rgba_bg(hdr, CHAT_BG1)
        _hline(hdr, CHAT_BORDER, 'bottom')
        hdr.add_widget(_lbl('DELETE SITREP', CHAT_RED2, 12, bold=True))
        wrap.add_widget(hdr)

        wrap.add_widget(_lbl(
            "Permanently delete this SITREP?\nThis cannot be undone.",
            CHAT_G4, 10, halign='center',
            size_hint_y=None, height=dp(72),
        ))

        btn_row = BoxLayout(size_hint_y=None, height=dp(48),
                            padding=(dp(12), dp(8)), spacing=dp(8))
        cancel_btn = _btn('CANCEL', CHAT_BG3, CHAT_G3, 10, h=32)
        cancel_btn.bind(on_release=lambda _: modal.dismiss())
        delete_btn = _btn('DELETE', (*CHAT_RED[:3], 1.0), CHAT_G6, 10, h=32)
        delete_btn.bind(on_release=lambda _: self._do_delete_sitrep(modal, sitrep_id))
        btn_row.add_widget(cancel_btn)
        btn_row.add_widget(delete_btn)
        wrap.add_widget(btn_row)

        modal.add_widget(wrap)
        modal.open()

    def _do_delete_sitrep(self, confirm_modal: ModalView, sitrep_id: int) -> None:
        app = App.get_running_app()
        if app.conn is None:
            return
        try:
            from talon.sitrep import delete_sitrep
            delete_sitrep(app.conn, sitrep_id)
            app.net_notify_delete("sitreps", sitrep_id)
            confirm_modal.dismiss()
            self._load_feed()
        except Exception as exc:
            _log.error("Failed to delete SITREP: %s", exc)

    # ------------------------------------------------------------------
    # Feed loader
    # ------------------------------------------------------------------

    def _load_feed(self) -> None:
        app = App.get_running_app()
        if app.conn is None or app.db_key is None:
            return
        try:
            from talon.sitrep import load_sitreps
            entries = load_sitreps(app.conn, app.db_key)
            self._entries = entries
            feed = self._sitrep_list
            feed.clear_widgets()

            self._update_feed_summary(entries)

            if not entries:
                feed.add_widget(
                    _lbl("// No SITREPs logged.", CHAT_G3, 10, halign='center',
                         size_hint_y=None, height=dp(56))
                )
                return

            screen_ref = self if app.mode == "server" else None
            for sitrep, callsign, asset_label in entries:
                feed.add_widget(_SitrepRow(
                    sitrep=sitrep,
                    callsign=callsign,
                    asset_label=asset_label,
                    screen=screen_ref,
                ))
        except Exception as exc:
            _log.error("Failed to load SITREP feed: %s", exc)
            self._set_status(f"Feed error: {exc}", error=True)

    def _update_feed_summary(self, entries: list) -> None:
        total = len(entries)
        self._count_lbl.text = f"{total} TOTAL"
        counts = {level: 0 for level in SITREP_LEVELS}
        for sitrep, _callsign, _asset_label in entries:
            counts[sitrep.level] = counts.get(sitrep.level, 0) + 1
        priority_count = counts.get('PRIORITY', 0)
        immediate_count = counts.get('IMMEDIATE', 0)
        flash_count = counts.get('FLASH', 0) + counts.get('FLASH_OVERRIDE', 0)
        self._severity_summary_lbl.text = (
            f"PRIORITY {priority_count}   IMMEDIATE {immediate_count}   FLASH {flash_count}"
        )
        self._compose_state_lbl.text = datetime.datetime.now().strftime('%H:%M')

        if entries and entries[0][0].level in ('FLASH', 'FLASH_OVERRIDE'):
            self._latest_flash_lbl.text = f"LATEST: {entries[0][0].level}"
        else:
            self._latest_flash_lbl.text = ""


# ---------------------------------------------------------------------------
# Feed row widget
# ---------------------------------------------------------------------------

class _SitrepRow(ButtonBehavior, BoxLayout):
    """One entry in the SITREP feed."""

    def __init__(
        self,
        sitrep,
        callsign: str,
        asset_label: typing.Optional[str] = None,
        screen: typing.Optional["SitrepScreen"] = None,
        **kwargs,
    ):
        super().__init__(
            orientation='horizontal',
            size_hint_y=None,
            height=dp(84),
            padding=(0, 0),
            spacing=0,
            **kwargs,
        )
        self._sitrep = sitrep
        self._screen = screen
        self._base_bg = CHAT_BG2

        color = _level_color(sitrep.level)
        is_flash = sitrep.level in ('FLASH', 'FLASH_OVERRIDE')
        is_immediate = sitrep.level == 'IMMEDIATE'
        if is_flash:
            self._base_bg = (*CHAT_RED[:3], 0.12)
        elif is_immediate:
            self._base_bg = (*CHAT_AMBER[:3], 0.10)

        with self.canvas.before:
            self._bg_color = Color(*self._base_bg)
            self._bg_rect = Rectangle(pos=self.pos, size=self.size)
            Color(*color)
            self._bar = Rectangle(pos=self.pos, size=(dp(4), self.height))
        self.bind(pos=self._update_canvas, size=self._update_canvas)
        _hline(self, CHAT_BORDER, 'bottom')

        self.add_widget(Widget(size_hint_x=None, width=dp(4)))

        content = BoxLayout(
            orientation='vertical',
            padding=(dp(10), dp(6), dp(8), dp(5)),
            spacing=dp(3),
        )

        header = BoxLayout(orientation='horizontal', size_hint_y=None,
                           height=_fs(18), spacing=dp(8))
        time_text = _format_ts(sitrep.created_at)
        header.add_widget(_clip_label(Label(
            text=time_text,
            color=CHAT_G2,
            font_size=_fs(8),
            halign='left',
            valign='middle',
            size_hint=(None, None),
            size=(dp(82), _fs(18)),
        )))

        level_lbl = Label(
            text=sitrep.level,
            color=color,
            font_size=_fs(9),
            bold=True,
            halign='left',
            valign='middle',
            size_hint=(None, None),
            size=(dp(126), _fs(18)),
        )
        header.add_widget(_clip_label(level_lbl))

        author_text = callsign
        if asset_label:
            author_text = f"{callsign} → {asset_label}"
        if getattr(sitrep, 'mission_id', None):
            author_text = f"{author_text}  |  MISSION #{sitrep.mission_id}"
        author_lbl = Label(
            text=author_text,
            color=CHAT_G5,
            font_size=_fs(10),
            bold=True,
            halign='left',
            valign='middle',
        )
        header.add_widget(_clip_label(author_lbl))
        content.add_widget(header)

        body_text = _body_text(sitrep.body)
        if len(body_text) > 220:
            body_text = body_text[:217] + '…'
        body_lbl = Label(
            text=body_text,
            color=CHAT_AMBER2 if is_flash else (CHAT_AMBER if is_immediate else CHAT_G4),
            font_size=_fs(10),
            halign='left',
            valign='top',
            size_hint_y=None,
            height=dp(48),
        )
        body_lbl.bind(size=body_lbl.setter('text_size'))
        content.add_widget(body_lbl)
        self.add_widget(content)

        if screen is not None:
            action = BoxLayout(orientation='vertical', size_hint_x=None, width=dp(54),
                               padding=(0, dp(10), dp(8), dp(10)))
            delete_btn = _btn('DEL', (*CHAT_RED[:3], 0.45), CHAT_G6, 9, h=28, w=44)
            delete_btn.bind(
                on_release=lambda _, sid=sitrep.id: screen._confirm_delete_sitrep(sid)
            )
            action.add_widget(delete_btn)
            action.add_widget(Widget())
            self.add_widget(action)

    def _update_canvas(self, *_):
        self._bg_rect.pos = self.pos
        self._bg_rect.size = self.size
        self._bar.pos = self.pos
        self._bar.size = (dp(4), self.height)

    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos):
            self._bg_color.rgba = CHAT_BG4
        return super().on_touch_down(touch)

    def on_touch_up(self, touch):
        result = super().on_touch_up(touch)
        self._bg_color.rgba = self._base_bg
        return result
