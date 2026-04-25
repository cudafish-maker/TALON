"""
Main screen — root layout after login.

Desktop layout (4-pane):
  Topbar  (42 dp) — TALON logo | active op | Zulu clock | quick-nav buttons
  Body row:
    Icon rail (48 dp) | Asset panel (240 dp) | Map (flex) | Mission+SITREP (260 dp)

Android layout deferred to Phase 4.
"""
import datetime
import typing

from kivy.app import App
from kivy.clock import Clock
from kivy.graphics import Color, Ellipse, Line, Rectangle
from kivy.metrics import dp
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.modalview import ModalView
from kivy.uix.screenmanager import ScreenManager
from kivy.uix.scrollview import ScrollView
from kivy.uix.widget import Widget
from kivymd.uix.screen import MDScreen
from kivymd.uix.selectioncontrol import MDCheckbox

from talon.ui.font_scale import get_font_scale, load_font_scale_from_db
from talon.ui.theme import (
    CHAT_AMBER, CHAT_AMBER2, CHAT_BG0, CHAT_BG1, CHAT_BG2, CHAT_BG3, CHAT_BG4,
    CHAT_BORDER, CHAT_G1, CHAT_G2, CHAT_G3, CHAT_G4, CHAT_G5, CHAT_G6,
    CHAT_RED, CHAT_RED2, SITREP_COLORS, available_ui_themes, get_ui_theme_key,
    get_ui_theme_label,
)
from talon.utils.platform import IS_ANDROID


# ── Font scale ─────────────────────────────────────────────────────────────

def _mfs(base: float) -> float:
    return dp(base * get_font_scale())


# ── Constants ──────────────────────────────────────────────────────────────

_ASSET_GROUPS: list[tuple[str, list[str]]] = [
    ("PERSONNEL",  ["person"]),
    ("LOCATIONS",  ["safe_house", "cache", "rally_point"]),
    ("VEHICLES",   ["vehicle"]),
    ("OTHER",      ["custom"]),
]

_MISSION_STATUS_COLOR: dict[str, tuple] = {
    "active":           CHAT_G5,
    "pending_approval": CHAT_AMBER2,
    "completed":        CHAT_G2,
    "aborted":          CHAT_RED2,
    "rejected":         CHAT_RED,
}


# ── Canvas helpers ─────────────────────────────────────────────────────────

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


# ── Small reusable widgets ─────────────────────────────────────────────────

class _VSep(Widget):
    """Thin vertical separator for the topbar."""
    def __init__(self, **kwargs):
        super().__init__(size_hint=(None, 1), width=dp(1), **kwargs)
        with self.canvas:
            Color(*CHAT_BORDER)
            self._r = Rectangle(pos=self.pos, size=(dp(1), self.height))
        self.bind(
            pos=lambda w, _: setattr(self._r, 'pos', w.pos),
            size=lambda w, _: setattr(self._r, 'size', (dp(1), w.height)),
        )


def _clip_label(label: Label) -> Label:
    """Make a dashboard label stay on one line and ellipsize when space is tight."""
    label.shorten = True
    label.shorten_from = 'right'
    label.max_lines = 1

    def _update_text_box(w, _=None):
        w.text_size = (max(0, w.width), max(0, w.height))

    label.bind(size=_update_text_box)
    _update_text_box(label)
    return label


# ── Asset row ──────────────────────────────────────────────────────────────

class _AssetRow(ButtonBehavior, BoxLayout):
    """One tappable asset row in the left panel."""

    def __init__(self, asset, on_tap: typing.Callable, **kwargs):
        super().__init__(
            orientation='horizontal',
            size_hint_y=None,
            height=_mfs(48),
            padding=(dp(10), dp(4)),
            spacing=dp(6),
            **kwargs,
        )
        self._asset = asset
        self._on_tap = on_tap

        if asset.mission_id:
            dot_color = CHAT_AMBER2
            status_text, status_color = "ASSIGNED", CHAT_AMBER2
        elif asset.verified:
            dot_color = CHAT_G5
            status_text, status_color = "VERIFIED", CHAT_G4
        else:
            dot_color = CHAT_G2
            status_text, status_color = "UNVERIFIED", CHAT_G2

        dot = Widget(size_hint=(None, None), size=(dp(7), dp(7)))
        with dot.canvas:
            Color(*dot_color)
            e = Ellipse(pos=dot.pos, size=dot.size)
        dot.bind(
            pos=lambda w, _: setattr(e, 'pos', w.pos),
            size=lambda w, _: setattr(e, 'size', w.size),
        )

        from talon.assets import CATEGORY_LABEL
        info = BoxLayout(orientation='vertical', spacing=dp(1))

        la = Label(text=asset.label or '—', color=CHAT_G6, font_size=_mfs(11),
                   bold=True, halign='left', valign='middle',
                   size_hint_y=None, height=_mfs(16))
        _clip_label(la)

        lb = Label(text=CATEGORY_LABEL.get(asset.category, asset.category),
                   color=CHAT_G3, font_size=_mfs(9), halign='left', valign='middle',
                   size_hint_y=None, height=_mfs(12))
        _clip_label(lb)

        coord = (f"{asset.lat:.3f}, {asset.lon:.3f}"
                 if asset.lat is not None else "No GPS")
        lc = Label(text=coord, color=CHAT_G2, font_size=_mfs(8),
                   halign='left', valign='middle', size_hint_y=None, height=_mfs(10))
        _clip_label(lc)

        info.add_widget(la)
        info.add_widget(lb)
        info.add_widget(lc)

        st = Label(text=status_text, color=status_color, font_size=_mfs(8),
                   size_hint=(None, None), size=(dp(60), _mfs(14)),
                   halign='right', valign='middle')
        _clip_label(st)

        with self.canvas.before:
            self._bg_c = Color(0, 0, 0, 0)
            self._bg_r = Rectangle(pos=self.pos, size=self.size)
        self.bind(
            pos=lambda w, _: setattr(self._bg_r, 'pos', w.pos),
            size=lambda w, _: setattr(self._bg_r, 'size', w.size),
        )
        _hline(self, CHAT_BORDER, 'bottom')

        self.add_widget(dot)
        self.add_widget(info)
        self.add_widget(st)

    def on_release(self):
        self._on_tap(self._asset)

    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos):
            self._bg_c.rgba = CHAT_BG3
        return super().on_touch_down(touch)

    def on_touch_up(self, touch):
        result = super().on_touch_up(touch)
        self._bg_c.rgba = (0, 0, 0, 0)
        return result


# ── Mission card ───────────────────────────────────────────────────────────

class _MissionCard(ButtonBehavior, BoxLayout):
    def __init__(
        self,
        mission,
        *,
        selected: bool = False,
        on_tap: typing.Optional[typing.Callable] = None,
        **kwargs,
    ):
        super().__init__(
            orientation='vertical',
            size_hint_y=None,
            height=_mfs(72),
            padding=(dp(12), dp(6)),
            spacing=dp(3),
            **kwargs,
        )
        self._mission = mission
        self._on_tap = on_tap
        self._selected = selected
        dot_color = _MISSION_STATUS_COLOR.get(mission.status, CHAT_G2)
        is_active = mission.status == 'active'
        bg_color = CHAT_BG4 if selected else (CHAT_BG3 if is_active else CHAT_BG2)
        border_w = dp(4) if selected else dp(2)

        with self.canvas.before:
            Color(*bg_color)
            self._bg = Rectangle(pos=self.pos, size=self.size)
            Color(*(CHAT_G5 if selected else dot_color))
            self._border = Rectangle(pos=self.pos, size=(border_w, self.height))
        self.bind(pos=self._upd, size=self._upd)
        _hline(self, CHAT_BORDER, 'bottom')

        title_row = BoxLayout(orientation='horizontal', size_hint_y=None,
                              height=_mfs(18), spacing=dp(6))
        dot = Widget(size_hint=(None, None), size=(dp(6), dp(6)))
        with dot.canvas:
            Color(*dot_color)
            e = Ellipse(pos=dot.pos, size=dot.size)
        dot.bind(
            pos=lambda w, _: setattr(e, 'pos', w.pos),
            size=lambda w, _: setattr(e, 'size', w.size),
        )
        tl = Label(text=mission.title, color=CHAT_G6, font_size=_mfs(12), bold=True,
                   halign='left', valign='middle', size_hint_y=None, height=_mfs(18))
        _clip_label(tl)
        sl = Label(text=mission.status.replace('_', ' ').upper(),
                   color=dot_color, font_size=_mfs(8),
                   size_hint=(None, None), size=(dp(90), _mfs(18)),
                   halign='right', valign='middle')
        _clip_label(sl)
        title_row.add_widget(dot)
        title_row.add_widget(tl)
        title_row.add_widget(sl)

        desc = mission.description or ''
        if len(desc) > 65:
            desc = desc[:62] + '…'
        dl = Label(text=desc, color=CHAT_G3, font_size=_mfs(9),
                   halign='left', valign='top', size_hint_y=None, height=_mfs(22))
        _clip_label(dl)

        ts = datetime.datetime.fromtimestamp(mission.created_at).strftime('%Y-%m-%d %H:%M')
        tsl = Label(text=ts, color=CHAT_G2, font_size=_mfs(8),
                    halign='left', valign='middle', size_hint_y=None, height=_mfs(10))
        _clip_label(tsl)

        self.add_widget(title_row)
        self.add_widget(dl)
        self.add_widget(tsl)

    def _upd(self, *_):
        self._bg.pos = self.pos
        self._bg.size = self.size
        self._border.pos = self.pos
        self._border.size = (dp(4) if self._selected else dp(2), self.height)

    def on_release(self):
        if self._on_tap is not None:
            self._on_tap(self._mission)


# ── SITREP row ─────────────────────────────────────────────────────────────

class _SitrepRow(BoxLayout):
    def __init__(self, sitrep, callsign: str, **kwargs):
        is_urgent = sitrep.level in ('FLASH', 'FLASH_OVERRIDE', 'IMMEDIATE')
        super().__init__(
            orientation='vertical',
            size_hint_y=None,
            height=_mfs(50),
            padding=(dp(10), dp(4)),
            spacing=dp(2),
            **kwargs,
        )
        level_color = SITREP_COLORS.get(sitrep.level, CHAT_G4)

        with self.canvas.before:
            Color(0, 0, 0, 0)
            self._bg = Rectangle(pos=self.pos, size=self.size)
            Color(*(CHAT_AMBER2 if is_urgent else (0, 0, 0, 0)))
            self._border = Rectangle(pos=self.pos, size=(dp(2), self.height))
        self.bind(pos=self._upd, size=self._upd)
        _hline(self, CHAT_BORDER, 'bottom')

        head = BoxLayout(orientation='horizontal', size_hint_y=None,
                         height=_mfs(15), spacing=dp(6))
        time_l = Label(
            text=datetime.datetime.fromtimestamp(sitrep.created_at).strftime('%H:%M'),
            color=CHAT_G2, font_size=_mfs(9),
            size_hint=(None, None), size=(dp(35), _mfs(15)),
            halign='left', valign='middle',
        )
        head.add_widget(_clip_label(time_l))
        cs_l = Label(text=callsign, color=CHAT_G5, font_size=_mfs(10), bold=True,
                     halign='left', valign='middle', size_hint_y=None, height=_mfs(15))
        _clip_label(cs_l)
        head.add_widget(cs_l)
        level_l = Label(
            text=sitrep.level, color=level_color, font_size=_mfs(8),
            size_hint=(None, None), size=(dp(70), _mfs(15)),
            halign='right', valign='middle',
        )
        head.add_widget(_clip_label(level_l))

        body = sitrep.body
        if isinstance(body, bytes):
            body = body.decode('utf-8', errors='replace')
        if len(body) > 70:
            body = body[:67] + '…'
        bl = Label(text=body,
                   color=CHAT_AMBER if is_urgent else CHAT_G3,
                   font_size=_mfs(9), halign='left', valign='top',
                   size_hint_y=None, height=_mfs(24))
        _clip_label(bl)

        self.add_widget(head)
        self.add_widget(bl)

    def _upd(self, *_):
        self._bg.pos = self.pos
        self._bg.size = self.size
        self._border.pos = self.pos
        self._border.size = (dp(2), self.height)


# ── MainScreen ─────────────────────────────────────────────────────────────

class MainScreen(MDScreen):
    """Root layout screen — adapts to platform and mode."""

    def on_kv_post(self, base_widget) -> None:
        app = App.get_running_app()
        self._selected_mission_id: typing.Optional[int] = None
        self._map_asset_filter_ids: typing.Optional[set[int]] = None
        self._last_map_context = None
        if IS_ANDROID:
            self._build_android_layout()
        else:
            self._build_desktop_layout(app.mode)

    # ------------------------------------------------------------------
    # Desktop layout
    # ------------------------------------------------------------------

    def _build_desktop_layout(self, mode: str) -> None:
        self.clear_widgets()
        root = BoxLayout(orientation='vertical')
        _rgba_bg(root, CHAT_BG0)

        root.add_widget(self._make_topbar())

        body = BoxLayout(orientation='horizontal')

        asset_panel = self._make_asset_panel()
        self._asset_panel = asset_panel
        body.add_widget(asset_panel)
        body.add_widget(self._make_panel_toggle('asset'))

        # FloatLayout for map + layer-toggle overlay. MapView already has its own
        # internal StencilPush/StencilUse (in its KV rule) that clips tiles to
        # its own bounds, so an outer StencilView is not only redundant but
        # causes a double-stencil interaction that mis-clips tiles at some sizes.
        map_container = FloatLayout(size_hint_x=6)
        _rgba_bg(map_container, CHAT_BG0)
        self._map_container = map_container
        body.add_widget(map_container)

        body.add_widget(self._make_panel_toggle('right'))
        right_panel = self._make_right_panel()
        self._right_panel = right_panel
        body.add_widget(right_panel)

        root.add_widget(body)
        self.add_widget(root)

        self._wire_map(map_container)

    def on_ui_theme_changed(self) -> None:
        if IS_ANDROID:
            self.clear_widgets()
            self._build_android_layout()
        else:
            app = App.get_running_app()
            self._build_desktop_layout(app.mode)
            self._refresh_all()

    # ------------------------------------------------------------------
    # Panel collapse toggles
    # ------------------------------------------------------------------

    def _make_panel_toggle(self, side: str) -> BoxLayout:
        """Thin vertical strip with a chevron to collapse/expand the adjacent panel.

        side='asset' → strip sits between asset panel and map (chevron faces left).
        side='right' → strip sits between map and right panel (chevron faces right).
        """
        strip = BoxLayout(orientation='vertical', size_hint=(None, 1), width=dp(18))
        _rgba_bg(strip, CHAT_BG2)
        border_edge = 'right' if side == 'asset' else 'left'
        _vline(strip, CHAT_BORDER, border_edge)

        # < = collapse asset panel; > = collapse right panel
        initial_text = '<' if side == 'asset' else '>'
        btn = Button(
            text=initial_text,
            color=CHAT_G5, font_size=dp(14), bold=True,
            background_normal='', background_color=(0, 0, 0, 0),
            size_hint=(1, None), height=dp(48),
        )
        btn.bind(on_release=lambda _: self._toggle_panel(side))

        if side == 'asset':
            self._asset_toggle_btn = btn
        else:
            self._right_toggle_btn = btn

        strip.add_widget(Widget())
        strip.add_widget(btn)
        strip.add_widget(Widget())
        return strip

    def _toggle_panel(self, side: str) -> None:
        if side == 'asset':
            panel = self._asset_panel
            btn = self._asset_toggle_btn
            collapsed = getattr(self, '_asset_collapsed', False)
            if collapsed:
                panel.size_hint_x = 2
                panel.opacity = 1
                panel.disabled = False
                btn.text = '<'
                self._asset_collapsed = False
            else:
                panel.size_hint_x = None
                panel.width = 0
                panel.opacity = 0
                panel.disabled = True
                btn.text = '>'
                self._asset_collapsed = True
        else:
            panel = self._right_panel
            btn = self._right_toggle_btn
            collapsed = getattr(self, '_right_collapsed', False)
            if collapsed:
                panel.size_hint_x = 2
                panel.opacity = 1
                panel.disabled = False
                btn.text = '>'
                self._right_collapsed = False
            else:
                panel.size_hint_x = None
                panel.width = 0
                panel.opacity = 0
                panel.disabled = True
                btn.text = '<'
                self._right_collapsed = True

    # ------------------------------------------------------------------
    # Topbar
    # ------------------------------------------------------------------

    def _make_topbar(self) -> BoxLayout:
        bar = BoxLayout(
            orientation='horizontal',
            size_hint_y=None,
            height=dp(42),
            padding=(dp(10), 0, dp(8), 0),
            spacing=0,
        )
        _rgba_bg(bar, CHAT_BG1)
        _hline(bar, CHAT_BORDER, 'bottom')

        def _lbl(text, color=CHAT_G4, size=11, bold=False, w=None, **kw):
            l = Label(text=text, color=color, font_size=dp(size), bold=bold,
                      halign='left', valign='middle', **kw)
            if w:
                l.size_hint_x = None
                l.width = dp(w)
            return _clip_label(l)

        # Logo — fixed width
        bar.add_widget(_lbl('TALON', CHAT_G6, 18, True, w=64))
        bar.add_widget(_VSep())
        bar.add_widget(Widget(size_hint_x=None, width=dp(8)))

        # Active mission — FLEX: takes all available space, never overflows
        self._tb_mission_lbl = Label(
            text='NO ACTIVE MISSION', color=CHAT_G2,
            font_size=dp(12), bold=True,
            halign='left', valign='middle',
            size_hint_x=1,
        )
        _clip_label(self._tb_mission_lbl)
        bar.add_widget(self._tb_mission_lbl)

        bar.add_widget(Widget(size_hint_x=None, width=dp(8)))
        bar.add_widget(_VSep())
        bar.add_widget(Widget(size_hint_x=None, width=dp(6)))

        # Zulu clock — fixed, compact
        self._clock_lbl = _lbl('------Z', CHAT_G5, 11, w=72)
        bar.add_widget(self._clock_lbl)

        bar.add_widget(Widget(size_hint_x=None, width=dp(6)))
        bar.add_widget(_VSep())
        bar.add_widget(Widget(size_hint_x=None, width=dp(6)))

        self._theme_btn = Button(
            text=self._theme_button_text(),
            color=CHAT_G4,
            font_size=dp(9),
            background_normal='',
            background_color=(*CHAT_G1[:3], 1.0),
            size_hint=(None, None),
            size=(dp(104), dp(26)),
        )
        self._theme_btn.bind(on_release=lambda _: self._open_theme_picker())
        bar.add_widget(self._theme_btn)

        bar.add_widget(Widget(size_hint_x=None, width=dp(6)))
        bar.add_widget(_VSep())
        bar.add_widget(Widget(size_hint_x=None, width=dp(6)))

        # FLASH alert — zero-width when hidden so it doesn't reserve space
        self._flash_btn = Button(
            text='⚡ FLASH', color=CHAT_RED2, font_size=dp(10),
            background_normal='', background_color=(*CHAT_RED[:3], 0.15),
            size_hint=(None, None), size=(dp(0), dp(26)),
            opacity=0,
        )
        bar.add_widget(self._flash_btn)

        # Quick-nav buttons — fixed, compact
        for text, screen in [("+ MISSION", "mission"), ("+ SITREP", "sitrep"), ("▶ CHAT", "chat")]:
            btn = Button(
                text=text, color=CHAT_G3, font_size=dp(10),
                background_normal='', background_color=(*CHAT_G1[:3], 1.0),
                size_hint=(None, None), size=(dp(76), dp(26)),
            )
            btn.bind(on_release=lambda _, s=screen: self.navigate_to(s))
            bar.add_widget(Widget(size_hint_x=None, width=dp(4)))
            bar.add_widget(btn)

        return bar

    def _theme_button_text(self) -> str:
        label = get_ui_theme_label(get_ui_theme_key()).upper()
        return label if len(label) <= 14 else label[:13] + '…'

    def _open_theme_picker(self) -> None:
        modal = ModalView(
            size_hint=(None, None),
            size=(dp(360), dp(230)),
            background='',
            background_color=(0, 0, 0, 0.62),
            auto_dismiss=True,
        )
        wrap = BoxLayout(orientation='vertical', size_hint=(1, 1))
        _rgba_bg(wrap, CHAT_BG2)

        hdr = BoxLayout(
            orientation='horizontal',
            size_hint_y=None,
            height=dp(42),
            padding=(dp(12), 0),
        )
        _rgba_bg(hdr, CHAT_BG1)
        _hline(hdr, CHAT_BORDER, 'bottom')
        title = Label(
            text='DISPLAY THEME',
            color=CHAT_G6,
            font_size=dp(12),
            bold=True,
            halign='left',
            valign='middle',
        )
        _clip_label(title)
        hdr.add_widget(title)
        wrap.add_widget(hdr)

        current = get_ui_theme_key()
        for key, label in available_ui_themes():
            selected = key == current
            btn = Button(
                text=('✓ ' if selected else '  ') + label.upper(),
                color=CHAT_G6 if selected else CHAT_G4,
                font_size=dp(12),
                bold=selected,
                background_normal='',
                background_color=CHAT_BG4 if selected else CHAT_BG3,
                size_hint_y=None,
                height=dp(48),
            )
            btn.bind(on_release=lambda _, k=key: self._select_theme(modal, k))
            wrap.add_widget(btn)

        wrap.add_widget(Widget())
        close = Button(
            text='CLOSE',
            color=CHAT_G3,
            font_size=dp(10),
            background_normal='',
            background_color=(*CHAT_G1[:3], 1.0),
            size_hint_y=None,
            height=dp(36),
        )
        close.bind(on_release=lambda _: modal.dismiss())
        wrap.add_widget(close)

        modal.add_widget(wrap)
        modal.open()

    def _select_theme(self, modal: ModalView, theme_key: str) -> None:
        modal.dismiss()
        app = App.get_running_app()
        if hasattr(app, 'set_global_theme'):
            app.set_global_theme(theme_key)

    # ------------------------------------------------------------------
    # Left panel — asset list
    # ------------------------------------------------------------------

    def _make_asset_panel(self) -> BoxLayout:
        panel = BoxLayout(orientation='vertical', size_hint_x=2, size_hint_min_x=dp(160))
        _rgba_bg(panel, CHAT_BG1)
        _vline(panel, CHAT_BORDER, 'right')

        hdr = BoxLayout(orientation='horizontal', size_hint_y=None, height=_mfs(36),
                        padding=(dp(10), 0))
        _rgba_bg(hdr, CHAT_BG1)
        _hline(hdr, CHAT_BORDER, 'bottom')
        self._asset_hdr = hdr

        self._asset_panel_title_lbl = Label(text='AVAILABLE ASSETS', color=CHAT_G4,
                                             font_size=_mfs(10), bold=True,
                                             halign='left', valign='middle')
        _clip_label(self._asset_panel_title_lbl)
        self._asset_count_lbl = Label(text='', color=CHAT_G2, font_size=_mfs(9),
                                       size_hint=(None, 1), width=dp(62),
                                       halign='right', valign='middle')
        _clip_label(self._asset_count_lbl)
        self._map_asset_btn = Button(
            text='MAP ALL',
            color=CHAT_G4,
            font_size=_mfs(9),
            background_normal='',
            background_color=(*CHAT_G1[:3], 1.0),
            size_hint=(None, None),
            size=(dp(58), dp(24)),
        )
        self._map_asset_btn.bind(on_release=lambda _: self._open_map_asset_picker())
        hdr.add_widget(self._asset_panel_title_lbl)
        hdr.add_widget(self._asset_count_lbl)
        hdr.add_widget(Widget(size_hint_x=None, width=dp(6)))
        hdr.add_widget(self._map_asset_btn)
        panel.add_widget(hdr)

        scroll = ScrollView(size_hint=(1, 1))
        self._asset_list = GridLayout(cols=1, size_hint_y=None, spacing=0)
        self._asset_list.bind(minimum_height=self._asset_list.setter('height'))
        scroll.add_widget(self._asset_list)
        panel.add_widget(scroll)
        return panel

    # ------------------------------------------------------------------
    # Right panel — missions + sitrep feed
    # ------------------------------------------------------------------

    def _make_right_panel(self) -> BoxLayout:
        panel = BoxLayout(orientation='vertical', size_hint_x=2, size_hint_min_x=dp(180))
        _rgba_bg(panel, CHAT_BG1)
        _vline(panel, CHAT_BORDER, 'left')

        # Missions header
        mh = BoxLayout(orientation='horizontal', size_hint_y=None, height=_mfs(36),
                       padding=(dp(10), 0))
        _rgba_bg(mh, CHAT_BG1)
        _hline(mh, CHAT_BORDER, 'bottom')
        self._mission_hdr = mh

        self._mission_title_lbl = Label(text='MISSIONS', color=CHAT_G4, font_size=_mfs(10),
                                         bold=True, halign='left', valign='middle')
        _clip_label(self._mission_title_lbl)
        self._mission_count_lbl = Label(text='', color=CHAT_G2, font_size=_mfs(9),
                                         size_hint=(None, 1), width=dp(70),
                                         halign='right', valign='middle')
        _clip_label(self._mission_count_lbl)
        mh.add_widget(self._mission_title_lbl)
        mh.add_widget(self._mission_count_lbl)
        panel.add_widget(mh)

        self._mission_cards = GridLayout(cols=1, size_hint_y=None, spacing=0)
        self._mission_cards.bind(minimum_height=self._mission_cards.setter('height'))
        panel.add_widget(self._mission_cards)

        # SITREP header
        sh = BoxLayout(orientation='horizontal', size_hint_y=None, height=_mfs(32),
                       padding=(dp(10), 0))
        _rgba_bg(sh, CHAT_BG1)
        _hline(sh, CHAT_BORDER, 'top')
        _hline(sh, CHAT_BORDER, 'bottom')
        self._sitrep_hdr = sh

        self._sitrep_title_lbl = Label(text='SITREP FEED', color=CHAT_G4, font_size=_mfs(10),
                                        bold=True, halign='left', valign='middle')
        _clip_label(self._sitrep_title_lbl)
        self._sr_live_lbl = Label(text='LIVE', color=CHAT_G3, font_size=_mfs(9),
                                   size_hint=(None, 1), width=dp(35),
                                   halign='right', valign='middle')
        _clip_label(self._sr_live_lbl)
        sh.add_widget(self._sitrep_title_lbl)
        sh.add_widget(self._sr_live_lbl)
        panel.add_widget(sh)

        sr_scroll = ScrollView(size_hint=(1, 1))
        self._sitrep_list = GridLayout(cols=1, size_hint_y=None, spacing=0)
        self._sitrep_list.bind(minimum_height=self._sitrep_list.setter('height'))
        sr_scroll.add_widget(self._sitrep_list)
        panel.add_widget(sr_scroll)
        return panel

    # ------------------------------------------------------------------
    # Map
    # ------------------------------------------------------------------

    def _wire_map(self, container: FloatLayout) -> None:
        from talon.ui.widgets.map_widget import MapWidget
        self.map_widget = MapWidget(size_hint=(1, 1))
        container.add_widget(self.map_widget, index=len(container.children))
        # Propagate size/pos immediately on any container resize so MapView
        # reloads tiles for the correct viewport without waiting for
        # FloatLayout's deferred do_layout pass.
        container.bind(
            size=lambda w, v: setattr(self.map_widget, 'size', v),
            pos=lambda w, v: setattr(self.map_widget, 'pos', v),
        )
        # Force a full tile refresh once layout has settled (~100 ms).
        # MapView's on_size fires during FloatLayout's first pass, but at that
        # point center_x may not yet reflect the final pos; this ensures tiles
        # are requested for the true viewport after both size and pos are stable.
        Clock.schedule_once(lambda dt: self.map_widget.trigger_update(True), 0.1)
        self.map_widget.bind(on_asset_tap=self._on_asset_tap)
        self._build_layer_toggle(container)

    def _build_layer_toggle(self, container: FloatLayout) -> None:
        toggle = BoxLayout(
            orientation='vertical',
            size_hint=(None, None),
            size=(dp(72), dp(82)),
            pos_hint={'right': 1, 'top': 1},
            padding=dp(4), spacing=dp(2),
        )
        _rgba_bg(toggle, (*CHAT_BG2[:3], 0.88))

        self._layer_btns: dict[str, Button] = {}
        for key, label in [("osm", "OSM"), ("satellite", "SAT"), ("topo", "TOPO")]:
            active = key == "osm"
            btn = Button(
                text=label, font_size=dp(10),
                color=CHAT_G6 if active else CHAT_G3,
                background_normal='',
                background_color=CHAT_BG4 if active else CHAT_BG3,
                size_hint_y=None, height=dp(22),
            )
            btn.bind(on_release=lambda _, k=key: self._on_layer_selected(k))
            self._layer_btns[key] = btn
            toggle.add_widget(btn)

        container.add_widget(toggle)

    def _on_layer_selected(self, name: str) -> None:
        if hasattr(self, 'map_widget'):
            self.map_widget.set_layer(name)
        for k, btn in self._layer_btns.items():
            btn.color = CHAT_G6 if k == name else CHAT_G3
            btn.background_color = CHAT_BG4 if k == name else CHAT_BG3

    def _build_android_layout(self) -> None:
        pass  # Phase 4

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def on_pre_enter(self) -> None:
        app = App.get_running_app()
        if hasattr(app, 'clear_badge'):
            app.clear_badge('main')
        load_font_scale_from_db(app.conn)
        if not getattr(self, '_clock_handle', None):
            self._clock_handle = Clock.schedule_interval(self._tick_clock, 1.0)
        self._tick_clock(0)
        self._refresh_all()

    def on_pre_leave(self) -> None:
        handle = getattr(self, '_clock_handle', None)
        if handle:
            handle.cancel()
            self._clock_handle = None

    def _tick_clock(self, _dt) -> None:
        if hasattr(self, '_clock_lbl'):
            self._clock_lbl.text = datetime.datetime.utcnow().strftime('%H%M%S') + 'Z'

    # ------------------------------------------------------------------
    # Data refresh
    # ------------------------------------------------------------------

    def _rescale_headers(self) -> None:
        """Update header widget heights and font sizes to match current font scale."""
        if hasattr(self, '_asset_hdr'):
            self._asset_hdr.height = _mfs(36)
            self._asset_panel_title_lbl.font_size = _mfs(10)
            self._asset_count_lbl.font_size = _mfs(9)
        if hasattr(self, '_mission_hdr'):
            self._mission_hdr.height = _mfs(36)
            self._mission_title_lbl.font_size = _mfs(10)
            self._mission_count_lbl.font_size = _mfs(9)
        if hasattr(self, '_sitrep_hdr'):
            self._sitrep_hdr.height = _mfs(32)
            self._sitrep_title_lbl.font_size = _mfs(10)
            self._sr_live_lbl.font_size = _mfs(9)

    def _refresh_all(self) -> None:
        self._rescale_headers()
        app = App.get_running_app()
        if app.conn is None:
            return
        try:
            from talon.sitrep import load_sitreps
            from talon.ui.widgets.map_data import load_map_context

            map_context = load_map_context(app.conn)
            assets = map_context.assets
            missions = map_context.missions
            sitreps_raw = load_sitreps(app.conn, app.db_key) if app.db_key else []
        except Exception:
            return

        self._last_map_context = map_context
        if self._map_asset_filter_ids is not None:
            mappable_ids = {
                asset.id for asset in assets
                if asset.lat is not None and asset.lon is not None
            }
            self._map_asset_filter_ids.intersection_update(mappable_ids)
        shown_missions = self._shown_missions(missions)
        shown_ids = {mission.id for mission in shown_missions}
        if self._selected_mission_id not in shown_ids:
            self._selected_mission_id = None

        if hasattr(self, 'map_widget'):
            visible_context = map_context.with_selected_mission_overlays(
                self._selected_mission_id
            ).with_visible_assets(
                self._map_asset_filter_ids,
                selected_mission_id=self._selected_mission_id,
            )
            self.map_widget.set_map_context(visible_context)

        self._refresh_asset_panel(assets)
        self._refresh_mission_panel(missions, shown_missions=shown_missions)
        self._refresh_sitrep_panel(sitreps_raw)

        active_m = [m for m in missions if m.status == 'active']
        pending_m = [m for m in missions if m.status == 'pending_approval']
        if active_m:
            self._tb_mission_lbl.text = active_m[0].title.upper()
            self._tb_mission_lbl.color = CHAT_G5
        elif pending_m:
            self._tb_mission_lbl.text = pending_m[0].title.upper() + '  [PENDING]'
            self._tb_mission_lbl.color = CHAT_AMBER2
        else:
            self._tb_mission_lbl.text = 'NO ACTIVE MISSION'
            self._tb_mission_lbl.color = CHAT_G2

        has_flash = any(s.level in ('FLASH', 'FLASH_OVERRIDE') for s, _, _ in sitreps_raw)
        if hasattr(self, '_flash_btn'):
            self._flash_btn.opacity = 1.0 if has_flash else 0.0
            self._flash_btn.width = dp(88) if has_flash else dp(0)

    def _refresh_map_assets(self) -> None:
        """Kept for external callers — delegates to full refresh."""
        self._refresh_all()

    def _refresh_asset_panel(self, assets: list) -> None:
        if not hasattr(self, '_asset_list'):
            return
        self._asset_list.clear_widgets()
        self._asset_count_lbl.text = f'{len(assets)} TOTAL'
        self._update_map_asset_button()
        for group_name, categories in _ASSET_GROUPS:
            group = [a for a in assets if a.category in categories]
            if not group:
                continue
            wrap = BoxLayout(size_hint_y=None, height=_mfs(22), padding=(dp(10), 0))
            gl = Label(text=group_name, color=CHAT_G2, font_size=_mfs(9), bold=True,
                       halign='left', valign='middle')
            _clip_label(gl)
            wrap.add_widget(gl)
            self._asset_list.add_widget(wrap)
            for asset in group:
                self._asset_list.add_widget(
                    _AssetRow(asset=asset, on_tap=self._on_summary_asset_tap)
                )

    def _shown_missions(self, missions: list) -> list:
        return [m for m in missions if m.status in ('active', 'pending_approval')][:5]

    def _refresh_mission_panel(
        self,
        missions: list,
        *,
        shown_missions: typing.Optional[list] = None,
    ) -> None:
        if not hasattr(self, '_mission_cards'):
            return
        self._mission_cards.clear_widgets()
        active_count = sum(1 for m in missions if m.status == 'active')
        if self._selected_mission_id is not None:
            self._mission_count_lbl.text = '1 SELECTED'
        else:
            self._mission_count_lbl.text = f'{active_count} ACTIVE'
        shown = shown_missions if shown_missions is not None else self._shown_missions(missions)
        if shown:
            for m in shown:
                self._mission_cards.add_widget(_MissionCard(
                    mission=m,
                    selected=m.id == self._selected_mission_id,
                    on_tap=self._on_mission_tap,
                ))
        else:
            el = Label(text='No active missions', color=CHAT_G2, font_size=_mfs(10),
                       size_hint_y=None, height=_mfs(36))
            self._mission_cards.add_widget(el)

    def _on_mission_tap(self, mission) -> None:
        if self._selected_mission_id == mission.id:
            self._selected_mission_id = None
        else:
            self._selected_mission_id = mission.id
        self._refresh_all()

    def _update_map_asset_button(self) -> None:
        if not hasattr(self, '_map_asset_btn'):
            return
        if self._map_asset_filter_ids is None:
            self._map_asset_btn.text = 'MAP ALL'
            self._map_asset_btn.color = CHAT_G4
        else:
            self._map_asset_btn.text = f'MAP {len(self._map_asset_filter_ids)}'
            self._map_asset_btn.color = CHAT_AMBER2

    def _open_map_asset_picker(self) -> None:
        context = getattr(self, '_last_map_context', None)
        if context is None:
            self._refresh_all()
            context = getattr(self, '_last_map_context', None)
        assets = list(getattr(context, 'assets', []) or [])
        mappable = [asset for asset in assets if asset.lat is not None and asset.lon is not None]

        modal = ModalView(
            size_hint=(None, None),
            size=(dp(420), dp(560)),
            background='',
            background_color=(0, 0, 0, 0.62),
            auto_dismiss=False,
        )
        wrap = BoxLayout(orientation='vertical', size_hint=(1, 1))
        _rgba_bg(wrap, CHAT_BG2)

        hdr = BoxLayout(
            orientation='horizontal',
            size_hint_y=None,
            height=dp(42),
            padding=(dp(10), 0),
            spacing=dp(6),
        )
        _rgba_bg(hdr, CHAT_BG1)
        _hline(hdr, CHAT_BORDER, 'bottom')
        title = Label(
            text='MAP ASSETS',
            color=CHAT_G5,
            font_size=dp(12),
            bold=True,
            halign='left',
            valign='middle',
        )
        title.bind(size=title.setter('text_size'))
        hdr.add_widget(title)
        hdr.add_widget(Label(
            text=f'{len(mappable)} MAPPABLE',
            color=CHAT_G2,
            font_size=dp(9),
            size_hint=(None, 1),
            width=dp(92),
            halign='right',
            valign='middle',
        ))
        wrap.add_widget(hdr)

        note = Label(
            text='Selected mission assets are always shown while that mission is selected.',
            color=CHAT_G3,
            font_size=dp(10),
            size_hint_y=None,
            height=dp(34),
            padding=(dp(10), 0),
            halign='left',
            valign='middle',
        )
        note.bind(size=note.setter('text_size'))
        wrap.add_widget(note)

        scroll = ScrollView(size_hint=(1, 1))
        body = GridLayout(cols=1, size_hint_y=None, spacing=0)
        body.bind(minimum_height=body.setter('height'))
        checks: dict[int, MDCheckbox] = {}

        if not mappable:
            empty = Label(
                text='No assets have map coordinates.',
                color=CHAT_G2,
                font_size=dp(11),
                size_hint_y=None,
                height=dp(48),
            )
            body.add_widget(empty)
        else:
            current = self._map_asset_filter_ids
            for asset in mappable:
                row = BoxLayout(
                    orientation='horizontal',
                    size_hint_y=None,
                    height=dp(42),
                    padding=(dp(8), 0),
                    spacing=dp(6),
                )
                _hline(row, CHAT_BORDER, 'bottom')
                chk = MDCheckbox(
                    size_hint=(None, None),
                    size=(dp(36), dp(36)),
                    active=current is None or asset.id in current,
                )
                checks[asset.id] = chk
                row.add_widget(chk)

                mission_tag = ''
                if (
                    self._selected_mission_id is not None
                    and asset.mission_id == self._selected_mission_id
                ):
                    mission_tag = '  [MISSION]'
                label = Label(
                    text=f'{asset.label}{mission_tag}',
                    color=CHAT_G6 if mission_tag else CHAT_G4,
                    font_size=dp(11),
                    bold=bool(mission_tag),
                    halign='left',
                    valign='middle',
                )
                label.bind(size=label.setter('text_size'))
                row.add_widget(label)
                row.add_widget(Label(
                    text=asset.category.replace('_', ' ').upper(),
                    color=CHAT_G2,
                    font_size=dp(8),
                    size_hint=(None, 1),
                    width=dp(92),
                    halign='right',
                    valign='middle',
                ))
                body.add_widget(row)

        scroll.add_widget(body)
        wrap.add_widget(scroll)

        actions = BoxLayout(
            orientation='horizontal',
            size_hint_y=None,
            height=dp(52),
            padding=(dp(8), dp(6)),
            spacing=dp(6),
        )
        _rgba_bg(actions, CHAT_BG1)
        _hline(actions, CHAT_BORDER, 'top')

        def _set_all(active: bool) -> None:
            for chk in checks.values():
                chk.active = active

        def _apply() -> None:
            selected = {aid for aid, chk in checks.items() if chk.active}
            if len(selected) == len(checks):
                self._map_asset_filter_ids = None
            else:
                self._map_asset_filter_ids = selected
            modal.dismiss()
            self._refresh_all()

        for text, cb, color in [
            ('ALL', lambda *_: _set_all(True), CHAT_G3),
            ('NONE', lambda *_: _set_all(False), CHAT_G3),
            ('CANCEL', lambda *_: modal.dismiss(), CHAT_G2),
            ('APPLY', lambda *_: _apply(), CHAT_G5),
        ]:
            btn = Button(
                text=text,
                color=color,
                font_size=dp(10),
                background_normal='',
                background_color=(*CHAT_G1[:3], 1.0),
            )
            btn.bind(on_release=cb)
            actions.add_widget(btn)
        wrap.add_widget(actions)
        modal.add_widget(wrap)
        modal.open()

    def _refresh_sitrep_panel(self, sitreps_raw: list) -> None:
        if not hasattr(self, '_sitrep_list'):
            return
        self._sitrep_list.clear_widgets()
        if sitreps_raw:
            for sitrep, callsign, _al in sitreps_raw[:8]:
                self._sitrep_list.add_widget(
                    _SitrepRow(sitrep=sitrep, callsign=callsign or '—')
                )
        else:
            el = Label(text='No SITREPs', color=CHAT_G2, font_size=_mfs(10),
                       size_hint_y=None, height=_mfs(36))
            self._sitrep_list.add_widget(el)

    # ------------------------------------------------------------------
    # Asset tap → detail popup
    # ------------------------------------------------------------------

    def _on_summary_asset_tap(self, asset) -> None:
        if hasattr(self, 'map_widget') and asset.lat is not None and asset.lon is not None:
            self.map_widget.center_on(asset.lat, asset.lon)
            self.map_widget.zoom = 15
        self._on_asset_tap(None, asset)

    def _on_asset_tap(self, _map_widget, asset) -> None:
        app = App.get_running_app()
        linked: list = []
        if app.conn is not None and app.db_key is not None:
            try:
                from talon.sitrep import load_sitreps
                linked = [(s, cs) for s, cs, _ in
                          load_sitreps(app.conn, app.db_key, asset_id=asset.id)]
            except Exception:
                pass
        self._show_asset_dialog(asset, linked)

    def _show_asset_dialog(self, asset, linked_sitreps: list) -> None:
        from talon.ui.widgets.context_panel import ContextPanel

        modal = ModalView(
            size_hint=(None, None),
            size=(dp(340), dp(500)),
            background='',
            background_color=(0, 0, 0, 0.6),
        )
        wrap = BoxLayout(orientation='vertical',
                         size_hint=(None, None), size=(dp(340), dp(500)))
        _rgba_bg(wrap, CHAT_BG2)

        close_row = BoxLayout(size_hint_y=None, height=dp(36),
                              padding=(dp(4), dp(4)))
        _rgba_bg(close_row, CHAT_BG1)
        close_row.add_widget(Widget())
        close_btn = Button(
            text='✕  CLOSE', color=CHAT_G3, font_size=dp(10),
            background_normal='', background_color=(*CHAT_G1[:3], 1.0),
            size_hint=(None, None), size=(dp(80), dp(26)),
        )
        close_btn.bind(on_release=lambda _: modal.dismiss())
        close_row.add_widget(close_btn)
        wrap.add_widget(close_row)

        panel = ContextPanel(size_hint=(1, 1))
        _rgba_bg(panel, CHAT_BG2)
        panel.show_asset(asset, linked_sitreps=linked_sitreps)
        wrap.add_widget(panel)
        modal.add_widget(wrap)
        modal.open()

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def navigate_to(self, screen_name: str) -> None:
        sm: ScreenManager = self.manager
        if any(s.name == screen_name for s in sm.screens):
            sm.current = screen_name

    # ------------------------------------------------------------------
    # Sync engine compat
    # ------------------------------------------------------------------

    def update_summary(self, *_args, **_kwargs) -> None:
        """Compatibility stub — right panel auto-refreshes on data push."""
        self._refresh_all()
