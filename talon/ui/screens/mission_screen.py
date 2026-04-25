"""
Mission screen — submit, review, approve, and manage tactical missions.
Layout built entirely in Python; mission.kv is a minimal registration stub.
"""
import datetime
import typing

from kivy.app import App
from kivy.graphics import Color, Ellipse, Line, Rectangle
from kivy.metrics import dp
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.modalview import ModalView
from kivy.uix.scrollview import ScrollView
from kivy.uix.widget import Widget
from kivymd.uix.button import MDIconButton
from kivymd.uix.screen import MDScreen
from kivymd.uix.selectioncontrol import MDCheckbox

from talon.assets import load_assets
from talon.missions import MISSION_STATUSES, get_channel_for_mission, get_mission_assets, load_missions
from talon.services.missions import (
    abort_mission_command,
    approve_mission_command,
    complete_mission_command,
    delete_mission_command,
    reject_mission_command,
)
from talon.sitrep import load_sitreps
from talon.ui.font_scale import get_font_scale
from talon.ui.theme import (
    CHAT_AMBER, CHAT_AMBER2, CHAT_BG0, CHAT_BG1, CHAT_BG2, CHAT_BG3, CHAT_BG4,
    CHAT_BORDER, CHAT_G1, CHAT_G2, CHAT_G3, CHAT_G4, CHAT_G5, CHAT_G6,
    CHAT_RED, CHAT_RED2,
)
from talon.ui.widgets.map_draw import CATEGORY_ABBR as _CATEGORY_ABBR
from talon.waypoints import load_waypoints
from talon.zones import load_zones

def _fs(base: float) -> float:
    return dp(base * get_font_scale())


# ---------------------------------------------------------------------------
# Status display maps
# ---------------------------------------------------------------------------

_STATUS_COLOR: dict[str, tuple] = {
    "pending_approval": CHAT_AMBER2,
    "active":           CHAT_G5,
    "rejected":         CHAT_RED2,
    "completed":        CHAT_G3,
    "aborted":          CHAT_G2,
}

_STATUS_LABEL: dict[str, str] = {
    "pending_approval": "PENDING",
    "active":           "ACTIVE",
    "rejected":         "REJECTED",
    "completed":        "COMPLETED",
    "aborted":          "ABORTED",
}

_FILTER_OPTIONS: list[tuple[str, typing.Optional[str]]] = [
    ("ALL MISSIONS",   None),
    ("PENDING",        "pending_approval"),
    ("ACTIVE",         "active"),
    ("REJECTED",       "rejected"),
    ("COMPLETED",      "completed"),
    ("ABORTED",        "aborted"),
]

_PRIORITY_COLOR: dict[str, tuple] = {
    "PRIORITY": CHAT_AMBER2,
    "FLASH":    CHAT_RED2,
}


# ---------------------------------------------------------------------------
# Canvas helpers (same pattern as main_screen / chat_screen)
# ---------------------------------------------------------------------------

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


def _lbl(text, color=CHAT_G4, fsize=11, bold=False, halign='left', **kw):
    l = Label(text=text, color=color, font_size=_fs(fsize), bold=bold,
              halign=halign, valign='middle', **kw)
    l.bind(size=l.setter('text_size'))
    return l


def _btn(text, bg=CHAT_BG3, fg=CHAT_G4, size=10, h=28, w=None, **kw):
    b = Button(
        text=text, color=fg, font_size=_fs(size),
        background_normal='', background_color=bg,
        size_hint_y=None, height=dp(h), **kw,
    )
    if w is not None:
        b.size_hint_x = None
        b.width = dp(w)
    return b


# ---------------------------------------------------------------------------
# Mission list row
# ---------------------------------------------------------------------------

class _MissionRow(ButtonBehavior, BoxLayout):
    def __init__(self, mission, is_server: bool,
                 on_tap: typing.Callable, on_quick_approve: typing.Callable, **kwargs):
        super().__init__(
            orientation='horizontal',
            size_hint_y=None, height=dp(68),
            padding=(0, 0), spacing=0,
            **kwargs,
        )
        self._mission = mission
        self._on_tap = on_tap

        color = _STATUS_COLOR.get(mission.status, CHAT_G2)
        status_label = _STATUS_LABEL.get(mission.status, mission.status.upper())
        is_active = mission.status == 'active'

        # Background
        with self.canvas.before:
            self._bg_c = Color(*(CHAT_BG3 if is_active else CHAT_BG2))
            self._bg_r = Rectangle(pos=self.pos, size=self.size)
            Color(*color)
            self._bar = Rectangle(pos=self.pos, size=(dp(3), self.height))
        self.bind(pos=self._upd_canvas, size=self._upd_canvas)
        _hline(self, CHAT_BORDER, 'bottom')

        # Spacer after bar
        self.add_widget(Widget(size_hint_x=None, width=dp(3)))

        # Text block
        text_block = BoxLayout(orientation='vertical', padding=(dp(8), dp(6)),
                               spacing=dp(2))

        title_lbl = _lbl(mission.title, CHAT_G6, 12, bold=True,
                          size_hint_y=None, height=dp(18))
        text_block.add_widget(title_lbl)

        meta_parts = []
        if getattr(mission, 'mission_type', ''):
            meta_parts.append(mission.mission_type)
        priority = getattr(mission, 'priority', 'ROUTINE')
        if priority in ('PRIORITY', 'FLASH'):
            meta_parts.append(f'[{priority}]')

        if meta_parts:
            meta_color = _PRIORITY_COLOR.get(priority, CHAT_G4)
            text_block.add_widget(_lbl('  '.join(meta_parts), meta_color, 9,
                                       size_hint_y=None, height=dp(14)))
        elif mission.description:
            preview = (mission.description[:60] + '…') if len(mission.description) > 60 else mission.description
            text_block.add_widget(_lbl(preview, CHAT_G3, 9,
                                       size_hint_y=None, height=dp(14)))

        ts = datetime.datetime.fromtimestamp(mission.created_at).strftime('%Y-%m-%d %H:%M')
        text_block.add_widget(_lbl(ts, CHAT_G2, 8, size_hint_y=None, height=dp(12)))

        self.add_widget(text_block)

        # Status label (right)
        sl = _lbl(status_label, color, 9, bold=True, halign='right',
                   size_hint=(None, None), size=(dp(72), dp(68)))
        self.add_widget(sl)

        # Quick-approve button (server, pending only)
        if is_server and mission.status == 'pending_approval':
            ab = MDIconButton(
                icon='check-circle-outline',
                size_hint=(None, None), size=(dp(40), dp(40)),
                theme_icon_color='Custom', icon_color=CHAT_G5,
                md_bg_color=(0, 0, 0, 0),
            )
            ab.bind(on_release=lambda *_: on_quick_approve(mission))
            self.add_widget(ab)

    def _upd_canvas(self, *_):
        self._bg_r.pos = self.pos
        self._bg_r.size = self.size
        self._bar.pos = self.pos
        self._bar.size = (dp(3), self.height)

    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos):
            self._bg_c.rgba = CHAT_BG4
        return super().on_touch_down(touch)

    def on_touch_up(self, touch):
        result = super().on_touch_up(touch)
        is_active = self._mission.status == 'active'
        self._bg_c.rgba = CHAT_BG3 if is_active else CHAT_BG2
        return result

    def on_release(self):
        self._on_tap(self._mission)


# ---------------------------------------------------------------------------
# MissionScreen
# ---------------------------------------------------------------------------

class MissionScreen(MDScreen):

    def on_kv_post(self, base_widget) -> None:
        self._filter_index: int = 0
        self._build_layout()

    def _build_layout(self) -> None:
        self.clear_widgets()
        root = BoxLayout(orientation='vertical')
        _rgba_bg(root, CHAT_BG0)

        root.add_widget(self._make_topbar())

        body = BoxLayout(orientation='horizontal')
        content = BoxLayout(orientation='vertical')
        _rgba_bg(content, CHAT_BG0)
        content.add_widget(self._make_filter_bar())

        scroll = ScrollView(size_hint=(1, 1))
        self._mission_list = GridLayout(cols=1, size_hint_y=None, spacing=0)
        self._mission_list.bind(minimum_height=self._mission_list.setter('height'))
        scroll.add_widget(self._mission_list)
        content.add_widget(scroll)

        body.add_widget(content)
        root.add_widget(body)
        self.add_widget(root)

    def on_ui_theme_changed(self) -> None:
        self._build_layout()
        if self.manager and self.manager.current == self.name:
            self.on_pre_enter()

    # ------------------------------------------------------------------
    # Topbar
    # ------------------------------------------------------------------

    def _make_topbar(self) -> BoxLayout:
        bar = BoxLayout(
            orientation='horizontal',
            size_hint_y=None, height=dp(42),
            padding=(dp(6), 0, dp(8), 0), spacing=0,
        )
        _rgba_bg(bar, CHAT_BG1)
        _hline(bar, CHAT_BORDER, 'bottom')

        back = _btn('◀ TALON', CHAT_BG1, CHAT_G5, 11, h=42, w=80)
        back.bind(on_release=lambda _: self.on_back_pressed())
        bar.add_widget(back)

        sep = Widget(size_hint_x=None, width=dp(1))
        with sep.canvas:
            Color(*CHAT_BORDER)
            Rectangle(pos=sep.pos, size=sep.size)
        sep.bind(pos=lambda w, p: None, size=lambda w, s: None)
        bar.add_widget(sep)
        bar.add_widget(Widget(size_hint_x=None, width=dp(10)))

        title = _lbl('MISSIONS', CHAT_G6, 14, bold=True, size_hint_x=None, width=dp(120))
        bar.add_widget(title)

        bar.add_widget(Widget())  # flex spacer

        refresh_btn = MDIconButton(
            icon='refresh',
            size_hint=(None, None), size=(dp(36), dp(36)),
            theme_icon_color='Custom', icon_color=CHAT_G4,
            md_bg_color=(0, 0, 0, 0),
        )
        refresh_btn.bind(on_release=lambda _: self._load_missions())
        bar.add_widget(refresh_btn)

        bar.add_widget(Widget(size_hint_x=None, width=dp(4)))

        create_btn = _btn('+ CREATE', (*CHAT_G2[:3], 1.0), CHAT_G6, 10, h=28, w=74)
        create_btn.bind(on_release=lambda _: self.on_create_pressed())
        bar.add_widget(create_btn)

        return bar

    def _nav(self, screen: str) -> None:
        if self.manager and any(s.name == screen for s in self.manager.screens):
            self.manager.current = screen

    # ------------------------------------------------------------------
    # Filter bar
    # ------------------------------------------------------------------

    def _make_filter_bar(self) -> BoxLayout:
        bar = BoxLayout(
            orientation='horizontal',
            size_hint_y=None, height=dp(36),
            padding=(dp(10), 0, dp(10), 0), spacing=dp(8),
        )
        _rgba_bg(bar, CHAT_BG1)
        _hline(bar, CHAT_BORDER, 'bottom')

        bar.add_widget(_lbl('FILTER:', CHAT_G3, 9, bold=True,
                             size_hint=(None, 1), width=dp(52)))

        label, _ = _FILTER_OPTIONS[self._filter_index]
        self._filter_btn = _btn(f'▾ {label}', CHAT_BG3, CHAT_G5, 10, h=26, w=130)
        self._filter_btn.bind(on_release=lambda _: self._cycle_filter())
        bar.add_widget(self._filter_btn)

        bar.add_widget(Widget())

        self._count_lbl = _lbl('', CHAT_G2, 9, halign='right',
                                 size_hint=(None, 1), width=dp(80))
        bar.add_widget(self._count_lbl)
        return bar

    def _cycle_filter(self) -> None:
        self._filter_index = (self._filter_index + 1) % len(_FILTER_OPTIONS)
        label, _ = _FILTER_OPTIONS[self._filter_index]
        self._filter_btn.text = f'▾ {label}'
        self._load_missions()

    # ------------------------------------------------------------------
    # Public handlers
    # ------------------------------------------------------------------

    def on_back_pressed(self) -> None:
        self.manager.current = 'main'

    def on_create_pressed(self) -> None:
        self.manager.current = 'mission_create'

    def on_pre_enter(self, *_) -> None:
        app = App.get_running_app()
        app.clear_badge('mission')
        self._load_missions()

    # ------------------------------------------------------------------
    # Load / refresh
    # ------------------------------------------------------------------

    def _load_missions(self) -> None:
        app = App.get_running_app()
        if not hasattr(app, 'conn') or app.conn is None:
            return
        _, status_filter = _FILTER_OPTIONS[self._filter_index]
        missions = load_missions(app.conn, status_filter=status_filter)
        is_server = getattr(app, 'mode', 'client') == 'server'

        self._mission_list.clear_widgets()

        if hasattr(self, '_count_lbl'):
            active_count = sum(1 for m in missions if m.status == 'active')
            self._count_lbl.text = f'{len(missions)} TOTAL  {active_count} ACTIVE'

        if not missions:
            self._mission_list.add_widget(
                _lbl('No missions found.', CHAT_G2, 10, halign='center',
                      size_hint_y=None, height=dp(48))
            )
            return

        for mission in missions:
            self._mission_list.add_widget(_MissionRow(
                mission=mission,
                is_server=is_server,
                on_tap=self._on_row_tap,
                on_quick_approve=self._show_approve_dialog,
            ))

    # ------------------------------------------------------------------
    # Row tap
    # ------------------------------------------------------------------

    def _on_row_tap(self, mission) -> None:
        app = App.get_running_app()
        is_server = getattr(app, 'mode', 'client') == 'server'
        if is_server and mission.status == 'pending_approval':
            self._show_approve_dialog(mission)
        else:
            self._show_detail_dialog(mission)

    # ------------------------------------------------------------------
    # Approve dialog
    # ------------------------------------------------------------------

    def _show_approve_dialog(self, mission) -> None:
        app = App.get_running_app()
        if not hasattr(app, 'conn') or app.conn is None:
            return

        requested_assets = get_mission_assets(app.conn, mission.id)
        requested_ids = {a.id for a in requested_assets}
        all_assets = load_assets(app.conn)

        row = app.conn.execute(
            'SELECT callsign FROM operators WHERE id = ?', (mission.created_by,)
        ).fetchone()
        creator = row[0] if row else f'#{mission.created_by}'

        modal = ModalView(
            size_hint=(None, None), size=(dp(480), dp(560)),
            background='', background_color=(0, 0, 0, 0.7),
        )
        wrap = BoxLayout(orientation='vertical',
                         size_hint=(None, None), size=(dp(480), dp(560)))
        _rgba_bg(wrap, CHAT_BG2)

        # Header
        hdr = BoxLayout(size_hint_y=None, height=dp(40), padding=(dp(12), 0))
        _rgba_bg(hdr, CHAT_BG1)
        _hline(hdr, CHAT_BORDER, 'bottom')
        hdr.add_widget(_lbl('REVIEW MISSION', CHAT_G6, 12, bold=True))
        hdr.add_widget(Widget())
        close_x = _btn('✕', CHAT_BG1, CHAT_G3, 10, h=40, w=36)
        close_x.bind(on_release=lambda _: modal.dismiss())
        hdr.add_widget(close_x)
        wrap.add_widget(hdr)

        scroll = ScrollView(size_hint=(1, 1))
        body = GridLayout(cols=1, size_hint_y=None, padding=(dp(12), dp(8)),
                          spacing=dp(4))
        body.bind(minimum_height=body.setter('height'))

        def _info(key, val, val_color=CHAT_G4):
            row_w = BoxLayout(size_hint_y=None, height=dp(22), spacing=dp(8))
            row_w.add_widget(_lbl(key, CHAT_G3, 9, bold=True,
                                   size_hint=(None, 1), width=dp(120)))
            row_w.add_widget(_lbl(val or '—', val_color, 9))
            body.add_widget(row_w)

        _info('DESIGNATION', mission.title, CHAT_G6)
        _info('REQUESTED BY', creator)
        if mission.description:
            _info('INTENT', mission.description[:80] + ('…' if len(mission.description) > 80 else ''))

        # Asset allocation section
        _sep_hdr = BoxLayout(size_hint_y=None, height=dp(24), padding=(0, dp(4)))
        _rgba_bg(_sep_hdr, CHAT_BG1)
        _sep_hdr.add_widget(_lbl('ASSET ALLOCATION', CHAT_G4, 9, bold=True))
        body.add_widget(_sep_hdr)

        asset_checks: dict[int, MDCheckbox] = {}
        for asset in all_assets:
            if asset.mission_id is not None and asset.mission_id != mission.id:
                continue
            abbr = _CATEGORY_ABBR.get(asset.category, 'CST')
            pre_checked = asset.id in requested_ids
            ar = BoxLayout(size_hint_y=None, height=dp(30), spacing=dp(8),
                           padding=(dp(4), 0))
            chk = MDCheckbox(size_hint_x=None, width=dp(30), active=pre_checked)
            asset_checks[asset.id] = chk
            ar.add_widget(chk)
            label_text = f'[{abbr}]  {asset.label}'
            if pre_checked:
                label_text += '  ← requested'
            ar.add_widget(_lbl(label_text, CHAT_G5 if pre_checked else CHAT_G4, 10))
            body.add_widget(ar)

        if not all_assets:
            body.add_widget(_lbl('No assets in database.', CHAT_G2, 10,
                                  size_hint_y=None, height=dp(28)))

        scroll.add_widget(body)
        wrap.add_widget(scroll)

        # Footer buttons
        foot = BoxLayout(size_hint_y=None, height=dp(48),
                         padding=(dp(12), dp(8)), spacing=dp(8))
        _rgba_bg(foot, CHAT_BG1)
        _hline(foot, CHAT_BORDER, 'top')

        cancel_btn = _btn('CANCEL', CHAT_BG3, CHAT_G3, 10, h=32, w=80)
        cancel_btn.bind(on_release=lambda _: modal.dismiss())

        reject_btn = _btn('REJECT', (*CHAT_RED[:3], 1.0), CHAT_G6, 10, h=32, w=80)
        reject_btn.bind(on_release=lambda _: self._do_reject_mission(modal, mission.id))

        approve_btn = _btn('APPROVE', (*CHAT_G3[:3], 1.0), CHAT_G6, 11, h=32, w=90)
        approve_btn.bold = True
        approve_btn.bind(on_release=lambda _: self._do_approve_mission(modal, mission.id, asset_checks))

        foot.add_widget(cancel_btn)
        foot.add_widget(Widget())
        foot.add_widget(reject_btn)
        foot.add_widget(approve_btn)
        wrap.add_widget(foot)

        modal.add_widget(wrap)
        modal.open()

    def _do_approve_mission(self, modal, mission_id, asset_checks):
        app = App.get_running_app()
        approved_ids = [aid for aid, chk in asset_checks.items() if chk.active]
        try:
            result = approve_mission_command(app.conn, mission_id, asset_ids=approved_ids)
        except ValueError as exc:
            self._show_error_dialog(str(exc))
            return
        app.dispatch_domain_events(result.events)
        modal.dismiss()
        self._load_missions()

    def _do_reject_mission(self, modal, mission_id):
        app = App.get_running_app()
        try:
            result = reject_mission_command(app.conn, mission_id)
        except ValueError as exc:
            self._show_error_dialog(str(exc))
            return
        app.dispatch_domain_events(result.events)
        modal.dismiss()
        self._load_missions()

    # ------------------------------------------------------------------
    # Detail dialog
    # ------------------------------------------------------------------

    def _show_detail_dialog(self, mission) -> None:
        app = App.get_running_app()
        if not hasattr(app, 'conn') or app.conn is None:
            return
        is_server = getattr(app, 'mode', 'client') == 'server'

        row = app.conn.execute(
            'SELECT callsign FROM operators WHERE id = ?', (mission.created_by,)
        ).fetchone()
        creator = row[0] if row else f'#{mission.created_by}'

        mission_assets  = get_mission_assets(app.conn, mission.id)
        channel_name    = get_channel_for_mission(app.conn, mission.id) or ''
        mission_zones   = load_zones(app.conn, mission_id=mission.id)
        ao_zones        = [z for z in mission_zones if z.zone_type == 'AO']
        mission_wps     = load_waypoints(app.conn, mission.id)
        db_key          = getattr(app, 'db_key', None)
        mission_sitreps = load_sitreps(app.conn, db_key, mission_id=mission.id) if db_key else []

        color        = _STATUS_COLOR.get(mission.status, CHAT_G2)
        status_label = _STATUS_LABEL.get(mission.status, mission.status.upper())

        modal = ModalView(
            size_hint=(None, None), size=(dp(520), dp(600)),
            background='', background_color=(0, 0, 0, 0.7),
        )
        wrap = BoxLayout(orientation='vertical',
                         size_hint=(None, None), size=(dp(520), dp(600)))
        _rgba_bg(wrap, CHAT_BG2)

        # Header
        hdr = BoxLayout(size_hint_y=None, height=dp(40), padding=(dp(12), 0),
                        spacing=dp(8))
        _rgba_bg(hdr, CHAT_BG1)
        _hline(hdr, CHAT_BORDER, 'bottom')
        hdr.add_widget(_lbl(mission.title.upper(), CHAT_G6, 13, bold=True))
        hdr.add_widget(Widget())
        hdr.add_widget(_lbl(status_label, color, 9, bold=True,
                             size_hint=(None, 1), width=dp(72), halign='right'))
        close_x = _btn('✕', CHAT_BG1, CHAT_G3, 10, h=40, w=36)
        close_x.bind(on_release=lambda _: modal.dismiss())
        hdr.add_widget(close_x)
        wrap.add_widget(hdr)

        scroll = ScrollView(size_hint=(1, 1))
        body = GridLayout(cols=1, size_hint_y=None, padding=(dp(12), dp(8)),
                          spacing=dp(3))
        body.bind(minimum_height=body.setter('height'))

        def _info(key, val, val_color=CHAT_G4):
            if not val:
                return
            r = BoxLayout(size_hint_y=None, height=dp(20), spacing=dp(8))
            r.add_widget(_lbl(key, CHAT_G3, 9, bold=True,
                               size_hint=(None, 1), width=dp(130)))
            r.add_widget(_lbl(str(val), val_color, 9))
            body.add_widget(r)

        def _section(title):
            sh = BoxLayout(size_hint_y=None, height=dp(22), padding=(0, dp(2)))
            _rgba_bg(sh, CHAT_BG1)
            sh.add_widget(_lbl(title, CHAT_G4, 9, bold=True))
            body.add_widget(sh)

        _info('CREATED BY', creator)
        _info('CREATED', datetime.datetime.fromtimestamp(mission.created_at).strftime('%Y-%m-%d %H:%M'))
        _info('TYPE', getattr(mission, 'mission_type', ''))
        priority = getattr(mission, 'priority', '')
        _info('PRIORITY', priority, _PRIORITY_COLOR.get(priority, CHAT_G4))
        _info('LEAD COORD', getattr(mission, 'lead_coordinator', ''))
        _info('ORGANIZATION', getattr(mission, 'organization', ''))
        _info('ACTIVATION', getattr(mission, 'activation_time', ''))
        _info('WINDOW', getattr(mission, 'operation_window', ''))
        constraints = getattr(mission, 'constraints', [])
        if constraints:
            _info('CONSTRAINTS', ', '.join(constraints))

        resource_rows = [
            ('MEDICAL', getattr(mission, 'support_medical', '')),
            ('LOGISTICS', getattr(mission, 'support_logistics', '')),
            ('COMMS', getattr(mission, 'support_comms', '')),
            ('EQUIPMENT', getattr(mission, 'support_equipment', '')),
        ]
        custom_resources = getattr(mission, 'custom_resources', [])
        if any(val for _, val in resource_rows) or custom_resources:
            _section('SUPPORT RESOURCES')
            for key, val in resource_rows:
                _info(key, val)
            for resource in custom_resources:
                if not isinstance(resource, dict):
                    continue
                label = str(resource.get('label') or 'CUSTOM RESOURCE').upper()
                details = str(resource.get('details') or '')
                _info(label, details or 'Defined')

        key_locations = getattr(mission, 'key_locations', {})
        if isinstance(key_locations, dict) and any(key_locations.values()):
            _section('KEY LOCATIONS')
            for key, val in key_locations.items():
                if val:
                    _info(str(key).replace('_', ' ').upper(), val)

        phases = getattr(mission, 'phases', [])
        if phases:
            _section(f'PHASES ({len(phases)})')
            for i, ph in enumerate(phases):
                name = ph.get('name') or f'Phase {i + 1}'
                end = ph.get('objective', '')
                dur = ph.get('duration', '')
                line = f'  {i + 1}. {name}'
                if end: line += f'  —  {end}'
                if dur: line += f'  ({dur})'
                body.add_widget(_lbl(line, CHAT_G3, 9,
                                      size_hint_y=None, height=dp(18)))

        objectives = getattr(mission, 'objectives', [])
        if objectives:
            _section(f'OBJECTIVES ({len(objectives)})')
            for i, obj in enumerate(objectives):
                label = obj.get('label') or ('PRIMARY OBJ' if i == 0 else f'OBJ {i+1}')
                criteria = obj.get('criteria', '')
                line = f"  {'▶' if i == 0 else '◦'}  {label}"
                if criteria: line += f'  —  {criteria[:55]}'
                body.add_widget(_lbl(line, CHAT_G4 if i == 0 else CHAT_G3, 9,
                                      size_hint_y=None, height=dp(18)))

        if mission.description:
            _section('DESCRIPTION')
            dl = Label(
                text=mission.description, color=CHAT_G3,
                font_size=dp(9), halign='left', valign='top',
                size_hint_y=None,
            )
            dl.bind(
                width=lambda w, _: setattr(w, 'text_size', (w.width, None)),
                texture_size=lambda w, ts: setattr(w, 'height', ts[1]),
            )
            body.add_widget(dl)

        if mission_assets:
            _section(f'ASSETS ({len(mission_assets)})')
            for a in mission_assets:
                abbr = _CATEGORY_ABBR.get(a.category, 'CST')
                body.add_widget(_lbl(f'  [{abbr}]  {a.label}', CHAT_G4, 9,
                                      size_hint_y=None, height=dp(18)))

        if ao_zones:
            _info('MISSION AREA', f'AO polygon  ({len(ao_zones[0].polygon)} vertices)')

        if mission_wps:
            _section(f'ROUTE ({len(mission_wps)} waypoints)')
            for wp in mission_wps:
                body.add_widget(_lbl(
                    f'  W{wp.sequence}  {wp.label}   {wp.lat:.5f}, {wp.lon:.5f}',
                    CHAT_G3, 9, size_hint_y=None, height=dp(18)
                ))

        if mission_sitreps:
            _section(f'SITREPS ({len(mission_sitreps)})')
            for sitrep, callsign, _ in mission_sitreps:
                body_text = sitrep.body.decode('utf-8', errors='replace') if isinstance(sitrep.body, bytes) else str(sitrep.body)
                preview = (body_text[:55] + '…') if len(body_text) > 55 else body_text
                ts = datetime.datetime.fromtimestamp(sitrep.created_at).strftime('%m-%d %H:%M')
                body.add_widget(_lbl(
                    f'  [{sitrep.level}]  {callsign}  {ts}  —  {preview}',
                    CHAT_G3, 9, size_hint_y=None, height=dp(18)
                ))

        if channel_name:
            _info('CHANNEL', channel_name)

        scroll.add_widget(body)
        wrap.add_widget(scroll)

        # Footer buttons
        foot = BoxLayout(size_hint_y=None, height=dp(48),
                         padding=(dp(12), dp(8)), spacing=dp(8))
        _rgba_bg(foot, CHAT_BG1)
        _hline(foot, CHAT_BORDER, 'top')

        close_btn = _btn('CLOSE', CHAT_BG3, CHAT_G3, 10, h=32, w=70)
        close_btn.bind(on_release=lambda _: modal.dismiss())
        foot.add_widget(close_btn)
        foot.add_widget(Widget())

        if is_server:
            if mission.status == 'active':
                cb = _btn('COMPLETE', (*CHAT_G3[:3], 1.0), CHAT_G6, 10, h=32, w=88)
                cb.bind(on_release=lambda _: self._do_complete_mission(modal, mission.id))
                foot.add_widget(cb)
            if mission.status in ('pending_approval', 'active'):
                ab = _btn('ABORT', (*CHAT_AMBER[:3], 1.0), CHAT_G6, 10, h=32, w=70)
                ab.bind(on_release=lambda _: self._confirm_abort(modal, mission.id))
                foot.add_widget(ab)
            db = _btn('DELETE', (*CHAT_RED[:3], 1.0), CHAT_G6, 10, h=32, w=70)
            db.bind(on_release=lambda _: self._confirm_delete(modal, mission.id))
            foot.add_widget(db)

        wrap.add_widget(foot)
        modal.add_widget(wrap)
        modal.open()

    def _do_complete_mission(self, detail_modal, mission_id):
        app = App.get_running_app()
        try:
            result = complete_mission_command(app.conn, mission_id)
        except ValueError as exc:
            self._show_error_dialog(str(exc))
            return
        app.dispatch_domain_events(result.events)
        detail_modal.dismiss()
        self._load_missions()

    def _confirm_abort(self, detail_modal, mission_id):
        self._show_confirm(
            'Abort this mission?\nAllocated assets will be released.',
            'ABORT',
            lambda: self._do_abort_mission(detail_modal, mission_id),
        )

    def _do_abort_mission(self, detail_modal, mission_id):
        app = App.get_running_app()
        try:
            result = abort_mission_command(app.conn, mission_id)
        except ValueError as exc:
            self._show_error_dialog(str(exc))
            return
        app.dispatch_domain_events(result.events)
        detail_modal.dismiss()
        self._load_missions()

    def _confirm_delete(self, detail_modal, mission_id):
        self._show_confirm(
            'Permanently delete this mission?\nAll linked data will be unlinked.\nThis cannot be undone.',
            'DELETE',
            lambda: self._do_delete_mission(detail_modal, mission_id),
        )

    def _do_delete_mission(self, detail_modal, mission_id):
        app = App.get_running_app()
        if app.conn is None:
            return
        try:
            result = delete_mission_command(app.conn, mission_id)
        except ValueError as exc:
            self._show_error_dialog(str(exc))
            return

        app.dispatch_domain_events(result.events)
        detail_modal.dismiss()
        self._load_missions()

    # ------------------------------------------------------------------
    # Generic confirm / error modals
    # ------------------------------------------------------------------

    def _show_confirm(self, message: str, action_label: str, on_confirm) -> None:
        modal = ModalView(
            size_hint=(None, None), size=(dp(360), dp(180)),
            background='', background_color=(0, 0, 0, 0.7),
        )
        wrap = BoxLayout(orientation='vertical',
                         size_hint=(None, None), size=(dp(360), dp(180)))
        _rgba_bg(wrap, CHAT_BG2)

        msg_lbl = Label(
            text=message, color=CHAT_G4, font_size=dp(10),
            halign='center', valign='middle',
            size_hint=(1, 1),
        )
        msg_lbl.bind(size=msg_lbl.setter('text_size'))
        wrap.add_widget(msg_lbl)

        foot = BoxLayout(size_hint_y=None, height=dp(44),
                         padding=(dp(12), dp(6)), spacing=dp(8))
        _rgba_bg(foot, CHAT_BG1)
        _hline(foot, CHAT_BORDER, 'top')

        cancel_btn = _btn('CANCEL', CHAT_BG3, CHAT_G3, 10, h=32, w=80)
        cancel_btn.bind(on_release=lambda _: modal.dismiss())
        action_btn = _btn(action_label, (*CHAT_RED[:3], 1.0), CHAT_G6, 10, h=32, w=90)
        action_btn.bind(on_release=lambda _: (modal.dismiss(), on_confirm()))

        foot.add_widget(Widget())
        foot.add_widget(cancel_btn)
        foot.add_widget(action_btn)
        wrap.add_widget(foot)
        modal.add_widget(wrap)
        modal.open()

    def _show_error_dialog(self, message: str) -> None:
        modal = ModalView(
            size_hint=(None, None), size=(dp(340), dp(140)),
            background='', background_color=(0, 0, 0, 0.7),
        )
        wrap = BoxLayout(orientation='vertical',
                         size_hint=(None, None), size=(dp(340), dp(140)))
        _rgba_bg(wrap, CHAT_BG2)

        msg_lbl = Label(text=message, color=CHAT_RED2, font_size=dp(10),
                        halign='center', valign='middle', size_hint=(1, 1))
        msg_lbl.bind(size=msg_lbl.setter('text_size'))
        wrap.add_widget(msg_lbl)

        foot = BoxLayout(size_hint_y=None, height=dp(40),
                         padding=(dp(12), dp(4)))
        _rgba_bg(foot, CHAT_BG1)
        ok_btn = _btn('OK', CHAT_BG3, CHAT_G4, 10, h=28, w=60)
        ok_btn.bind(on_release=lambda _: modal.dismiss())
        foot.add_widget(Widget())
        foot.add_widget(ok_btn)
        wrap.add_widget(foot)
        modal.add_widget(wrap)
        modal.open()
