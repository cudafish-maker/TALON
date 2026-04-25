"""
TalonNavRail — persistent collapsible navigation rail.

Structure (horizontal BoxLayout):
  _content  — 48 dp vertical strip of nav icons + cog (hidden when collapsed)
  _tab      — 14 dp persistent strip with centered < / > arrow

Expanded : 48 + 14 = 62 dp total
Collapsed:  0 + 14 = 14 dp total

The tab is always visible so expand/collapse is always reachable.
"""
import typing

from kivy.app import App
from kivy.graphics import Color, Line, Rectangle
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.widget import Widget
from kivymd.uix.button import MDIconButton

from talon.ui.theme import (
    CHAT_BG1, CHAT_BG2, CHAT_BG3, CHAT_BG4,
    CHAT_BORDER, CHAT_G2, CHAT_G3, CHAT_G4, CHAT_G5, CHAT_G6,
    CHAT_RED2,
)

_CONTENT_W = 48
_TAB_W = 14

_SCREEN_TO_NAV: dict = {
    'main':           'main',
    'assets':         'assets',
    'chat':           'chat',
    'sitrep':         'sitrep',
    'mission':        'mission',
    'mission_create': 'mission',
    'documents':      'documents',
    'enroll':         'enroll',
    'clients':        'clients',
    'audit':          'audit',
    'keys':           'keys',
}

_NAV_SHARED: list = [
    ("map",                   "main",      "Map"),
    ("shield-account",        "assets",    "Assets"),
    None,
    ("chat",                  "chat",      "Chat"),
    ("alert-circle-outline",  "sitrep",    "SITREPs"),
    ("flag-outline",          "mission",   "Missions"),
    ("file-document-outline", "documents", "Documents"),
]

_NAV_SERVER: list = [
    None,
    ("account-plus-outline", "enroll",  "Enroll"),
    ("account-multiple",     "clients", "Clients"),
    ("format-list-text",     "audit",   "Audit Log"),
    ("key-variant",          "keys",    "Keys"),
]


# ---------------------------------------------------------------------------
# _NavBtn — icon button with active-state highlight and badge overlay
# ---------------------------------------------------------------------------

class _NavBtn(Widget):
    def __init__(self, icon: str, screen_name: str, active: bool = False, **kwargs):
        super().__init__(
            size_hint=(None, None),
            size=(dp(_CONTENT_W), dp(_CONTENT_W)),
            **kwargs,
        )
        self._screen_name = screen_name
        self._active = active

        with self.canvas.before:
            self._bg = Color(*(CHAT_BG4 if active else (0, 0, 0, 0)))
            self._bg_rect = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._upd, size=self._upd)

        self._icon_btn = MDIconButton(
            icon=icon,
            size_hint=(None, None),
            size=(dp(36), dp(36)),
            pos=self.pos,
            theme_icon_color="Custom",
            icon_color=CHAT_G6 if active else CHAT_G3,
            md_bg_color=(0, 0, 0, 0),
        )
        self.bind(pos=lambda w, p: setattr(self._icon_btn, 'pos', p))
        self.add_widget(self._icon_btn)

        self._badge_lbl = Label(
            text='', color=CHAT_RED2, font_size=dp(8), bold=True,
            size_hint=(None, None), size=(dp(14), dp(12)),
        )
        self.bind(pos=self._upd_badge, size=self._upd_badge)
        self.add_widget(self._badge_lbl)

    def _upd(self, *_):
        self._bg_rect.pos = self.pos
        self._bg_rect.size = self.size

    def _upd_badge(self, *_):
        self._badge_lbl.pos = (self.right - dp(14), self.top - dp(12))

    def set_active(self, active: bool):
        self._active = active
        self._icon_btn.icon_color = CHAT_G6 if active else CHAT_G3
        self._bg.rgba = CHAT_BG4 if active else (0, 0, 0, 0)

    def set_badge(self, count: int):
        self._badge_lbl.text = str(count) if count > 0 else ''

    def bind_release(self, cb):
        self._icon_btn.bind(on_release=cb)

    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos) and not self._active:
            self._bg.rgba = CHAT_BG3
            self._icon_btn.icon_color = CHAT_G5
        return super().on_touch_down(touch)

    def on_touch_up(self, touch):
        result = super().on_touch_up(touch)
        if not self._active:
            self._bg.rgba = (0, 0, 0, 0)
            self._icon_btn.icon_color = CHAT_G3
        return result


class _Sep(Widget):
    """Thin horizontal separator between nav groups."""
    def __init__(self, **kwargs):
        super().__init__(size_hint_y=None, height=dp(1), **kwargs)
        with self.canvas:
            Color(*CHAT_BORDER)
            self._r = Rectangle(pos=self.pos, size=(dp(_CONTENT_W - 12), dp(1)))
        self.bind(pos=lambda w, _: setattr(self._r, 'pos', (w.x + dp(6), w.y)))


# ---------------------------------------------------------------------------
# TalonNavRail
# ---------------------------------------------------------------------------

class TalonNavRail(BoxLayout):
    """
    Persistent collapsible icon rail.

    Horizontal layout: [_content (icons) | _tab (always-visible arrow strip)].
    The tab never disappears so expand and collapse are always reachable.
    """

    def __init__(self, mode: str, **kwargs):
        super().__init__(
            orientation='horizontal',
            size_hint_x=None,
            width=dp(_CONTENT_W + _TAB_W),
            **kwargs,
        )
        self._mode = mode
        self._expanded = True
        self._nav_btns: dict[str, _NavBtn] = {}
        self._font_popup: typing.Optional[Widget] = None
        self._active_screen_name = ''
        self._badges: dict = {}

        self._build()

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def _build(self):
        # --- Icon content column ---
        self._content = BoxLayout(
            orientation='vertical',
            size_hint_x=None,
            width=dp(_CONTENT_W),
            spacing=dp(2),
            padding=(0, dp(4)),
        )
        with self._content.canvas.before:
            Color(*CHAT_BG1)
            self._content_bg = Rectangle(pos=self._content.pos, size=self._content.size)
        self._content.bind(
            pos=lambda w, _: setattr(self._content_bg, 'pos', w.pos),
            size=lambda w, _: setattr(self._content_bg, 'size', w.size),
        )
        self.add_widget(self._content)
        self._populate_items()

        # --- Tab strip (always visible) ---
        self._tab = BoxLayout(
            orientation='vertical',
            size_hint_x=None,
            width=dp(_TAB_W),
        )
        with self._tab.canvas.before:
            Color(*CHAT_BG2)
            self._tab_bg = Rectangle(pos=self._tab.pos, size=self._tab.size)
        self._tab.bind(
            pos=lambda w, _: setattr(self._tab_bg, 'pos', w.pos),
            size=lambda w, _: setattr(self._tab_bg, 'size', w.size),
        )
        with self._tab.canvas.after:
            Color(*CHAT_BORDER)
            self._tab_border = Line(points=[], width=1)
        self._tab.bind(pos=self._upd_tab_border, size=self._upd_tab_border)

        self._tab.add_widget(Widget())  # top spacer — centers the arrow

        self._arrow_btn = Button(
            text='<',
            color=CHAT_G4, font_size=dp(10), bold=True,
            background_normal='', background_color=(0, 0, 0, 0),
            size_hint=(1, None), height=dp(32),
        )
        self._arrow_btn.bind(on_release=lambda _: self.toggle())
        self._tab.add_widget(self._arrow_btn)

        self._tab.add_widget(Widget())  # bottom spacer

        self.add_widget(self._tab)

    def _upd_tab_border(self, *_):
        # Right border on the tab
        self._tab_border.points = [
            self._tab.right, self._tab.y,
            self._tab.right, self._tab.top,
        ]

    def _populate_items(self):
        self._content.clear_widgets()
        self._nav_btns.clear()

        for item in _NAV_SHARED + (_NAV_SERVER if self._mode == 'server' else []):
            if item is None:
                self._content.add_widget(_Sep())
                continue
            icon, screen_name, _ = item
            btn = _NavBtn(icon=icon, screen_name=screen_name)
            btn.bind_release(lambda _, sn=screen_name: self._nav(sn))
            self._nav_btns[screen_name] = btn
            self._content.add_widget(btn)

        self._content.add_widget(Widget())  # pushes cog to bottom

        self._cog = _NavBtn(icon='format-size', screen_name='')
        self._cog.bind_release(lambda _: self._toggle_font_popup())
        self._content.add_widget(self._cog)

    # ------------------------------------------------------------------
    # Toggle expand/collapse
    # ------------------------------------------------------------------

    def toggle(self):
        self._expanded = not self._expanded
        self._apply_expanded_state()

    def _apply_expanded_state(self) -> None:
        if self._expanded:
            self._content.width = dp(_CONTENT_W)
            self._content.opacity = 1
            self._content.disabled = False
            self._arrow_btn.text = '<'
            self.width = dp(_CONTENT_W + _TAB_W)
        else:
            self._content.width = 0
            self._content.opacity = 0
            self._content.disabled = True
            self._arrow_btn.text = '>'
            self.width = dp(_TAB_W)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_active(self, screen_name: str):
        self._active_screen_name = screen_name
        nav_key = _SCREEN_TO_NAV.get(screen_name, '')
        for sn, btn in self._nav_btns.items():
            btn.set_active(sn == nav_key)

    def set_badges(self, badges: dict):
        self._badges = dict(badges)
        for sn, btn in self._nav_btns.items():
            btn.set_badge(badges.get(sn, 0))

    def show(self):
        self.opacity = 1
        self.width = dp(_CONTENT_W + _TAB_W) if self._expanded else dp(_TAB_W)

    def hide(self):
        self.opacity = 0
        self.width = 0

    def on_ui_theme_changed(self) -> None:
        was_visible = self.opacity > 0 and self.width > 0
        self._hide_font_popup()
        self.clear_widgets()
        self._nav_btns.clear()
        self._build()
        self._apply_expanded_state()
        self.set_active(self._active_screen_name)
        self.set_badges(self._badges)
        if not was_visible:
            self.hide()

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def _nav(self, screen_name: str):
        app = App.get_running_app()
        sm = getattr(app, '_sm', None)
        if sm and any(s.name == screen_name for s in sm.screens):
            sm.current = screen_name

    # ------------------------------------------------------------------
    # Font scale popup
    # ------------------------------------------------------------------

    def _toggle_font_popup(self):
        if self._font_popup and self._font_popup.parent:
            self._hide_font_popup()
        else:
            self._show_font_popup()

    def _show_font_popup(self):
        from kivy.core.window import Window
        from talon.ui.font_scale import get_font_scale, set_font_scale
        from talon.ui.widgets.font_scale import FontScalePopup

        def _on_apply():
            app = App.get_running_app()
            sm = getattr(app, '_sm', None)
            if sm and sm.current_screen and hasattr(sm.current_screen, 'on_pre_enter'):
                sm.current_screen.on_pre_enter()

        popup = FontScalePopup(
            get_scale=get_font_scale,
            set_scale=set_font_scale,
            meta_key='global_font_scale',
            on_apply=_on_apply,
            on_dismiss=self._hide_font_popup,
        )
        self._font_popup = popup

        popup.x = self.right + dp(4)
        ideal_y = self._cog.y
        popup.y = max(dp(4), min(ideal_y, Window.height - popup.height - dp(4)))
        Window.add_widget(popup)

    def _hide_font_popup(self):
        if self._font_popup and self._font_popup.parent:
            self._font_popup.parent.remove_widget(self._font_popup)
        self._font_popup = None
