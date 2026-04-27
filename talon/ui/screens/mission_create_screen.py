"""
MissionCreateScreen — five-step OPORD-style wizard for creating a new mission.
Layout built entirely in Python; mission_create.kv is a minimal registration stub.

Steps:
  1. Parameters  — designation, type, priority, intent, coordinator, constraints
  2. Timeline    — activation time, phases, staging/demob locations
  3. Assets      — assign from available pool + supporting resources
  4. Objectives  — primary/secondary objectives, AO polygon, route, key locations
  5. Review      — read-back and submit
"""
import calendar as _calendar
import datetime
import typing

from kivy.app import App
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
from kivymd.uix.button import MDIconButton
from kivymd.uix.screen import MDScreen

from talon.ui.font_scale import get_font_scale
from talon.ui.theme import (
    CHAT_AMBER, CHAT_AMBER2, CHAT_BG0, CHAT_BG1, CHAT_BG2, CHAT_BG3, CHAT_BG4,
    CHAT_BORDER, CHAT_G1, CHAT_G2, CHAT_G3, CHAT_G4, CHAT_G5, CHAT_G6,
    CHAT_RED, CHAT_RED2,
)
from talon.ui.widgets.map_draw import (
    CATEGORY_ABBR,
    PointPickerModal,
    PolygonDrawModal,
    WaypointRouteModal,
)

def _fs(base: float) -> float:
    return dp(base * get_font_scale())


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MISSION_TYPES: tuple[str, ...] = (
    "SEARCH & RESCUE",
    "DEBRIS CLEARANCE",
    "MEDICAL AID",
    "SUPPLY DISTRIBUTION",
    "ROUTE SURVEY",
    "SHELTER SETUP",
    "WELFARE CHECK",
    "HAZMAT RESPONSE",
    "EVACUATION SUPPORT",
)

OPERATING_CONSTRAINTS: tuple[str, ...] = (
    "STRUCTURAL ENTRY AUTHORIZED",
    "HAZMAT CERTIFIED ONLY",
    "MEDIA BLACKOUT",
    "ANIMAL RESCUE PROTOCOL",
    "WATER RESCUE PROTOCOL",
    "HEAVY EQUIPMENT REQUIRED",
)

RESOURCE_FIELDS: tuple[tuple[str, str, str, str], ...] = (
    ('support_medical',   'Medical',   'Medical team / resources (e.g. two EMTs on standby)', '_f_medical'),
    ('support_logistics', 'Logistics', 'Logistics / supply chain',                             '_f_logistics'),
    ('support_comms',     'Comms',     'Communications support (e.g. HAM relay)',              '_f_comms'),
    ('support_equipment', 'Equipment', 'Heavy or specialized equipment',                       '_f_equipment'),
)

KEY_LOCATION_FIELDS: tuple[tuple[str, str, str, str], ...] = (
    ('medical_station', 'Medical Station', 'Medical station address or coordinates', '_f_medical_loc'),
    ('alt_route',       'Alternate Route', 'Alternate route description',            '_f_alt_route'),
    ('demob_loc',       'Demob Location',  'Demobilization point',                   '_f_demob_loc'),
)

STEPS: tuple[tuple[str, str], ...] = (
    ("PARAMETERS",  "Type, priority, intent, constraints"),
    ("TIMELINE",    "Activation time, phases, locations"),
    ("ASSETS",      "Assigned elements & support"),
    ("OBJECTIVES",  "AO, waypoints, key locations"),
    ("REVIEW",      "Confirm and submit"),
)

ASSET_GROUP_ORDER: tuple[str, ...] = (
    "person", "vehicle", "safe_house", "cache", "rally_point", "custom"
)
ASSET_GROUP_LABELS: dict[str, str] = {
    "person":      "PEOPLE",
    "safe_house":  "SAFE HOUSES",
    "cache":       "CACHES",
    "rally_point": "RALLY POINTS",
    "vehicle":     "VEHICLES",
    "custom":      "CUSTOM",
}

_PRIORITY_BG: dict[str, tuple] = {
    "ROUTINE":  (*CHAT_G2[:3], 1.0),
    "PRIORITY": (*CHAT_AMBER[:3], 1.0),
    "FLASH":    (*CHAT_RED[:3], 1.0),
}
_PRIORITY_FG: dict[str, tuple] = {
    "ROUTINE":  CHAT_G6,
    "PRIORITY": CHAT_G6,
    "FLASH":    CHAT_G6,
}


# ---------------------------------------------------------------------------
# Canvas helpers
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


def _lbl(text, color=CHAT_G4, fsize=10, bold=False, halign='left', **kw):
    l = Label(text=text, color=color, font_size=_fs(fsize), bold=bold,
              halign=halign, valign='middle', **kw)
    l.bind(size=l.setter('text_size'))
    return l


def _btn(text, bg=CHAT_BG3, fg=CHAT_G4, size=10, h=28, w=None, bold=False, **kw):
    b = Button(
        text=text, color=fg, font_size=_fs(size), bold=bold,
        background_normal='', background_color=bg,
        size_hint_y=None, height=dp(h), **kw,
    )
    if w is not None:
        b.size_hint_x = None
        b.width = dp(w)
    return b


def _text_input(hint: str, multiline: bool = False, height: int = 32) -> TextInput:
    ti = TextInput(
        hint_text=hint,
        hint_text_color=CHAT_G2,
        foreground_color=CHAT_G5,
        background_color=CHAT_BG3,
        cursor_color=CHAT_G5,
        font_size=_fs(10),
        multiline=multiline,
        size_hint_y=None,
        height=dp(height if multiline else height),
        padding=(dp(6), dp(4)),
    )
    return ti


def _section_hdr(num: str, title: str) -> BoxLayout:
    row = BoxLayout(size_hint_y=None, height=dp(28), spacing=dp(8), padding=(0, dp(2)))
    _rgba_bg(row, CHAT_BG1)
    _hline(row, CHAT_BORDER, 'bottom')
    row.add_widget(_lbl(num, CHAT_G3, 9, bold=True,
                         size_hint=(None, 1), width=dp(24), halign='right'))
    row.add_widget(_lbl(title, CHAT_G5, 11, bold=True))
    return row


def _field_label(text: str, required: bool = False) -> Label:
    return _lbl(
        text + (' *' if required else ''),
        CHAT_G3, 9, bold=True,
        size_hint_y=None, height=dp(18),
    )


def _compact_text(value: str) -> str:
    return ' '.join((value or '').strip().split())


def _normalise_option(value: str) -> str:
    return _compact_text(value).upper()


def _format_location_key(key: str) -> str:
    return _compact_text(str(key).replace('_', ' ')).upper()


# ---------------------------------------------------------------------------
# Toggle tile (mission type / priority / constraint)
# ---------------------------------------------------------------------------

class _ToggleTile(ButtonBehavior, BoxLayout):
    def __init__(self, label: str, on_toggle: typing.Callable,
                 active: bool = False, **kwargs):
        super().__init__(
            orientation='horizontal',
            size_hint_y=None, height=dp(36),
            spacing=dp(6), padding=(dp(8), dp(4)),
            **kwargs,
        )
        self._label_text = label
        self._on_toggle = on_toggle
        self._active = active

        with self.canvas.before:
            self._bg_c = Color(*(CHAT_BG4 if active else CHAT_BG2))
            self._bg_r = Rectangle(pos=self.pos, size=self.size)
            Color(*CHAT_BORDER)
            self._border = Line(rectangle=(self.x, self.y, self.width, self.height), width=1)
        self.bind(pos=self._upd, size=self._upd)

        self._dot = Widget(size_hint=(None, None), size=(dp(6), dp(6)))
        with self._dot.canvas:
            self._dot_c = Color(*(CHAT_G5 if active else CHAT_G2))
            self._dot_r = Rectangle(pos=self._dot.pos, size=self._dot.size)
        self._dot.bind(
            pos=lambda w, p: setattr(self._dot_r, 'pos', p),
            size=lambda w, s: setattr(self._dot_r, 'size', s),
        )

        self._lbl = _lbl(label, CHAT_G5 if active else CHAT_G3, 9, bold=active)
        self.add_widget(self._dot)
        self.add_widget(self._lbl)

    def _upd(self, *_):
        self._bg_r.pos = self.pos
        self._bg_r.size = self.size
        self._border.rectangle = (self.x, self.y, self.width, self.height)

    def _refresh(self) -> None:
        self._bg_c.rgba = CHAT_BG4 if self._active else CHAT_BG2
        self._dot_c.rgba = CHAT_G5 if self._active else CHAT_G2
        self._lbl.color = CHAT_G5 if self._active else CHAT_G3
        self._lbl.bold = self._active

    def on_release(self) -> None:
        self._active = not self._active
        self._refresh()
        self._on_toggle(self._label_text, self._active)

    def set_active(self, active: bool) -> None:
        self._active = active
        self._refresh()

    @property
    def active(self) -> bool:
        return self._active


# ---------------------------------------------------------------------------
# Phase row
# ---------------------------------------------------------------------------

class _PhaseRow(BoxLayout):
    def __init__(self, index: int, on_remove: typing.Callable, **kwargs):
        super().__init__(
            orientation='horizontal',
            size_hint_y=None, height=dp(40),
            spacing=dp(6), padding=(dp(4), dp(4)),
            **kwargs,
        )
        _rgba_bg(self, CHAT_BG2)
        _hline(self, CHAT_BORDER, 'bottom')

        badge = _lbl(str(index + 1), CHAT_G3, 9, bold=True,
                      size_hint=(None, 1), width=dp(20), halign='right')
        self.name_field = _text_input(f'Phase {index + 1} name')
        self.objective_field = _text_input('End state / objective')
        self.duration_field = _text_input('Duration', height=32)
        self.duration_field.size_hint_x = None
        self.duration_field.width = dp(90)

        rm = MDIconButton(
            icon='close-circle-outline',
            size_hint=(None, None), size=(dp(32), dp(32)),
            theme_icon_color='Custom', icon_color=CHAT_G3,
            md_bg_color=(0, 0, 0, 0),
        )
        rm.bind(on_release=lambda *_: on_remove(self))

        self.add_widget(badge)
        self.add_widget(self.name_field)
        self.add_widget(self.objective_field)
        self.add_widget(self.duration_field)
        self.add_widget(rm)

    def get_data(self) -> dict:
        return {
            'name': self.name_field.text.strip(),
            'objective': self.objective_field.text.strip(),
            'duration': self.duration_field.text.strip(),
        }


# ---------------------------------------------------------------------------
# Objective card
# ---------------------------------------------------------------------------

class _ObjectiveCard(BoxLayout):
    def __init__(self, index: int,
                 on_remove: typing.Optional[typing.Callable] = None, **kwargs):
        super().__init__(
            orientation='vertical',
            size_hint_y=None, height=dp(130),
            spacing=dp(4), padding=(dp(8), dp(6)),
            **kwargs,
        )
        _rgba_bg(self, CHAT_BG2)
        _hline(self, CHAT_BORDER, 'bottom')

        is_primary = (index == 0)
        badge_color = CHAT_G5 if is_primary else CHAT_G4
        badge_text  = 'PRIMARY OBJ' if is_primary else f'OBJ {index + 1}'

        head = BoxLayout(size_hint_y=None, height=dp(22), spacing=dp(6))
        head.add_widget(_lbl(badge_text, badge_color, 9, bold=True))
        if on_remove:
            rm = MDIconButton(
                icon='close', size_hint=(None, None), size=(dp(28), dp(28)),
                theme_icon_color='Custom', icon_color=CHAT_G3,
                md_bg_color=(0, 0, 0, 0),
            )
            rm.bind(on_release=lambda *_: on_remove(self))
            head.add_widget(Widget())
            head.add_widget(rm)
        self.add_widget(head)

        row1 = BoxLayout(size_hint_y=None, height=dp(32), spacing=dp(6))
        self.label_field = _text_input('Objective designation (e.g. OBJ ALPHA)')
        self.phase_field  = _text_input('Phase link')
        self.phase_field.size_hint_x = None
        self.phase_field.width = dp(90)
        row1.add_widget(self.label_field)
        row1.add_widget(self.phase_field)
        self.add_widget(row1)

        self.criteria_field = _text_input('Success criteria / end state',
                                          multiline=True, height=48)
        self.add_widget(self.criteria_field)

    def get_data(self) -> dict:
        return {
            'label':    self.label_field.text.strip(),
            'phase':    self.phase_field.text.strip(),
            'criteria': self.criteria_field.text.strip(),
        }


# ---------------------------------------------------------------------------
# Custom label/details row
# ---------------------------------------------------------------------------

class _CustomPairRow(BoxLayout):
    def __init__(
        self,
        label_hint: str,
        value_hint: str,
        on_remove: typing.Callable,
        *,
        value_key: str = 'details',
        **kwargs,
    ):
        super().__init__(
            orientation='horizontal',
            size_hint_y=None, height=dp(40),
            spacing=dp(6), padding=(dp(4), dp(4)),
            **kwargs,
        )
        self._value_key = value_key
        _rgba_bg(self, CHAT_BG2)
        _hline(self, CHAT_BORDER, 'bottom')

        self.label_field = _text_input(label_hint)
        self.label_field.size_hint_x = None
        self.label_field.width = dp(150)
        self.value_field = _text_input(value_hint)

        rm = MDIconButton(
            icon='close-circle-outline',
            size_hint=(None, None), size=(dp(32), dp(32)),
            theme_icon_color='Custom', icon_color=CHAT_G3,
            md_bg_color=(0, 0, 0, 0),
        )
        rm.bind(on_release=lambda *_: on_remove(self))

        self.add_widget(self.label_field)
        self.add_widget(self.value_field)
        self.add_widget(rm)

    def get_data(self) -> dict:
        label = _compact_text(self.label_field.text)
        value = _compact_text(self.value_field.text)
        return {
            'label': label,
            self._value_key: value,
        }


# ---------------------------------------------------------------------------
# MissionCreateScreen
# ---------------------------------------------------------------------------

class MissionCreateScreen(MDScreen):

    def on_kv_post(self, base_widget) -> None:
        self._step = 0
        self._data: dict = {}
        self._phase_rows: list[_PhaseRow] = []
        self._asset_checks: dict[int, _ToggleTile] = {}
        self._selected_asset_ids: list[int] = []
        self._constraint_tiles: list[_ToggleTile] = []
        self._objective_cards: list[_ObjectiveCard] = []
        self._ao_polygon: list[list[float]] = []
        self._route: list[tuple[float, float]] = []
        self._priority_selector: typing.Optional['_PrioritySelector'] = None
        self._mission_type_tiles: list[_ToggleTile] = []
        self._selected_mission_type: str = ''
        self._custom_resource_rows: list[_CustomPairRow] = []
        self._custom_key_location_rows: list[_CustomPairRow] = []
        self._build_layout()

    def on_pre_enter(self, *_) -> None:
        self._step = 0
        self._data = {}
        self._phase_rows = []
        self._asset_checks = {}
        self._selected_asset_ids = []
        self._constraint_tiles = []
        self._objective_cards = []
        self._ao_polygon = []
        self._route = []
        self._selected_mission_type = ''
        self._custom_resource_rows = []
        self._custom_key_location_rows = []
        self._build_step(0)
        self._refresh_footer()
        self._refresh_sidebar()
        self._refresh_summary()

    # ------------------------------------------------------------------
    # Layout construction
    # ------------------------------------------------------------------

    def _build_layout(self) -> None:
        # Clear any previous layout (re-entry)
        self.clear_widgets()

        root = BoxLayout(orientation='vertical')
        _rgba_bg(root, CHAT_BG0)

        root.add_widget(self._make_topbar())

        body = BoxLayout(orientation='horizontal')

        # Left sidebar
        sidebar = BoxLayout(orientation='vertical',
                            size_hint_x=None, width=dp(200))
        _rgba_bg(sidebar, CHAT_BG1)
        _vline(sidebar, CHAT_BORDER, 'right')

        self._step_list = GridLayout(cols=1, size_hint_y=None, spacing=0)
        self._step_list.bind(minimum_height=self._step_list.setter('height'))
        sidebar_scroll = ScrollView(size_hint=(1, None), height=dp(240))
        sidebar_scroll.add_widget(self._step_list)
        sidebar.add_widget(sidebar_scroll)

        sidebar.add_widget(Widget())  # spacer

        summary_wrap = BoxLayout(orientation='vertical', size_hint_y=None,
                                  height=dp(160), padding=(dp(8), dp(8)),
                                  spacing=dp(2))
        _rgba_bg(summary_wrap, CHAT_BG1)
        _hline(summary_wrap, CHAT_BORDER, 'top')
        self._summary_pane = summary_wrap
        sidebar.add_widget(summary_wrap)

        body.add_widget(sidebar)

        # Main scrollable content
        content_wrap = BoxLayout(orientation='vertical')
        _rgba_bg(content_wrap, CHAT_BG0)

        main_scroll = ScrollView(size_hint=(1, 1))
        self._step_content = GridLayout(cols=1, size_hint_y=None,
                                         padding=(dp(20), dp(16)), spacing=dp(14))
        self._step_content.bind(minimum_height=self._step_content.setter('height'))
        main_scroll.add_widget(self._step_content)
        content_wrap.add_widget(main_scroll)

        body.add_widget(content_wrap)
        root.add_widget(body)
        root.add_widget(self._make_footer())
        self.add_widget(root)

        self._build_sidebar()
        self._build_step(0)
        self._refresh_footer()
        self._refresh_summary()

    def on_ui_theme_changed(self) -> None:
        self._build_layout()

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

        back = _btn('◀ MISSIONS', CHAT_BG1, CHAT_G5, 11, h=42, w=94)
        back.bind(on_release=lambda _: self.on_back_pressed())
        bar.add_widget(back)

        sep = Widget(size_hint_x=None, width=dp(1))
        with sep.canvas:
            Color(*CHAT_BORDER)
            r = Rectangle(pos=sep.pos, size=sep.size)
        sep.bind(pos=lambda w, p: setattr(r, 'pos', p),
                 size=lambda w, s: setattr(r, 'size', s))
        bar.add_widget(sep)
        bar.add_widget(Widget(size_hint_x=None, width=dp(10)))

        bar.add_widget(_lbl('CREATE MISSION', CHAT_G6, 14, bold=True,
                              size_hint_x=None, width=dp(160)))
        bar.add_widget(Widget())

        self._step_indicator = _lbl('Step 1 of 5', CHAT_G3, 9, halign='right',
                                     size_hint=(None, 1), width=dp(90))
        bar.add_widget(self._step_indicator)
        return bar

    # ------------------------------------------------------------------
    # Footer
    # ------------------------------------------------------------------

    def _make_footer(self) -> BoxLayout:
        foot = BoxLayout(
            orientation='horizontal',
            size_hint_y=None, height=dp(48),
            padding=(dp(12), dp(8)), spacing=dp(8),
        )
        _rgba_bg(foot, CHAT_BG1)
        _hline(foot, CHAT_BORDER, 'top')

        # Progress segments
        self._prog_segs: list[Widget] = []
        prog_row = BoxLayout(size_hint=(None, None), size=(dp(120), dp(4)),
                              spacing=dp(3))
        for _ in STEPS:
            seg = Widget(size_hint=(1, None), height=dp(4))
            with seg.canvas.before:
                seg._c = Color(*CHAT_G1)
                seg._r = Rectangle(pos=seg.pos, size=seg.size)
            seg.bind(pos=lambda w, _: setattr(w._r, 'pos', w.pos),
                     size=lambda w, _: setattr(w._r, 'size', w.size))
            self._prog_segs.append(seg)
            prog_row.add_widget(seg)

        foot.add_widget(prog_row)
        foot.add_widget(Widget(size_hint_x=None, width=dp(8)))

        self._footer_label = _lbl('STEP 1 OF 5 — PARAMETERS', CHAT_G3, 9,
                                    size_hint_x=None, width=dp(200))
        foot.add_widget(self._footer_label)
        foot.add_widget(Widget())

        self._back_btn = _btn('← BACK', CHAT_BG3, CHAT_G3, 10, h=32, w=88)
        self._back_btn.bind(on_release=lambda _: self.on_back_step())
        foot.add_widget(self._back_btn)

        self._next_btn = _btn('NEXT →', (*CHAT_G3[:3], 1.0), CHAT_G6, 11, h=32, w=110, bold=True)
        self._next_btn.bind(on_release=lambda _: self.on_next_step())
        foot.add_widget(self._next_btn)

        return foot

    # ------------------------------------------------------------------
    # Sidebar
    # ------------------------------------------------------------------

    def _build_sidebar(self) -> None:
        self._step_list.clear_widgets()
        self._step_items: list[BoxLayout] = []
        for i, (name, desc) in enumerate(STEPS):
            item = BoxLayout(
                orientation='horizontal',
                size_hint_y=None, height=dp(52),
                spacing=dp(8), padding=(dp(8), dp(6)),
            )
            _rgba_bg(item, CHAT_BG1)
            if i < len(STEPS) - 1:
                _hline(item, CHAT_BORDER, 'bottom')

            num_lbl = _lbl(str(i + 1), CHAT_G3, 10, bold=True,
                            size_hint=(None, 1), width=dp(18), halign='right')
            text_col = BoxLayout(orientation='vertical', spacing=dp(1))
            name_lbl = _lbl(name, CHAT_G4, 10, bold=True,
                              size_hint_y=None, height=dp(18))
            desc_lbl = _lbl(desc, CHAT_G2, 8, size_hint_y=None, height=dp(14))
            text_col.add_widget(name_lbl)
            text_col.add_widget(desc_lbl)

            item.add_widget(num_lbl)
            item.add_widget(text_col)
            item._name_lbl = name_lbl
            item._num_lbl  = num_lbl
            self._step_items.append(item)
            self._step_list.add_widget(item)

    def _refresh_sidebar(self) -> None:
        for i, item in enumerate(self._step_items):
            if i == self._step:
                item._name_lbl.color = CHAT_G6
                item._name_lbl.bold  = True
                item._num_lbl.color  = CHAT_G5
            elif i < self._step:
                item._name_lbl.color = CHAT_G4
                item._name_lbl.bold  = False
                item._num_lbl.color  = CHAT_G3
            else:
                item._name_lbl.color = CHAT_G2
                item._name_lbl.bold  = False
                item._num_lbl.color  = CHAT_G1

    # ------------------------------------------------------------------
    # Progress bar + footer label
    # ------------------------------------------------------------------

    def _refresh_progress(self) -> None:
        for i, seg in enumerate(self._prog_segs):
            if i < self._step:
                seg._c.rgba = CHAT_G4
            elif i == self._step:
                seg._c.rgba = CHAT_G6
            else:
                seg._c.rgba = CHAT_G1

    def _refresh_footer(self) -> None:
        name = STEPS[self._step][0]
        self._footer_label.text = f'STEP {self._step + 1} OF {len(STEPS)} — {name}'
        self._step_indicator.text = f'Step {self._step + 1} of {len(STEPS)}'
        self._back_btn.disabled = (self._step == 0)
        self._back_btn.color = CHAT_G2 if self._step == 0 else CHAT_G3
        if self._step == len(STEPS) - 1:
            self._next_btn.text = '◎ SUBMIT'
            self._next_btn.background_color = (*CHAT_G4[:3], 1.0)
        else:
            self._next_btn.text = 'NEXT →'
            self._next_btn.background_color = (*CHAT_G3[:3], 1.0)
        self._refresh_progress()
        self._refresh_sidebar()

    # ------------------------------------------------------------------
    # Summary pane
    # ------------------------------------------------------------------

    def _refresh_summary(self) -> None:
        self._summary_pane.clear_widgets()
        self._summary_pane.add_widget(
            _lbl('CURRENT ORDER', CHAT_G3, 8, bold=True,
                  size_hint_y=None, height=dp(16))
        )
        items = [
            ('DESIGNATION', self._data.get('title', '')),
            ('TYPE',        self._data.get('mission_type', '')),
            ('ACTIVATION',  self._data.get('activation_time', '')),
            ('ELEMENTS',    f"{len(self._selected_asset_ids)} assigned" if self._selected_asset_ids else 'None'),
            ('OBJECTIVES',  f"{len(self._objective_cards)} defined" if self._objective_cards else 'None'),
        ]
        for key, val in items:
            r = BoxLayout(size_hint_y=None, height=dp(18), spacing=dp(4))
            r.add_widget(_lbl(key, CHAT_G2, 8, bold=True,
                               size_hint=(None, 1), width=dp(80)))
            r.add_widget(_lbl(val or '—', CHAT_G4 if val else CHAT_G1, 8))
            self._summary_pane.add_widget(r)

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def on_back_pressed(self) -> None:
        self.manager.current = 'mission'

    def on_back_step(self) -> None:
        if self._step > 0:
            self._collect_current_step()
            self._step -= 1
            self._build_step(self._step)
            self._refresh_footer()

    def on_next_step(self) -> None:
        if not self._validate_current_step():
            return
        self._collect_current_step()
        if self._step < len(STEPS) - 1:
            self._step += 1
            self._build_step(self._step)
            self._refresh_footer()
        else:
            self._do_submit()

    # ------------------------------------------------------------------
    # Step dispatcher
    # ------------------------------------------------------------------

    def _build_step(self, step: int) -> None:
        self._step_content.clear_widgets()
        builders = [
            self._build_step1_parameters,
            self._build_step2_timeline,
            self._build_step3_assets,
            self._build_step4_objectives,
            self._build_step5_review,
        ]
        builders[step]()

    # ------------------------------------------------------------------
    # Step 1 — Parameters
    # ------------------------------------------------------------------

    def _build_step1_parameters(self) -> None:
        c = self._step_content

        c.add_widget(_section_hdr('01', 'MISSION PARAMETERS'))

        c.add_widget(_field_label('Mission Designation', required=True))
        self._f_title = _text_input('e.g. Operation Clearwater')
        self._f_title.text = self._data.get('title', '')
        c.add_widget(self._f_title)

        c.add_widget(_field_label('Mission Type', required=True))
        current_type = self._data.get('mission_type', self._selected_mission_type)
        self._selected_mission_type = current_type
        type_grid = BoxLayout(
            orientation='horizontal',
            size_hint_y=None, height=dp(len(MISSION_TYPES) // 3 * 40 + 4),
            spacing=dp(6),
        )
        col1 = BoxLayout(orientation='vertical', spacing=dp(4))
        col2 = BoxLayout(orientation='vertical', spacing=dp(4))
        col3 = BoxLayout(orientation='vertical', spacing=dp(4))
        self._mission_type_tiles = []
        for i, mtype in enumerate(MISSION_TYPES):
            tile = _ToggleTile(
                label=mtype,
                on_toggle=lambda lbl, active, t=mtype: self._pick_mission_type(t),
                active=(mtype == current_type),
            )
            [col1, col2, col3][i % 3].add_widget(tile)
            self._mission_type_tiles.append(tile)
        type_grid.add_widget(col1)
        type_grid.add_widget(col2)
        type_grid.add_widget(col3)
        c.add_widget(type_grid)

        custom_type_row = BoxLayout(size_hint_y=None, height=dp(34), spacing=dp(6))
        self._f_custom_mission_type = _text_input('Custom mission type')
        if current_type and current_type not in MISSION_TYPES:
            self._f_custom_mission_type.text = current_type
        custom_type_btn = _btn('USE CUSTOM', CHAT_BG3, CHAT_G4, 10, h=30, w=112)
        custom_type_btn.bind(on_release=lambda _: self._apply_custom_mission_type())
        custom_type_row.add_widget(self._f_custom_mission_type)
        custom_type_row.add_widget(custom_type_btn)
        c.add_widget(custom_type_row)

        c.add_widget(_field_label('Priority', required=True))
        self._priority_selector = _PrioritySelector(
            on_change=lambda p: None,
            initial=self._data.get('priority', 'ROUTINE'),
        )
        c.add_widget(self._priority_selector)

        c.add_widget(_field_label('Mission Intent / Summary'))
        self._f_description = _text_input(
            'Brief description — what this mission accomplishes and why',
            multiline=True, height=64,
        )
        self._f_description.text = self._data.get('description', '')
        c.add_widget(self._f_description)

        # Lead + Org row
        coord_row = BoxLayout(size_hint_y=None, height=dp(56), spacing=dp(10))
        col_a = BoxLayout(orientation='vertical', spacing=dp(4))
        col_a.add_widget(_field_label('Lead Coordinator'))
        self._f_lead = _text_input('Callsign of lead coordinator')
        self._f_lead.text = self._data.get('lead_coordinator', '')
        col_a.add_widget(self._f_lead)
        col_b = BoxLayout(orientation='vertical', spacing=dp(4))
        col_b.add_widget(_field_label('Organization'))
        self._f_org = _text_input('Home organization / unit')
        self._f_org.text = self._data.get('organization', '')
        col_b.add_widget(self._f_org)
        coord_row.add_widget(col_a)
        coord_row.add_widget(col_b)
        c.add_widget(coord_row)

        c.add_widget(_section_hdr('02', 'OPERATING CONSTRAINTS'))
        grid = BoxLayout(
            orientation='horizontal',
            size_hint_y=None, height=dp(len(OPERATING_CONSTRAINTS) // 2 * 40 + 4),
            spacing=dp(6),
        )
        col_l = BoxLayout(orientation='vertical', spacing=dp(4))
        col_r = BoxLayout(orientation='vertical', spacing=dp(4))
        active_constraints = set(self._data.get('constraints', []))
        self._constraint_tiles = []
        for i, c_str in enumerate(OPERATING_CONSTRAINTS):
            tile = _ToggleTile(
                label=c_str,
                on_toggle=lambda lbl, active: None,
                active=(c_str in active_constraints),
            )
            (col_l if i % 2 == 0 else col_r).add_widget(tile)
            self._constraint_tiles.append(tile)
        grid.add_widget(col_l)
        grid.add_widget(col_r)
        c.add_widget(grid)

        custom_constraints = [
            value for value in self._data.get('constraints', [])
            if value not in OPERATING_CONSTRAINTS
        ]
        self._custom_constraint_box = GridLayout(cols=1, size_hint_y=None, spacing=dp(3))
        self._custom_constraint_box.bind(
            minimum_height=self._custom_constraint_box.setter('height')
        )
        c.add_widget(self._custom_constraint_box)
        for value in custom_constraints:
            self._add_custom_constraint_tile(value, active=True)

        custom_constraint_row = BoxLayout(size_hint_y=None, height=dp(34), spacing=dp(6))
        self._f_custom_constraint = _text_input('Custom operating constraint')
        add_constraint_btn = _btn('+ ADD CONSTRAINT', CHAT_BG3, CHAT_G4, 10, h=30, w=136)
        add_constraint_btn.bind(on_release=lambda _: self._add_custom_constraint_from_input())
        custom_constraint_row.add_widget(self._f_custom_constraint)
        custom_constraint_row.add_widget(add_constraint_btn)
        c.add_widget(custom_constraint_row)

    def _pick_mission_type(self, mtype: str) -> None:
        self._selected_mission_type = mtype
        for tile in self._mission_type_tiles:
            tile.set_active(tile._label_text == mtype)

    def _apply_custom_mission_type(self) -> None:
        custom_type = _normalise_option(self._f_custom_mission_type.text)
        if not custom_type:
            return
        self._pick_mission_type(custom_type)
        self._f_custom_mission_type.text = custom_type

    def _add_custom_constraint_from_input(self) -> None:
        label = _normalise_option(self._f_custom_constraint.text)
        if not label:
            return
        for tile in self._constraint_tiles:
            if tile._label_text == label:
                tile.set_active(True)
                self._f_custom_constraint.text = ''
                return
        self._add_custom_constraint_tile(label, active=True)
        self._f_custom_constraint.text = ''

    def _add_custom_constraint_tile(self, label: str, *, active: bool) -> None:
        if not label or not hasattr(self, '_custom_constraint_box'):
            return
        tile = _ToggleTile(
            label=label,
            on_toggle=lambda lbl, is_active: None,
            active=active,
        )
        self._constraint_tiles.append(tile)
        self._custom_constraint_box.add_widget(tile)

    # ------------------------------------------------------------------
    # Step 2 — Timeline
    # ------------------------------------------------------------------

    def _build_step2_timeline(self) -> None:
        c = self._step_content
        c.add_widget(_section_hdr('03', 'TIMING'))

        # Row 1: Activation Time (date picker) | Operation Window | Max Duration
        row1 = BoxLayout(size_hint_y=None, height=dp(56), spacing=dp(10))

        # Activation Time — calendar picker button
        col_act = BoxLayout(orientation='vertical', spacing=dp(4))
        col_act.add_widget(_field_label('Activation Time'))
        act_row = BoxLayout(size_hint_y=None, height=dp(32), spacing=dp(4))
        self._f_activation = _text_input('e.g. 2026-04-20 06:00')
        self._f_activation.text = self._data.get('activation_time', '')
        cal_btn = MDIconButton(
            icon='calendar', size_hint=(None, None), size=(dp(32), dp(32)),
            theme_icon_color='Custom', icon_color=CHAT_G4,
            md_bg_color=(0, 0, 0, 0),
        )
        cal_btn.bind(on_release=lambda *_: self._open_datetime_picker())
        act_row.add_widget(self._f_activation)
        act_row.add_widget(cal_btn)
        col_act.add_widget(act_row)
        row1.add_widget(col_act)

        # Operation Window — plain text
        col_win = BoxLayout(orientation='vertical', spacing=dp(4))
        col_win.add_widget(_field_label('Operation Window'))
        self._f_window = _text_input('e.g. 06:00–14:00')
        self._f_window.text = self._data.get('operation_window', '')
        col_win.add_widget(self._f_window)
        row1.add_widget(col_win)

        # Max Duration — plain text
        col_dur = BoxLayout(orientation='vertical', spacing=dp(4))
        col_dur.add_widget(_field_label('Max Duration'))
        self._f_duration = _text_input('e.g. 8 hrs')
        self._f_duration.text = self._data.get('max_duration', '')
        col_dur.add_widget(self._f_duration)
        row1.add_widget(col_dur)

        c.add_widget(row1)

        # Row 2: Staging Area | Demob Point — both with map pin pickers
        row2 = BoxLayout(size_hint_y=None, height=dp(56), spacing=dp(10))

        for field_key, label, attr in [
            ('staging_area', 'Staging Area', '_f_staging'),
            ('demob_point',  'Demob Point',  '_f_demob'),
        ]:
            col = BoxLayout(orientation='vertical', spacing=dp(4))
            col.add_widget(_field_label(label))
            pick_row = BoxLayout(size_hint_y=None, height=dp(32), spacing=dp(4))
            tf = _text_input('Address or coordinates')
            tf.text = self._data.get(field_key, '')
            setattr(self, attr, tf)
            map_btn = MDIconButton(
                icon='map-marker',
                size_hint=(None, None), size=(dp(32), dp(32)),
                theme_icon_color='Custom', icon_color=CHAT_G4,
                md_bg_color=(0, 0, 0, 0),
            )
            map_btn.bind(
                on_release=lambda *_, lbl=label, f=tf: self._open_point_picker(lbl, f)
            )
            pick_row.add_widget(tf)
            pick_row.add_widget(map_btn)
            col.add_widget(pick_row)
            row2.add_widget(col)

        c.add_widget(row2)

        c.add_widget(_field_label('Stand-down Criteria'))
        self._f_standdown = _text_input('Conditions under which to stand down')
        self._f_standdown.text = self._data.get('standdown_criteria', '')
        c.add_widget(self._f_standdown)

        c.add_widget(_section_hdr('04', 'MISSION PHASES'))

        self._phase_container = GridLayout(cols=1, size_hint_y=None, spacing=dp(2))
        self._phase_container.bind(minimum_height=self._phase_container.setter('height'))
        c.add_widget(self._phase_container)

        self._phase_rows = []
        for phase in self._data.get('phases', []):
            row = self._add_phase_row()
            row.name_field.text      = phase.get('name', '')
            row.objective_field.text = phase.get('objective', '')
            row.duration_field.text  = phase.get('duration', '')

        add_btn = _btn('+ ADD PHASE', CHAT_BG3, CHAT_G4, 10, h=30, w=120)
        add_btn.bind(on_release=lambda _: self._add_phase_row())
        c.add_widget(add_btn)

    def _open_datetime_picker(self) -> None:
        modal = _DateTimePickerModal(
            on_confirm=lambda dt_str: setattr(self._f_activation, 'text', dt_str),
            initial_text=self._f_activation.text,
        )
        modal.open()

    def _open_point_picker(self, label: str, target_field: TextInput) -> None:
        modal = PointPickerModal(
            on_confirm=lambda lat, lon: setattr(
                target_field, 'text', f'{lat:.5f}, {lon:.5f}'
            ),
            label=label,
        )
        modal.open()

    def _add_phase_row(self) -> _PhaseRow:
        row = _PhaseRow(index=len(self._phase_rows), on_remove=self._remove_phase_row)
        self._phase_rows.append(row)
        self._phase_container.add_widget(row)
        return row

    def _remove_phase_row(self, row: _PhaseRow) -> None:
        if row in self._phase_rows:
            self._phase_rows.remove(row)
        self._phase_container.remove_widget(row)

    # ------------------------------------------------------------------
    # Step 3 — Assets
    # ------------------------------------------------------------------

    def _build_step3_assets(self) -> None:
        c = self._step_content
        app = App.get_running_app()

        c.add_widget(_section_hdr('05', f'ASSIGNED ELEMENTS  ({len(self._selected_asset_ids)} selected)'))

        self._asset_checks = {}

        if not app.core_session.is_unlocked:
            c.add_widget(_lbl('Database not available.', CHAT_G2, 10,
                               size_hint_y=None, height=dp(32)))
        else:
            all_assets = app.core_session.read_model("assets.list")
            groups: dict[str, list] = {cat: [] for cat in ASSET_GROUP_ORDER}
            for a in all_assets:
                cat = a.category if a.category in groups else 'custom'
                groups[cat].append(a)

            for cat in ASSET_GROUP_ORDER:
                assets = groups[cat]
                if not assets:
                    continue
                c.add_widget(_lbl(ASSET_GROUP_LABELS.get(cat, cat.upper()),
                                   CHAT_G3, 8, bold=True,
                                   size_hint_y=None, height=dp(18)))
                col_l = BoxLayout(orientation='vertical', spacing=dp(3),
                                   size_hint_y=None)
                col_r = BoxLayout(orientation='vertical', spacing=dp(3),
                                   size_hint_y=None)
                col_l.bind(minimum_height=col_l.setter('height'))
                col_r.bind(minimum_height=col_r.setter('height'))
                grid = BoxLayout(orientation='horizontal', size_hint_y=None,
                                  spacing=dp(6))
                grid.bind(minimum_height=grid.setter('height'))
                for i, asset in enumerate(assets):
                    abbr = CATEGORY_ABBR.get(asset.category, 'CST')
                    pre = asset.id in self._selected_asset_ids
                    tile = _ToggleTile(
                        label=f'[{abbr}]  {asset.label}',
                        on_toggle=lambda lbl, active, aid=asset.id: self._toggle_asset(aid, active),
                        active=pre,
                    )
                    self._asset_checks[asset.id] = tile
                    (col_l if i % 2 == 0 else col_r).add_widget(tile)
                grid.add_widget(col_l)
                grid.add_widget(col_r)
                c.add_widget(grid)

        c.add_widget(_section_hdr('06', 'SUPPORTING RESOURCES'))

        for field_key, label, hint, attr in RESOURCE_FIELDS:
            c.add_widget(_field_label(label))
            tf = _text_input(hint)
            tf.text = self._data.get(field_key, '')
            setattr(self, attr, tf)
            c.add_widget(tf)

        self._custom_resource_container = GridLayout(cols=1, size_hint_y=None, spacing=dp(3))
        self._custom_resource_container.bind(
            minimum_height=self._custom_resource_container.setter('height')
        )
        self._custom_resource_rows = []
        for resource in self._data.get('custom_resources', []):
            row = self._add_custom_resource_row()
            row.label_field.text = resource.get('label', '')
            row.value_field.text = resource.get('details', '')
        c.add_widget(self._custom_resource_container)

        add_resource_btn = _btn('+ ADD CUSTOM RESOURCE', CHAT_BG3, CHAT_G4, 10, h=30, w=178)
        add_resource_btn.bind(on_release=lambda _: self._add_custom_resource_row())
        c.add_widget(add_resource_btn)

    def _toggle_asset(self, asset_id: int, active: bool) -> None:
        if active:
            if asset_id not in self._selected_asset_ids:
                self._selected_asset_ids.append(asset_id)
        else:
            if asset_id in self._selected_asset_ids:
                self._selected_asset_ids.remove(asset_id)

    def _add_custom_resource_row(self) -> _CustomPairRow:
        row = _CustomPairRow(
            'Resource label',
            'Resource requirement / details',
            self._remove_custom_resource_row,
            value_key='details',
        )
        self._custom_resource_rows.append(row)
        self._custom_resource_container.add_widget(row)
        return row

    def _remove_custom_resource_row(self, row: _CustomPairRow) -> None:
        if row in self._custom_resource_rows:
            self._custom_resource_rows.remove(row)
        self._custom_resource_container.remove_widget(row)

    # ------------------------------------------------------------------
    # Step 4 — Objectives
    # ------------------------------------------------------------------

    def _build_step4_objectives(self) -> None:
        c = self._step_content
        c.add_widget(_section_hdr('07', 'OBJECTIVES'))

        self._objective_container = GridLayout(cols=1, size_hint_y=None, spacing=dp(4))
        self._objective_container.bind(minimum_height=self._objective_container.setter('height'))
        c.add_widget(self._objective_container)

        self._objective_cards = []
        if not self._data.get('objectives'):
            self._add_objective_card()
        else:
            for i, obj in enumerate(self._data['objectives']):
                card = self._add_objective_card()
                card.label_field.text    = obj.get('label', '')
                card.phase_field.text    = obj.get('phase', '')
                card.criteria_field.text = obj.get('criteria', '')

        add_btn = _btn('+ ADD OBJECTIVE', CHAT_BG3, CHAT_G4, 10, h=30, w=140)
        add_btn.bind(on_release=lambda _: self._add_objective_card())
        c.add_widget(add_btn)

        c.add_widget(_section_hdr('08', 'AREA OF OPERATIONS'))

        ao_row = BoxLayout(size_hint_y=None, height=dp(36), spacing=dp(8))
        self._ao_label = _lbl(
            f'Mission area: {len(self._ao_polygon)} vertices set' if self._ao_polygon else 'No area set',
            CHAT_G4, 9,
        )
        ao_btn = _btn('DRAW MISSION AREA', CHAT_BG3, CHAT_G5, 10, h=28, w=140)
        ao_btn.bind(on_release=lambda _: self._open_ao_modal())
        ao_clr = MDIconButton(
            icon='close-circle-outline', size_hint=(None, None), size=(dp(28), dp(28)),
            theme_icon_color='Custom', icon_color=CHAT_G3, md_bg_color=(0, 0, 0, 0),
        )
        ao_clr.bind(on_release=lambda _: self._clear_ao())
        ao_row.add_widget(self._ao_label)
        ao_row.add_widget(Widget())
        ao_row.add_widget(ao_btn)
        ao_row.add_widget(ao_clr)
        c.add_widget(ao_row)

        rt_row = BoxLayout(size_hint_y=None, height=dp(36), spacing=dp(8))
        self._route_label = _lbl(
            f'Route: {len(self._route)} waypoints set' if self._route else 'No route set',
            CHAT_G4, 9,
        )
        rt_btn = _btn('SET ROUTE / WAYPOINTS', CHAT_BG3, CHAT_G5, 10, h=28, w=160)
        rt_btn.bind(on_release=lambda _: self._open_route_modal())
        rt_clr = MDIconButton(
            icon='close-circle-outline', size_hint=(None, None), size=(dp(28), dp(28)),
            theme_icon_color='Custom', icon_color=CHAT_G3, md_bg_color=(0, 0, 0, 0),
        )
        rt_clr.bind(on_release=lambda _: self._clear_route())
        rt_row.add_widget(self._route_label)
        rt_row.add_widget(Widget())
        rt_row.add_widget(rt_btn)
        rt_row.add_widget(rt_clr)
        c.add_widget(rt_row)

        c.add_widget(_section_hdr('09', 'KEY LOCATIONS'))
        key_locs = self._data.get('key_locations', {})
        preset_location_keys = {field_key for field_key, _, _, _ in KEY_LOCATION_FIELDS}
        for field_key, label, hint, attr in KEY_LOCATION_FIELDS:
            c.add_widget(_field_label(label))
            tf = _text_input(hint)
            tf.text = key_locs.get(field_key, '')
            setattr(self, attr, tf)
            c.add_widget(tf)

        self._custom_key_location_container = GridLayout(cols=1, size_hint_y=None, spacing=dp(3))
        self._custom_key_location_container.bind(
            minimum_height=self._custom_key_location_container.setter('height')
        )
        self._custom_key_location_rows = []
        for label, value in key_locs.items():
            if label in preset_location_keys or not value:
                continue
            row = self._add_custom_key_location_row()
            row.label_field.text = str(label)
            row.value_field.text = str(value)
        c.add_widget(self._custom_key_location_container)

        add_location_btn = _btn('+ ADD KEY LOCATION', CHAT_BG3, CHAT_G4, 10, h=30, w=158)
        add_location_btn.bind(on_release=lambda _: self._add_custom_key_location_row())
        c.add_widget(add_location_btn)

    def _add_objective_card(self) -> _ObjectiveCard:
        idx = len(self._objective_cards)
        on_remove = self._remove_objective_card if idx > 0 else None
        card = _ObjectiveCard(index=idx, on_remove=on_remove)
        self._objective_cards.append(card)
        self._objective_container.add_widget(card)
        return card

    def _remove_objective_card(self, card: _ObjectiveCard) -> None:
        if card in self._objective_cards:
            self._objective_cards.remove(card)
        self._objective_container.remove_widget(card)

    def _add_custom_key_location_row(self) -> _CustomPairRow:
        row = _CustomPairRow(
            'Location label',
            'Address, coordinates, or description',
            self._remove_custom_key_location_row,
            value_key='value',
        )
        self._custom_key_location_rows.append(row)
        self._custom_key_location_container.add_widget(row)
        return row

    def _remove_custom_key_location_row(self, row: _CustomPairRow) -> None:
        if row in self._custom_key_location_rows:
            self._custom_key_location_rows.remove(row)
        self._custom_key_location_container.remove_widget(row)

    def _open_ao_modal(self) -> None:
        modal = PolygonDrawModal(on_confirm=self._on_ao_confirmed)
        modal.open()

    def _on_ao_confirmed(self, polygon: list) -> None:
        self._ao_polygon = polygon
        if hasattr(self, '_ao_label'):
            self._ao_label.text = f'Mission area: {len(polygon)} vertices set'

    def _clear_ao(self) -> None:
        self._ao_polygon = []
        if hasattr(self, '_ao_label'):
            self._ao_label.text = 'No area set'

    def _open_route_modal(self) -> None:
        modal = WaypointRouteModal(on_confirm=self._on_route_confirmed)
        modal.open()

    def _on_route_confirmed(self, route: list) -> None:
        self._route = route
        if hasattr(self, '_route_label'):
            self._route_label.text = f'Route: {len(route)} waypoints set'

    def _clear_route(self) -> None:
        self._route = []
        if hasattr(self, '_route_label'):
            self._route_label.text = 'No route set'

    # ------------------------------------------------------------------
    # Step 5 — Review
    # ------------------------------------------------------------------

    def _build_step5_review(self) -> None:
        self._collect_all_steps()
        c = self._step_content
        d = self._data

        c.add_widget(_lbl(
            'Review the mission order below before submitting.\n'
            'Once submitted this mission goes to the server for approval.',
            CHAT_G3, 9, size_hint_y=None, height=dp(36),
        ))

        def _review_block(title, rows):
            card = BoxLayout(orientation='vertical', size_hint_y=None,
                              padding=(dp(10), dp(8)), spacing=dp(3))
            card.bind(minimum_height=card.setter('height'))
            _rgba_bg(card, CHAT_BG2)
            card.add_widget(_lbl(title.upper(), CHAT_G5, 10, bold=True,
                                  size_hint_y=None, height=dp(20)))
            # thin line
            ln = Widget(size_hint_y=None, height=dp(1))
            with ln.canvas:
                Color(*CHAT_BORDER)
                r = Rectangle(pos=ln.pos, size=ln.size)
            ln.bind(pos=lambda w, p: setattr(r, 'pos', p),
                    size=lambda w, s: setattr(r, 'size', s))
            card.add_widget(ln)
            for key, val in rows:
                if not val:
                    continue
                row_w = BoxLayout(size_hint_y=None, height=dp(20), spacing=dp(8))
                row_w.add_widget(_lbl(key, CHAT_G3, 9, bold=True,
                                       size_hint=(None, 1), width=dp(120)))
                row_w.add_widget(_lbl(val, CHAT_G4, 9))
                card.add_widget(row_w)
            h = dp(20) + dp(1) + dp(8) + dp(8) + sum(dp(20) for k, v in rows if v)
            card.height = h
            return card

        c.add_widget(_review_block('Mission Parameters', [
            ('DESIGNATION',  d.get('title', '')),
            ('TYPE',         d.get('mission_type', '')),
            ('PRIORITY',     d.get('priority', 'ROUTINE')),
            ('LEAD',         d.get('lead_coordinator', '')),
            ('ORGANIZATION', d.get('organization', '')),
            ('CONSTRAINTS',  ', '.join(d.get('constraints', [])) or None),
            ('INTENT',       (d.get('description', '')[:80] + '…') if len(d.get('description', '')) > 80 else d.get('description', '')),
        ]))

        c.add_widget(_review_block('Timeline', [
            ('ACTIVATION',   d.get('activation_time', '')),
            ('WINDOW',       d.get('operation_window', '')),
            ('MAX DURATION', d.get('max_duration', '')),
            ('STAGING',      d.get('staging_area', '')),
            ('DEMOB POINT',  d.get('demob_point', '')),
            ('STAND-DOWN',   d.get('standdown_criteria', '')),
            ('PHASES',       str(len(d.get('phases', []))) + ' defined'),
        ]))

        element_rows = [
            ('ASSETS',    f'{len(self._selected_asset_ids)} requested' if self._selected_asset_ids else 'None'),
            ('MEDICAL',   d.get('support_medical', '')),
            ('LOGISTICS', d.get('support_logistics', '')),
            ('COMMS',     d.get('support_comms', '')),
            ('EQUIPMENT', d.get('support_equipment', '')),
        ]
        for resource in d.get('custom_resources', []):
            label = _format_location_key(resource.get('label', 'CUSTOM RESOURCE'))
            details = resource.get('details', '')
            if label or details:
                element_rows.append((label or 'CUSTOM RESOURCE', details or 'Defined'))
        c.add_widget(_review_block('Elements Assigned', element_rows))

        obj_rows = []
        for i, obj in enumerate(d.get('objectives', [])):
            prefix = 'PRIMARY' if i == 0 else f'OBJ {i + 1}'
            obj_rows.append((prefix, obj.get('label', '')))
            if obj.get('criteria'):
                obj_rows.append(('END STATE', obj['criteria'][:60]))
        obj_rows.append(('AO POLYGON', f'{len(self._ao_polygon)} vertices' if self._ao_polygon else None))
        obj_rows.append(('ROUTE',      f'{len(self._route)} waypoints' if self._route else None))
        for key, value in d.get('key_locations', {}).items():
            if value:
                obj_rows.append((_format_location_key(key), str(value)[:60]))
        c.add_widget(_review_block('Objectives & Location', obj_rows))

    # ------------------------------------------------------------------
    # Data collection
    # ------------------------------------------------------------------

    def _collect_current_step(self) -> None:
        collectors = [
            self._collect_step1,
            self._collect_step2,
            self._collect_step3,
            self._collect_step4,
            lambda: None,
        ]
        collectors[self._step]()
        self._refresh_summary()

    def _collect_all_steps(self) -> None:
        for fn in [self._collect_step1, self._collect_step2,
                   self._collect_step3, self._collect_step4]:
            try:
                fn()
            except AttributeError:
                pass

    def _collect_step1(self) -> None:
        custom_type_field = getattr(self, '_f_custom_mission_type', None)
        custom_type = _normalise_option(custom_type_field.text) if custom_type_field else ''
        preset_selected = any(t.active for t in self._mission_type_tiles)
        if custom_type and (
            not preset_selected
            or self._selected_mission_type == custom_type
            or self._selected_mission_type not in MISSION_TYPES
        ):
            self._selected_mission_type = custom_type
        self._data['title']           = getattr(self, '_f_title', None) and self._f_title.text.strip() or self._data.get('title', '')
        self._data['mission_type']    = self._selected_mission_type
        self._data['priority']        = self._priority_selector.value if self._priority_selector else self._data.get('priority', 'ROUTINE')
        self._data['description']     = getattr(self, '_f_description', None) and self._f_description.text.strip() or self._data.get('description', '')
        self._data['lead_coordinator']= getattr(self, '_f_lead', None) and self._f_lead.text.strip() or self._data.get('lead_coordinator', '')
        self._data['organization']    = getattr(self, '_f_org', None) and self._f_org.text.strip() or self._data.get('organization', '')
        constraints = [t._label_text for t in self._constraint_tiles if t.active]
        custom_constraint_field = getattr(self, '_f_custom_constraint', None)
        custom_constraint = (
            _normalise_option(custom_constraint_field.text)
            if custom_constraint_field else ''
        )
        if custom_constraint and custom_constraint not in constraints:
            constraints.append(custom_constraint)
        self._data['constraints'] = constraints

    def _collect_step2(self) -> None:
        for field_key, attr in [
            ('activation_time',   '_f_activation'),
            ('operation_window',  '_f_window'),
            ('max_duration',      '_f_duration'),
            ('staging_area',      '_f_staging'),
            ('demob_point',       '_f_demob'),
            ('standdown_criteria','_f_standdown'),
        ]:
            tf = getattr(self, attr, None)
            if tf is not None:
                self._data[field_key] = tf.text.strip()
        self._data['phases'] = [r.get_data() for r in self._phase_rows]

    def _collect_step3(self) -> None:
        for field_key, _, _, attr in RESOURCE_FIELDS:
            tf = getattr(self, attr, None)
            if tf is not None:
                self._data[field_key] = tf.text.strip()
        custom_resources = []
        for row in self._custom_resource_rows:
            item = row.get_data()
            if item.get('label') or item.get('details'):
                custom_resources.append(item)
        self._data['custom_resources'] = custom_resources

    def _collect_step4(self) -> None:
        self._data['objectives'] = [c.get_data() for c in self._objective_cards]
        key_locs = {}
        for field_key, _, _, attr in KEY_LOCATION_FIELDS:
            tf = getattr(self, attr, None)
            if tf is not None:
                key_locs[field_key] = tf.text.strip()
        for row in self._custom_key_location_rows:
            item = row.get_data()
            label = _compact_text(item.get('label', ''))
            value = _compact_text(item.get('value', ''))
            if label or value:
                key_locs[label or 'Custom Location'] = value
        self._data['key_locations'] = key_locs

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def _validate_current_step(self) -> bool:
        if self._step == 0:
            title = getattr(self, '_f_title', None) and self._f_title.text.strip()
            if not title:
                self._show_error('Mission designation is required.')
                return False
        return True

    # ------------------------------------------------------------------
    # Submit
    # ------------------------------------------------------------------

    def _do_submit(self) -> None:
        self._collect_all_steps()
        app = App.get_running_app()
        if not app.core_session.is_unlocked:
            self._show_error('Database not available.')
            return

        title = self._data.get('title', '').strip()
        if not title:
            self._show_error('Mission designation is required.')
            return

        try:
            app.core_session.command(
                "missions.create",
                title=title,
                description=self._data.get('description', ''),
                asset_ids=list(self._selected_asset_ids),
                ao_polygon=self._ao_polygon,
                route=self._route,
                mission_type=self._data.get('mission_type', ''),
                priority=self._data.get('priority', 'ROUTINE'),
                lead_coordinator=self._data.get('lead_coordinator', ''),
                organization=self._data.get('organization', ''),
                activation_time=self._data.get('activation_time', ''),
                operation_window=self._data.get('operation_window', ''),
                max_duration=self._data.get('max_duration', ''),
                staging_area=self._data.get('staging_area', ''),
                demob_point=self._data.get('demob_point', ''),
                standdown_criteria=self._data.get('standdown_criteria', ''),
                phases=self._data.get('phases', []),
                constraints=self._data.get('constraints', []),
                support_medical=self._data.get('support_medical', ''),
                support_logistics=self._data.get('support_logistics', ''),
                support_comms=self._data.get('support_comms', ''),
                support_equipment=self._data.get('support_equipment', ''),
                custom_resources=self._data.get('custom_resources', []),
                objectives=self._data.get('objectives', []),
                key_locations=self._data.get('key_locations', {}),
            )
        except ValueError as exc:
            self._show_error(str(exc))
            return

        self.manager.current = 'mission'

    # ------------------------------------------------------------------
    # Error dialog
    # ------------------------------------------------------------------

    def _show_error(self, message: str) -> None:
        modal = ModalView(
            size_hint=(None, None), size=(dp(340), dp(140)),
            background='', background_color=(0, 0, 0, 0.7),
        )
        wrap = BoxLayout(orientation='vertical',
                         size_hint=(None, None), size=(dp(340), dp(140)))
        _rgba_bg(wrap, CHAT_BG2)

        msg = Label(text=message, color=CHAT_RED2, font_size=dp(10),
                    halign='center', valign='middle', size_hint=(1, 1))
        msg.bind(size=msg.setter('text_size'))
        wrap.add_widget(msg)

        foot = BoxLayout(size_hint_y=None, height=dp(40), padding=(dp(12), dp(4)))
        _rgba_bg(foot, CHAT_BG1)
        ok_btn = _btn('OK', CHAT_BG3, CHAT_G4, 10, h=28, w=60)
        ok_btn.bind(on_release=lambda _: modal.dismiss())
        foot.add_widget(Widget())
        foot.add_widget(ok_btn)
        wrap.add_widget(foot)
        modal.add_widget(wrap)
        modal.open()


# ---------------------------------------------------------------------------
# Date/time picker modal — calendar grid + HH:MM +/− buttons
# ---------------------------------------------------------------------------

class _DateTimePickerModal(ModalView):
    """Compact tactical-themed date + time picker.

    Returns a string in ``YYYY-MM-DD HH:MM`` format via ``on_confirm``.
    """

    def __init__(self, on_confirm: typing.Callable, initial_text: str = '', **kwargs):
        super().__init__(
            size_hint=(None, None), size=(dp(360), dp(432)),
            auto_dismiss=False,
            background='', background_color=(0, 0, 0, 0.75),
            **kwargs,
        )
        self._on_confirm = on_confirm

        today = datetime.date.today()
        self._selected: typing.Optional[datetime.date] = None
        self._hour = 0
        self._minute = 0
        if initial_text:
            for fmt in ('%Y-%m-%d %H:%M', '%Y-%m-%d'):
                try:
                    dt = datetime.datetime.strptime(initial_text.strip(), fmt)
                    self._selected = dt.date()
                    self._hour = dt.hour
                    self._minute = dt.minute
                    break
                except ValueError:
                    pass
        self._view_year  = self._selected.year  if self._selected else today.year
        self._view_month = self._selected.month if self._selected else today.month

        wrap = BoxLayout(orientation='vertical', spacing=0)
        _rgba_bg(wrap, CHAT_BG2)

        # Title bar
        title_row = BoxLayout(size_hint_y=None, height=dp(36),
                               padding=(dp(10), dp(4)))
        _rgba_bg(title_row, CHAT_BG1)
        _hline(title_row, CHAT_BORDER, 'bottom')
        title_row.add_widget(_lbl('SELECT DATE & TIME', CHAT_G5, 11, bold=True))
        wrap.add_widget(title_row)

        # Month navigation
        nav_row = BoxLayout(size_hint_y=None, height=dp(36),
                             spacing=dp(4), padding=(dp(6), dp(4)))
        _rgba_bg(nav_row, CHAT_BG2)
        prev_btn = _btn('◀', CHAT_BG2, CHAT_G4, 11, h=28, w=32)
        prev_btn.bind(on_release=lambda _: self._prev_month())
        self._month_lbl = _lbl('', CHAT_G5, 11, bold=True, halign='center')
        next_btn = _btn('▶', CHAT_BG2, CHAT_G4, 11, h=28, w=32)
        next_btn.bind(on_release=lambda _: self._next_month())
        nav_row.add_widget(prev_btn)
        nav_row.add_widget(self._month_lbl)
        nav_row.add_widget(next_btn)
        wrap.add_widget(nav_row)

        # Day-name header row
        days_hdr = GridLayout(cols=7, size_hint_y=None, height=dp(20))
        for d in ('M', 'T', 'W', 'T', 'F', 'S', 'S'):
            days_hdr.add_widget(_lbl(d, CHAT_G3, 8, bold=True, halign='center'))
        wrap.add_widget(days_hdr)

        # Day grid (rebuilt on month change)
        self._cal_grid = GridLayout(cols=7, size_hint_y=None,
                                     spacing=dp(1), padding=(dp(2), dp(2)))
        self._cal_grid.bind(minimum_height=self._cal_grid.setter('height'))
        wrap.add_widget(self._cal_grid)

        # Divider
        div = Widget(size_hint_y=None, height=dp(1))
        with div.canvas:
            Color(*CHAT_BORDER)
            _r = Rectangle(pos=div.pos, size=div.size)
        div.bind(pos=lambda w, p: setattr(_r, 'pos', p),
                 size=lambda w, s: setattr(_r, 'size', s))
        wrap.add_widget(div)

        # Time row
        time_row = BoxLayout(size_hint_y=None, height=dp(50),
                              spacing=dp(6), padding=(dp(10), dp(7)))
        _rgba_bg(time_row, CHAT_BG1)
        time_row.add_widget(_lbl('TIME', CHAT_G3, 9, bold=True,
                                  size_hint_x=None, width=dp(38)))

        h_minus = _btn('−', CHAT_BG3, CHAT_G4, 13, h=34, w=30)
        self._h_lbl = _lbl(f'{self._hour:02d}', CHAT_G5, 14, bold=True,
                             halign='center', size_hint_x=None, width=dp(34))
        h_plus  = _btn('+', CHAT_BG3, CHAT_G4, 13, h=34, w=30)
        h_minus.bind(on_release=lambda _: self._adj_hour(-1))
        h_plus.bind(on_release=lambda _:  self._adj_hour(+1))
        time_row.add_widget(h_minus)
        time_row.add_widget(self._h_lbl)
        time_row.add_widget(h_plus)

        time_row.add_widget(_lbl(':', CHAT_G4, 16, bold=True,
                                  size_hint_x=None, width=dp(14), halign='center'))

        m_minus = _btn('−', CHAT_BG3, CHAT_G4, 13, h=34, w=30)
        self._m_lbl = _lbl(f'{self._minute:02d}', CHAT_G5, 14, bold=True,
                             halign='center', size_hint_x=None, width=dp(34))
        m_plus  = _btn('+', CHAT_BG3, CHAT_G4, 13, h=34, w=30)
        m_minus.bind(on_release=lambda _: self._adj_minute(-5))
        m_plus.bind(on_release=lambda _:  self._adj_minute(+5))
        time_row.add_widget(m_minus)
        time_row.add_widget(self._m_lbl)
        time_row.add_widget(m_plus)
        wrap.add_widget(time_row)

        # Footer
        foot = BoxLayout(size_hint_y=None, height=dp(44),
                          spacing=dp(8), padding=(dp(8), dp(6)))
        _rgba_bg(foot, CHAT_BG1)
        _hline(foot, CHAT_BORDER, 'top')
        cancel_btn = _btn('CANCEL', CHAT_BG3, CHAT_G3, 10, h=30, w=80)
        cancel_btn.bind(on_release=lambda _: self.dismiss())
        self._confirm_btn = _btn('CONFIRM', (*CHAT_G4[:3], 1.0), CHAT_G6, 10,
                                  h=30, w=90, bold=True)
        self._confirm_btn.bind(on_release=lambda _: self._confirm())
        foot.add_widget(Widget())
        foot.add_widget(cancel_btn)
        foot.add_widget(self._confirm_btn)
        wrap.add_widget(foot)

        self.add_widget(wrap)
        self._rebuild_calendar()

    def _rebuild_calendar(self) -> None:
        self._cal_grid.clear_widgets()
        self._month_lbl.text = (
            datetime.date(self._view_year, self._view_month, 1)
            .strftime('%B %Y').upper()
        )
        today = datetime.date.today()
        weeks = _calendar.monthcalendar(self._view_year, self._view_month)
        while len(weeks) < 6:
            weeks.append([0] * 7)

        for week in weeks:
            for day in week:
                if day == 0:
                    self._cal_grid.add_widget(
                        Widget(size_hint_y=None, height=dp(30))
                    )
                else:
                    date = datetime.date(self._view_year, self._view_month, day)
                    is_sel   = (self._selected == date)
                    is_today = (date == today)
                    if is_sel:
                        bg, fg = (*CHAT_G4[:3], 1.0), CHAT_G6
                    elif is_today:
                        bg, fg = CHAT_BG3, CHAT_AMBER
                    else:
                        bg, fg = CHAT_BG2, CHAT_G4
                    btn = _btn(str(day), bg, fg, 9, h=30)
                    btn.bind(on_release=lambda _, d=day: self._pick_day(d))
                    self._cal_grid.add_widget(btn)

        self._confirm_btn.disabled = (self._selected is None)

    def _pick_day(self, day: int) -> None:
        self._selected = datetime.date(self._view_year, self._view_month, day)
        self._rebuild_calendar()

    def _prev_month(self) -> None:
        if self._view_month == 1:
            self._view_month, self._view_year = 12, self._view_year - 1
        else:
            self._view_month -= 1
        self._rebuild_calendar()

    def _next_month(self) -> None:
        if self._view_month == 12:
            self._view_month, self._view_year = 1, self._view_year + 1
        else:
            self._view_month += 1
        self._rebuild_calendar()

    def _adj_hour(self, delta: int) -> None:
        self._hour = (self._hour + delta) % 24
        self._h_lbl.text = f'{self._hour:02d}'

    def _adj_minute(self, delta: int) -> None:
        self._minute = (self._minute + delta) % 60
        self._m_lbl.text = f'{self._minute:02d}'

    def _confirm(self) -> None:
        if self._selected:
            dt_str = (
                f"{self._selected.strftime('%Y-%m-%d')} "
                f"{self._hour:02d}:{self._minute:02d}"
            )
            self._on_confirm(dt_str)
        self.dismiss()


# ---------------------------------------------------------------------------
# Priority selector widget (defined after MissionCreateScreen so it can be
# referenced in the type hint above as a forward string reference)
# ---------------------------------------------------------------------------

class _PrioritySelector(BoxLayout):
    """Three-pill ROUTINE / PRIORITY / FLASH selector."""

    def __init__(self, on_change: typing.Callable, initial: str = 'ROUTINE', **kwargs):
        super().__init__(
            orientation='horizontal',
            size_hint_y=None, height=dp(40),
            spacing=dp(6),
            **kwargs,
        )
        self._on_change = on_change
        self._selected  = initial
        self._pills: dict[str, _ToggleTile] = {}
        for p in ('ROUTINE', 'PRIORITY', 'FLASH'):
            tile = _ToggleTile(
                label=p,
                on_toggle=lambda lbl, active, priority=p: self._pick(priority),
                active=(p == initial),
            )
            self._pills[p] = tile
            self.add_widget(tile)

    def _pick(self, priority: str) -> None:
        self._selected = priority
        for p, tile in self._pills.items():
            tile.set_active(p == priority)
        self._on_change(priority)

    @property
    def value(self) -> str:
        return self._selected
