"""
Chat screen — phosphor green 4-pane tactical layout.

Panes (left→right):
  _ChannelPanel  220dp — grouped channel list + search + user footer
  _ChatArea      flex  — top bar, message thread, compose area
  _RightPanel    210dp — operators online + alert feed
"""
import datetime
import typing

from kivy.app import App
from kivy.clock import Clock
from kivy.graphics import Color, Line, Rectangle
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.modalview import ModalView
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget
from kivymd.uix.screen import MDScreen

from talon.ui.font_scale import get_font_scale
from talon.ui.theme import (
    CHAT_AMBER, CHAT_AMBER2, CHAT_BG0, CHAT_BG1, CHAT_BG2, CHAT_BG3,
    CHAT_BG4, CHAT_BORDER, CHAT_G1, CHAT_G2, CHAT_G3, CHAT_G4, CHAT_G5,
    CHAT_G6, CHAT_RED, CHAT_RED2,
)
from talon.utils.logging import get_logger

_log = get_logger("ui.chat")


def _fs(base: float) -> float:
    return dp(base * get_font_scale())


# Channel group display order and metadata
_GROUP_ORDER = ["emergency", "allhands", "mission", "squad", "direct"]
_GROUP_LABELS = {
    "emergency": "EMERGENCY",
    "allhands":  "ALL-HANDS",
    "mission":   "MISSION",
    "squad":     "SQUAD",
    "direct":    "DIRECT",
}
_GROUP_ICONS = {
    "emergency": "⚡",
    "allhands":  "◉",
    "mission":   "◎",
    "squad":     "◈",
    "direct":    "◆",
}
_CHANNEL_DESC = {
    "emergency": "// PRIORITY ENCRYPTED",
    "allhands":  "// AUTHENTICATED",
    "mission":   "// ACTIVE OPERATION",
    "squad":     "// SQUAD NET",
    "direct":    "// SECURE DM",
}


def _rgba_bg(widget, color):
    """Draw a solid background rectangle on the given widget's canvas."""
    with widget.canvas.before:
        Color(*color)
        rect = Rectangle(pos=widget.pos, size=widget.size)
    widget.bind(
        pos=lambda w, _: setattr(rect, 'pos', w.pos),
        size=lambda w, _: setattr(rect, 'size', w.size),
    )
    return rect


def _draw_right_border(widget, color, thickness=1):
    """Draw a vertical border on the right edge of widget."""
    with widget.canvas.after:
        Color(*color)
        line = Line(points=[], width=thickness)

    def _update(_widget, _value):
        x = _widget.right
        line.points = [x, _widget.y, x, _widget.top]

    widget.bind(pos=_update, size=_update)


def _draw_left_border(widget, color, thickness=2):
    """Draw a vertical border on the left edge of widget."""
    with widget.canvas.before:
        Color(*color)
        rect = Rectangle(pos=(widget.x, widget.y), size=(thickness, widget.height))

    def _update(_widget, _value):
        rect.pos = (_widget.x, _widget.y)
        rect.size = (thickness, _widget.height)

    widget.bind(pos=_update, size=_update)
    return rect


def _draw_top_border(widget, color, thickness=1):
    with widget.canvas.before:
        Color(*color)
        rect = Rectangle(pos=widget.pos, size=(widget.width, thickness))

    def _update(_widget, _value):
        rect.pos = (_widget.x, _widget.top - thickness)
        rect.size = (_widget.width, thickness)

    widget.bind(pos=_update, size=_update)


def _draw_bottom_border(widget, color, thickness=1):
    with widget.canvas.before:
        Color(*color)
        rect = Rectangle(pos=widget.pos, size=(widget.width, thickness))

    def _update(_widget, _value):
        rect.pos = (_widget.x, _widget.y)
        rect.size = (_widget.width, thickness)

    widget.bind(pos=_update, size=_update)


def _start_blink(label: Label):
    """Blink a label's opacity between 1.0 and 0.3 every 0.6 s (step, not ease)."""
    def _toggle(dt):
        label.opacity = 0.3 if label.opacity > 0.5 else 1.0
    return Clock.schedule_interval(_toggle, 0.6)


def _ts_to_local(unix_ts: int) -> str:
    """Convert a Unix timestamp to HH:MM in the operator's local time."""
    try:
        dt = datetime.datetime.fromtimestamp(unix_ts)
        return dt.strftime("%H:%M")
    except Exception:
        return "--:--"


def _make_label(text="", color=CHAT_G4, font_size=11, bold=False,
                halign="left", size_hint_y=None, height=None, **kwargs) -> Label:
    lbl = Label(
        text=text,
        color=color,
        font_size=_fs(font_size),
        bold=bold,
        halign=halign,
        size_hint_y=size_hint_y,
        **kwargs,
    )
    if height is not None:
        lbl.height = dp(height)
    lbl.bind(size=lbl.setter('text_size'))
    return lbl


def _make_btn(text, bg_color=CHAT_BG3, text_color=CHAT_G4, font_size=11,
              height=28, width=None, **kwargs) -> Button:
    btn = Button(
        text=text,
        color=text_color,
        font_size=_fs(font_size),
        background_normal='',
        background_color=bg_color,
        size_hint_y=None,
        height=dp(height),
        **kwargs,
    )
    if width is not None:
        btn.size_hint_x = None
        btn.width = dp(width)
    return btn


# ---------------------------------------------------------------------------
# Channel Panel
# ---------------------------------------------------------------------------

class _ChannelPanel(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(
            orientation='vertical',
            size_hint_x=None,
            width=dp(220),
            **kwargs,
        )
        _rgba_bg(self, CHAT_BG1)
        _draw_right_border(self, CHAT_BORDER)

        # Header
        header = BoxLayout(
            size_hint_y=None, height=dp(36),
            padding=(dp(12), dp(0)),
        )
        _rgba_bg(header, CHAT_BG1)
        _draw_bottom_border(header, CHAT_BORDER)
        header.add_widget(_make_label(
            "TALON COMMS", color=CHAT_G6, font_size=12, bold=True,
            size_hint_y=None, height=36, halign='left',
        ))
        self.add_widget(header)

        # Search bar
        search_wrap = BoxLayout(size_hint_y=None, height=dp(36), padding=(dp(8), dp(4)))
        _rgba_bg(search_wrap, CHAT_BG1)
        _draw_bottom_border(search_wrap, CHAT_BORDER)
        self._search = TextInput(
            hint_text="SEARCH CHANNELS...",
            hint_text_color=CHAT_G2,
            foreground_color=CHAT_G5,
            background_color=CHAT_BG3,
            cursor_color=CHAT_G5,
            font_size=dp(10),
            multiline=False,
            size_hint_y=None,
            height=dp(26),
        )
        self._search.bind(text=self._on_search)
        search_wrap.add_widget(self._search)
        self.add_widget(search_wrap)

        # Scrollable channel list
        self._scroll = ScrollView(bar_width=dp(3), bar_color=CHAT_G2, bar_inactive_color=CHAT_G1)
        self._list_layout = GridLayout(cols=1, size_hint_y=None, spacing=0)
        self._list_layout.bind(minimum_height=self._list_layout.setter('height'))
        self._scroll.add_widget(self._list_layout)
        self.add_widget(self._scroll)

        # User footer
        self._footer = _UserFooter()
        self.add_widget(self._footer)

        self._all_items: list['_ChannelItem'] = []
        self._active_item: typing.Optional['_ChannelItem'] = None
        self._on_select_cb: typing.Optional[typing.Callable] = None

    def wire(self, screen: 'ChatScreen', on_select):
        self._on_select_cb = on_select
        self._footer.wire(screen)

    def populate(self, channels: list, active_channel_id: typing.Optional[int]) -> None:
        self._list_layout.clear_widgets()
        self._all_items.clear()
        self._active_item = None

        grouped: dict[str, list] = {g: [] for g in _GROUP_ORDER}
        for ch in channels:
            gt = ch.group_type if ch.group_type in grouped else "squad"
            grouped[gt].append(ch)

        for group in _GROUP_ORDER:
            chs = grouped[group]
            if not chs:
                continue
            # Group label
            lbl = _make_label(
                _GROUP_LABELS[group], color=CHAT_G3, font_size=10, bold=True,
                size_hint_y=None, height=22,
            )
            lbl.padding_x = dp(12)
            self._list_layout.add_widget(lbl)
            for ch in chs:
                item = _ChannelItem(channel=ch, panel=self)
                self._all_items.append(item)
                self._list_layout.add_widget(item)
                if active_channel_id is not None and ch.id == active_channel_id:
                    self._set_active(item)

    def _on_search(self, instance, text):
        q = text.strip().lower()
        for item in self._all_items:
            item.opacity = 1 if (not q or q in item.channel.name.lower()) else 0
            item.height = dp(28) if (not q or q in item.channel.name.lower()) else 0

    def select_item(self, item: '_ChannelItem'):
        self._set_active(item)
        if self._on_select_cb:
            self._on_select_cb(item.channel)

    def _set_active(self, item: '_ChannelItem'):
        if self._active_item is not None:
            self._active_item.set_active(False)
        self._active_item = item
        item.set_active(True)

    def update_footer(self, callsign: str, role: str):
        self._footer.update(callsign, role)


class _UserFooter(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(
            orientation='horizontal',
            size_hint_y=None,
            height=dp(40),
            padding=(dp(10), dp(6)),
            spacing=dp(6),
            **kwargs,
        )
        _rgba_bg(self, CHAT_BG1)
        _draw_top_border(self, CHAT_BORDER)

        # Online dot
        dot = Widget(size_hint=(None, None), size=(dp(6), dp(6)))
        with dot.canvas:
            Color(*CHAT_G5)
            Rectangle(pos=dot.pos, size=dot.size)
        self.add_widget(dot)

        # Callsign + role stack
        info = BoxLayout(orientation='vertical')
        self._callsign_lbl = _make_label("—", color=CHAT_G6, font_size=11, bold=True,
                                          size_hint_y=None, height=16)
        self._role_lbl = _make_label("", color=CHAT_G3, font_size=9,
                                      size_hint_y=None, height=12)
        info.add_widget(self._callsign_lbl)
        info.add_widget(self._role_lbl)
        self.add_widget(info)

    def wire(self, screen: 'ChatScreen'):
        pass  # populated via update()

    def update(self, callsign: str, role: str):
        self._callsign_lbl.text = callsign
        self._role_lbl.text = role.upper() if role else ""


# ---------------------------------------------------------------------------
# Channel Item
# ---------------------------------------------------------------------------

class _ChannelItem(BoxLayout):
    def __init__(self, channel, panel: _ChannelPanel, **kwargs):
        super().__init__(
            orientation='horizontal',
            size_hint_y=None,
            height=dp(28),
            padding=(dp(14), dp(4), dp(10), dp(4)),
            spacing=dp(6),
            **kwargs,
        )
        self.channel = channel
        self._panel = panel
        self._active = False
        self._bg_color = (0, 0, 0, 0)

        with self.canvas.before:
            self._bg_instr_color = Color(0, 0, 0, 0)
            self._bg_rect = Rectangle(pos=self.pos, size=self.size)
            # Left border (always drawn, color changes)
            border_color = CHAT_RED2 if channel.group_type == "emergency" else (0, 0, 0, 0)
            self._border_color_instr = Color(*border_color)
            self._border_rect = Rectangle(pos=self.pos, size=(dp(2), self.height))

        self.bind(pos=self._update_canvas, size=self._update_canvas)

        icon = _make_label(
            _GROUP_ICONS.get(channel.group_type, "◈"),
            color=CHAT_G3, font_size=10,
            size_hint_x=None, size_hint_y=None,
            height=20, width=dp(14),
        )
        self.add_widget(icon)

        name_text = channel.name
        name_color = CHAT_RED2 if channel.group_type == "emergency" else CHAT_G4
        self._name_lbl = _make_label(
            name_text, color=name_color, font_size=11,
            size_hint_y=None, height=20,
        )
        self.add_widget(self._name_lbl)

        # Unread badge placeholder (populated externally)
        self._badge_lbl = Label(
            text="",
            color=(1, 1, 1, 1),
            font_size=dp(9),
            size_hint=(None, None),
            size=(dp(0), dp(16)),
        )
        self.add_widget(self._badge_lbl)

    def _update_canvas(self, *_):
        self._bg_rect.pos = self.pos
        self._bg_rect.size = self.size
        self._border_rect.pos = self.pos
        self._border_rect.size = (dp(2), self.height)

    def set_active(self, active: bool):
        self._active = active
        if active:
            self._bg_instr_color.rgba = CHAT_BG4
            self._name_lbl.color = CHAT_G6
            # Active left border always green
            self._border_color_instr.rgba = CHAT_G5
            self._border_rect.size = (dp(2), self.height)
        else:
            self._bg_instr_color.rgba = (0, 0, 0, 0)
            if self.channel.group_type == "emergency":
                self._name_lbl.color = CHAT_RED2
                self._border_color_instr.rgba = CHAT_RED2
            else:
                self._name_lbl.color = CHAT_G4
                self._border_color_instr.rgba = (0, 0, 0, 0)

    def set_badge(self, count: int, is_mission: bool = False):
        if count > 0:
            badge_bg = CHAT_AMBER if is_mission else CHAT_RED
            self._badge_lbl.text = str(count)
            self._badge_lbl.width = dp(max(16, 8 * len(str(count))))
            with self._badge_lbl.canvas.before:
                Color(*badge_bg)
                Rectangle(pos=self._badge_lbl.pos, size=self._badge_lbl.size)
        else:
            self._badge_lbl.text = ""
            self._badge_lbl.width = dp(0)

    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos):
            self._bg_instr_color.rgba = CHAT_BG3
            return True
        return False

    def on_touch_up(self, touch):
        if self.collide_point(*touch.pos):
            self._panel.select_item(self)
        if not self._active:
            self._bg_instr_color.rgba = (0, 0, 0, 0)
        return False


# ---------------------------------------------------------------------------
# Chat Area
# ---------------------------------------------------------------------------

class _ChatArea(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(orientation='vertical', **kwargs)
        _rgba_bg(self, CHAT_BG0)

        # Flash banner (hidden by default)
        self._flash_bar = _FlashBanner()
        self._flash_bar.opacity = 0
        self._flash_bar.height = dp(0)
        self.add_widget(self._flash_bar)

        # Top bar
        self._topbar = _ChatTopBar()
        self.add_widget(self._topbar)

        # Message scroll
        self._msg_scroll = ScrollView(
            bar_width=dp(3), bar_color=CHAT_G2, bar_inactive_color=CHAT_G1,
            do_scroll_x=False,
        )
        self._msg_layout = GridLayout(cols=1, size_hint_y=None, spacing=0)
        self._msg_layout.bind(minimum_height=self._msg_layout.setter('height'))
        self._msg_scroll.add_widget(self._msg_layout)
        self.add_widget(self._msg_scroll)

        # Input area
        self._input_area = _InputArea()
        self.add_widget(self._input_area)

    def wire(self, screen: 'ChatScreen'):
        self._screen = screen
        self._input_area.wire(screen)

    def show_channel(self, channel, messages: list):
        is_flash = channel.group_type == "emergency"
        if is_flash:
            self._flash_bar.opacity = 1
            self._flash_bar.height = dp(32)
        else:
            self._flash_bar.opacity = 0
            self._flash_bar.height = dp(0)

        self._topbar.update(channel)

        self._msg_layout.clear_widgets()

        # Session divider
        divider = _SessionDivider()
        self._msg_layout.add_widget(divider)

        if not messages:
            empty = _make_label("// No traffic on this channel.", color=CHAT_G3,
                                font_size=10, size_hint_y=None, height=40, halign='left')
            empty.padding_x = dp(14)
            self._msg_layout.add_widget(empty)
            return

        for msg, callsign in messages:
            row = _MessageRow(msg=msg, callsign=callsign)
            self._msg_layout.add_widget(row)

        Clock.schedule_once(lambda dt: setattr(self._msg_scroll, 'scroll_y', 0))

    def append_message(self, msg, callsign: str):
        row = _MessageRow(msg=msg, callsign=callsign)
        self._msg_layout.add_widget(row)
        Clock.schedule_once(lambda dt: setattr(self._msg_scroll, 'scroll_y', 0))

    @property
    def urgent_active(self) -> bool:
        return self._input_area.urgent_active

    @property
    def grid_active(self) -> bool:
        return self._input_area.grid_active

    @property
    def grid_ref_text(self) -> str:
        return self._input_area.grid_ref_text

    @property
    def message_text(self) -> str:
        return self._input_area.message_text

    def clear_input(self):
        self._input_area.clear()


class _FlashBanner(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(
            orientation='horizontal',
            size_hint_y=None,
            height=dp(32),
            padding=(dp(14), dp(6)),
            spacing=dp(8),
            **kwargs,
        )
        with self.canvas.before:
            Color(0.706, 0.157, 0.0, 0.15)
            self._bg = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=lambda w, _: setattr(self._bg, 'pos', w.pos),
                  size=lambda w, _: setattr(self._bg, 'size', w.size))
        _draw_bottom_border(self, CHAT_RED2, thickness=2)

        self._flash_lbl = _make_label(
            "⚡ FLASH", color=CHAT_RED2, font_size=12, bold=True,
            size_hint_x=None, size_hint_y=None, height=20, width=dp(80),
        )
        self.add_widget(self._flash_lbl)
        self._blink_ev = _start_blink(self._flash_lbl)

        self.add_widget(_make_label(
            "PRIORITY CHANNEL — ALL TRAFFIC LOGGED",
            color=CHAT_RED2, font_size=10,
            size_hint_y=None, height=20,
        ))

    def on_parent(self, instance, parent):
        if parent is None and self._blink_ev:
            self._blink_ev.cancel()


class _ChatTopBar(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(
            orientation='horizontal',
            size_hint_y=None,
            height=dp(40),
            padding=(dp(14), dp(0)),
            spacing=dp(8),
            **kwargs,
        )
        _rgba_bg(self, CHAT_BG1)
        _draw_bottom_border(self, CHAT_BORDER)

        self._icon_lbl = _make_label("◎", color=CHAT_G3, font_size=11,
                                      size_hint_x=None, size_hint_y=None,
                                      height=40, width=dp(18))
        self.add_widget(self._icon_lbl)

        self._name_lbl = _make_label("", color=CHAT_G6, font_size=14, bold=True,
                                      size_hint_x=None, size_hint_y=None,
                                      height=40, width=dp(200))
        self.add_widget(self._name_lbl)

        self._type_lbl = _make_label("", color=CHAT_G3, font_size=9,
                                      size_hint_x=None, size_hint_y=None,
                                      height=40, width=dp(80))
        self.add_widget(self._type_lbl)

        self._desc_lbl = _make_label("", color=CHAT_G3, font_size=10,
                                      size_hint_y=None, height=40)
        self.add_widget(self._desc_lbl)

        # Spacer
        self.add_widget(Widget())

        # Action buttons
        for label in ("GRID REF", "ENCRYPT", "HISTORY"):
            btn = _make_btn(label, bg_color=CHAT_BG3, text_color=CHAT_G4,
                            font_size=10, height=24, width=60)
            self.add_widget(btn)

    def update(self, channel):
        self._icon_lbl.text = _GROUP_ICONS.get(channel.group_type, "◈")
        self._name_lbl.text = channel.name.upper().lstrip("#")
        self._type_lbl.text = f"[{_GROUP_LABELS.get(channel.group_type, 'CHANNEL')}]"
        self._desc_lbl.text = _CHANNEL_DESC.get(channel.group_type, "")


class _SessionDivider(BoxLayout):
    def __init__(self, **kwargs):
        now = datetime.datetime.utcnow().strftime("%d %b %Y").upper()
        super().__init__(
            orientation='horizontal',
            size_hint_y=None,
            height=dp(24),
            padding=(dp(14), dp(4)),
            spacing=dp(8),
            **kwargs,
        )
        line_l = Widget()
        with line_l.canvas:
            Color(*CHAT_BORDER)
            Rectangle(pos=(0, dp(12)), size=(1000, dp(1)))
        self.add_widget(line_l)

        self.add_widget(_make_label(
            f"SESSION START · {now}",
            color=CHAT_G2, font_size=9,
            size_hint_x=None, size_hint_y=None,
            height=24, width=dp(200), halign='center',
        ))

        line_r = Widget()
        with line_r.canvas:
            Color(*CHAT_BORDER)
            Rectangle(pos=(0, dp(12)), size=(1000, dp(1)))
        self.add_widget(line_r)


class _InputArea(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(
            orientation='vertical',
            size_hint_y=None,
            height=dp(90),
            padding=(dp(14), dp(8)),
            spacing=dp(6),
            **kwargs,
        )
        _rgba_bg(self, CHAT_BG1)
        _draw_top_border(self, CHAT_BORDER)
        self._screen: typing.Optional['ChatScreen'] = None
        self.urgent_active = False
        self.grid_active = False

        # Flag row
        flag_row = BoxLayout(size_hint_y=None, height=dp(24), spacing=dp(6))
        self._urgent_btn = _make_btn("⚠ URGENT", bg_color=(0, 0, 0, 0),
                                     text_color=CHAT_G3, font_size=10,
                                     height=24, width=80)
        self._urgent_btn.bind(on_release=self._toggle_urgent)
        flag_row.add_widget(self._urgent_btn)

        self._grid_btn = _make_btn("⊕ GRID", bg_color=(0, 0, 0, 0),
                                   text_color=CHAT_G3, font_size=10,
                                   height=24, width=70)
        self._grid_btn.bind(on_release=self._toggle_grid)
        flag_row.add_widget(self._grid_btn)

        flag_row.add_widget(Widget())  # spacer

        self._status_lbl = _make_label("", color=CHAT_G2, font_size=9,
                                        size_hint_x=None, size_hint_y=None,
                                        height=24, width=dp(160), halign='right')
        flag_row.add_widget(self._status_lbl)
        self.add_widget(flag_row)

        # Grid input (hidden by default)
        self._grid_row = BoxLayout(size_hint_y=None, height=dp(0), opacity=0)
        self._grid_input = TextInput(
            hint_text="38T LN XXXXX XXXXX",
            hint_text_color=CHAT_G2,
            foreground_color=CHAT_G5,
            background_color=CHAT_BG3,
            cursor_color=CHAT_G5,
            font_size=dp(11),
            multiline=False,
            size_hint_x=None,
            width=dp(220),
            size_hint_y=None,
            height=dp(28),
        )
        self._grid_row.add_widget(self._grid_input)
        self.add_widget(self._grid_row)

        # Input row
        input_row = BoxLayout(size_hint_y=None, height=dp(36), spacing=dp(8))
        self._msg_input = TextInput(
            hint_text="ENTER MESSAGE...",
            hint_text_color=CHAT_G2,
            foreground_color=CHAT_G5,
            background_color=CHAT_BG3,
            cursor_color=CHAT_G5,
            font_size=dp(11),
            multiline=False,
            size_hint_y=None,
            height=dp(36),
        )
        input_row.add_widget(self._msg_input)

        self._send_btn = _make_btn("SEND ▶", bg_color=CHAT_G2, text_color=CHAT_G6,
                                   font_size=12, height=36, width=80)
        self._send_btn.bold = True
        self._send_btn.bind(on_release=self._on_send)
        input_row.add_widget(self._send_btn)
        self.add_widget(input_row)

        Clock.schedule_once(self._update_status)
        Clock.schedule_interval(self._update_status, 30)

    def wire(self, screen: 'ChatScreen'):
        self._screen = screen

    def _toggle_urgent(self, *_):
        self.urgent_active = not self.urgent_active
        if self.urgent_active:
            self._urgent_btn.background_color = (0.706, 0.314, 0.0, 0.12)
            self._urgent_btn.color = CHAT_AMBER2
            self._msg_input.hint_text = "URGENT — ENTER MESSAGE..."
            self._msg_input.foreground_color = CHAT_AMBER2
        else:
            self._urgent_btn.background_color = (0, 0, 0, 0)
            self._urgent_btn.color = CHAT_G3
            self._msg_input.hint_text = "ENTER MESSAGE..."
            self._msg_input.foreground_color = CHAT_G5

    def _toggle_grid(self, *_):
        self.grid_active = not self.grid_active
        if self.grid_active:
            self._grid_row.height = dp(34)
            self._grid_row.opacity = 1
            self.height = dp(124)
            self._grid_btn.background_color = (0.706, 0.314, 0.0, 0.12)
            self._grid_btn.color = CHAT_AMBER2
        else:
            self._grid_row.height = dp(0)
            self._grid_row.opacity = 0
            self.height = dp(90)
            self._grid_btn.background_color = (0, 0, 0, 0)
            self._grid_btn.color = CHAT_G3
            self._grid_input.text = ""

    def _update_status(self, *_):
        app = App.get_running_app()
        callsign = "—"
        role = ""
        if app.core_session.is_unlocked:
            try:
                current = app.core_session.read_model("chat.current_operator")
                callsign = current["callsign"]
                role = current.get("role", "")
            except Exception:
                pass
        ts = datetime.datetime.now().strftime("%H:%M")
        self._status_lbl.text = f"{callsign} · {role} · {ts}" if role else f"{callsign} · {ts}"

    def _on_send(self, *_):
        if self._screen:
            self._screen.on_send_pressed()

    @property
    def grid_ref_text(self) -> str:
        return self._grid_input.text.strip()

    @property
    def message_text(self) -> str:
        return self._msg_input.text.strip()

    def clear(self):
        self._msg_input.text = ""
        if self.grid_active:
            self._grid_input.text = ""


# ---------------------------------------------------------------------------
# Message Row
# ---------------------------------------------------------------------------

class _MessageRow(BoxLayout):
    def __init__(self, msg, callsign: str, **kwargs):
        super().__init__(
            orientation='vertical',
            size_hint_y=None,
            padding=(dp(14), dp(6), dp(14), dp(6)),
            spacing=dp(2),
            **kwargs,
        )
        body_text = (msg.body.decode("utf-8", errors="replace")
                     if isinstance(msg.body, bytes) else str(msg.body))
        is_urgent = bool(msg.is_urgent)

        # Background + left border for urgent messages
        with self.canvas.before:
            if is_urgent:
                Color(0.706, 0.235, 0.0, 0.06)
            else:
                Color(0, 0, 0, 0)
            self._bg_rect = Rectangle(pos=self.pos, size=self.size)
            if is_urgent:
                Color(*CHAT_AMBER2)
                self._border_rect = Rectangle(pos=self.pos, size=(dp(2), self.height))
        self.bind(pos=self._update_canvas, size=self._update_canvas)

        # Header: timestamp · callsign · role · [URGENT]
        header = BoxLayout(
            orientation='horizontal', size_hint_y=None, height=dp(18), spacing=dp(8)
        )
        header.add_widget(_make_label(
            _ts_to_local(msg.sent_at), color=CHAT_G3, font_size=9,
            size_hint_x=None, size_hint_y=None, height=18, width=dp(48),
        ))
        header.add_widget(_make_label(
            callsign, color=CHAT_G6, font_size=11, bold=True,
            size_hint_x=None, size_hint_y=None, height=18, width=dp(100),
        ))

        # Role from the message — we don't store it separately so leave blank for now
        if is_urgent:
            self._urgent_tag = _make_label(
                "⚠ URGENT", color=CHAT_AMBER2, font_size=9, bold=True,
                size_hint_x=None, size_hint_y=None, height=18, width=dp(70),
            )
            self._blink_ev = _start_blink(self._urgent_tag)
            header.add_widget(self._urgent_tag)

        self.add_widget(header)

        # Body
        body_color = CHAT_AMBER2 if is_urgent else CHAT_G4
        body_lbl = Label(
            text=body_text,
            color=body_color,
            font_size=_fs(11),
            halign='left',
            valign='top',
            size_hint_y=None,
        )
        body_lbl.bind(
            width=lambda w, _: setattr(w, 'text_size', (w.width, None)),
            texture_size=lambda w, ts: setattr(w, 'height', ts[1]),
        )
        self.add_widget(body_lbl)
        self.height = dp(46)  # will grow with content via texture_size

        # Grid pill
        if msg.grid_ref:
            pill = _GridPill(msg.grid_ref)
            self.add_widget(pill)
            self.height += dp(26)

    def _update_canvas(self, *_):
        self._bg_rect.pos = self.pos
        self._bg_rect.size = self.size
        if hasattr(self, '_border_rect'):
            self._border_rect.pos = self.pos
            self._border_rect.size = (dp(2), self.height)


class _GridPill(BoxLayout):
    def __init__(self, grid_ref: str, **kwargs):
        super().__init__(
            orientation='horizontal',
            size_hint_y=None,
            height=dp(22),
            size_hint_x=None,
            width=dp(220),
            padding=(dp(6), dp(3)),
            spacing=dp(4),
            **kwargs,
        )
        with self.canvas.before:
            Color(*CHAT_BG3)
            self._bg = Rectangle(pos=self.pos, size=self.size)
            Color(*CHAT_G1)
            self._border = Line(rectangle=(self.x, self.y, self.width, self.height), width=1)
        self.bind(pos=self._update, size=self._update)

        self.add_widget(_make_label(
            "⊕", color=CHAT_G4, font_size=10,
            size_hint_x=None, size_hint_y=None, height=16, width=dp(16),
        ))
        self.add_widget(_make_label(
            grid_ref, color=CHAT_G5, font_size=10,
            size_hint_y=None, height=16,
        ))

    def _update(self, *_):
        self._bg.pos = self.pos
        self._bg.size = self.size
        self._border.rectangle = (self.x, self.y, self.width, self.height)


# ---------------------------------------------------------------------------
# Right Panel
# ---------------------------------------------------------------------------

class _RightPanel(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(orientation='vertical', size_hint_x=None, width=dp(210), **kwargs)
        _rgba_bg(self, CHAT_BG1)
        _draw_left_border(self, CHAT_BORDER, thickness=1)

        # Operators section header
        op_header = _RpHeader("OPERATORS", "0/0 ONLINE")
        self._op_count_lbl = op_header.count_lbl
        self.add_widget(op_header)

        # Operators list
        self._op_scroll = ScrollView(size_hint_y=None, height=dp(200))
        self._op_layout = GridLayout(cols=1, size_hint_y=None, spacing=0)
        self._op_layout.bind(minimum_height=self._op_layout.setter('height'))
        self._op_scroll.add_widget(self._op_layout)
        self.add_widget(self._op_scroll)

        # Alerts section header
        alert_header = _RpHeader("ALERT FEED", "0")
        self._alert_count_lbl = alert_header.count_lbl
        self.add_widget(alert_header)

        # Alert list
        self._alert_scroll = ScrollView(
            bar_width=dp(2), bar_color=CHAT_G1, bar_inactive_color=(0, 0, 0, 0)
        )
        self._alert_layout = GridLayout(cols=1, size_hint_y=None, spacing=0)
        self._alert_layout.bind(minimum_height=self._alert_layout.setter('height'))
        self._alert_scroll.add_widget(self._alert_layout)
        self.add_widget(self._alert_scroll)

    def populate_operators(self, operators: list):
        self._op_layout.clear_widgets()
        online = [o for o in operators if o.get('online')]
        offline = [o for o in operators if not o.get('online')]
        self._op_count_lbl.text = f"{len(online)}/{len(operators)} ONLINE"
        for op in online + offline:
            self._op_layout.add_widget(_OperatorRow(op))

    def populate_alerts(self, alerts: list):
        self._alert_layout.clear_widgets()
        self._alert_count_lbl.text = str(len(alerts))
        for alert in alerts:
            self._alert_layout.add_widget(_AlertRow(alert))


class _RpHeader(BoxLayout):
    def __init__(self, title: str, count: str, **kwargs):
        super().__init__(
            orientation='horizontal',
            size_hint_y=None,
            height=dp(32),
            padding=(dp(12), dp(6)),
            **kwargs,
        )
        _rgba_bg(self, CHAT_BG1)
        _draw_bottom_border(self, CHAT_BORDER)

        self.add_widget(_make_label(
            title, color=CHAT_G4, font_size=10, bold=True,
            size_hint_y=None, height=20,
        ))
        self.count_lbl = _make_label(
            count, color=CHAT_G3, font_size=9,
            size_hint_x=None, size_hint_y=None,
            height=20, width=dp(80), halign='right',
        )
        self.add_widget(self.count_lbl)


class _OperatorRow(BoxLayout):
    def __init__(self, op: dict, **kwargs):
        super().__init__(
            orientation='horizontal',
            size_hint_y=None,
            height=dp(26),
            padding=(dp(12), dp(4)),
            spacing=dp(6),
            **kwargs,
        )
        online = op.get('online', False)
        dot_color = CHAT_G5 if online else CHAT_G2
        callsign_color = CHAT_G5 if online else CHAT_G2
        role_color = CHAT_G3 if online else CHAT_G1

        dot = Widget(size_hint=(None, None), size=(dp(8), dp(8)))
        with dot.canvas:
            Color(*dot_color)
            self._dot_rect = Rectangle(size=(dp(6), dp(6)))
        dot.bind(pos=lambda w, p: setattr(self._dot_rect, 'pos', (p[0] + dp(1), p[1] + dp(1))))
        self.add_widget(dot)

        self.add_widget(_make_label(
            op.get('callsign', '—'), color=callsign_color, font_size=10, bold=True,
            size_hint_y=None, height=18,
        ))
        self.add_widget(_make_label(
            op.get('role', ''), color=role_color, font_size=9,
            size_hint_x=None, size_hint_y=None,
            height=18, width=dp(52), halign='right',
        ))


class _AlertRow(BoxLayout):
    def __init__(self, alert: dict, **kwargs):
        super().__init__(
            orientation='vertical',
            size_hint_y=None,
            height=dp(52),
            padding=(dp(12), dp(6)),
            spacing=dp(2),
            **kwargs,
        )
        _draw_bottom_border(self, CHAT_BORDER)

        atype = alert.get('type', 'ops')
        type_colors = {
            'contact': CHAT_RED2,
            'medevac': CHAT_AMBER2,
        }
        label_color = type_colors.get(atype, CHAT_G4)

        header_row = BoxLayout(size_hint_y=None, height=dp(16), spacing=dp(4))
        header_row.add_widget(_make_label(
            alert.get('label', 'INTEL'), color=label_color, font_size=9, bold=True,
            size_hint_x=None, size_hint_y=None, height=16, width=dp(70),
        ))
        header_row.add_widget(_make_label(
            alert.get('time', ''), color=CHAT_G2, font_size=9,
            size_hint_y=None, height=16,
        ))
        self.add_widget(header_row)

        text_lbl = Label(
            text=alert.get('text', ''),
            color=CHAT_G3,
            font_size=_fs(9),
            halign='left',
            valign='top',
            size_hint_y=None,
            height=dp(30),
        )
        text_lbl.bind(width=lambda w, _: setattr(w, 'text_size', (w.width, None)))
        self.add_widget(text_lbl)


# ---------------------------------------------------------------------------

class ChatScreen(MDScreen):
    """4-pane tactical chat screen. Layout built entirely in Python."""

    def on_kv_post(self, base_widget) -> None:
        self._active_channel = None
        self._build_layout()

    def _build_layout(self) -> None:
        self.clear_widgets()
        root = BoxLayout(orientation='horizontal')
        self._channel_panel = _ChannelPanel()
        self._chat_area = _ChatArea()
        self._right_panel = _RightPanel()
        root.add_widget(self._channel_panel)
        root.add_widget(self._chat_area)
        root.add_widget(self._right_panel)
        self.add_widget(root)

        self._channel_panel.wire(self, self._on_channel_selected)
        self._chat_area.wire(self)

    def on_ui_theme_changed(self) -> None:
        self._build_layout()
        if self.manager and self.manager.current == self.name:
            self.on_pre_enter()

    def on_pre_enter(self) -> None:
        app = App.get_running_app()
        app.clear_badge("chat")
        if not app.core_session.is_unlocked:
            return
        try:
            app.core_session.command("chat.ensure_defaults")
        except Exception as exc:
            _log.error("ensure_default_channels failed: %s", exc)
        self._load_channels()
        self._refresh_operators()
        self._refresh_alerts()
        self._update_footer()

    def on_back_pressed(self) -> None:
        self.manager.current = "main"

    # ------------------------------------------------------------------
    # Channel loading
    # ------------------------------------------------------------------

    def _load_channels(self) -> None:
        app = App.get_running_app()
        if not app.core_session.is_unlocked:
            return
        try:
            channels = app.core_session.read_model("chat.channels")
        except Exception as exc:
            _log.error("Failed to load channels: %s", exc)
            return

        active_id = self._active_channel.id if self._active_channel else None
        self._channel_panel.populate(channels, active_id)

        if not channels:
            return

        # Select the previously active channel, or default to first
        if self._active_channel is not None:
            still_there = next((c for c in channels if c.id == self._active_channel.id), None)
            if still_there:
                self._active_channel = still_there
                self._load_messages()
                return

        self._active_channel = channels[0]
        self._load_messages()

    def _on_channel_selected(self, channel) -> None:
        self._active_channel = channel
        self._load_messages()

    # ------------------------------------------------------------------
    # Message loading
    # ------------------------------------------------------------------

    def _load_messages(self) -> None:
        app = App.get_running_app()
        if not app.core_session.is_unlocked or self._active_channel is None:
            return
        try:
            entries = app.core_session.read_model(
                "chat.messages",
                {"channel_id": self._active_channel.id},
            )
        except Exception as exc:
            _log.error("Failed to load messages: %s", exc)
            return
        self._chat_area.show_channel(self._active_channel, entries)

    # ------------------------------------------------------------------
    # Send
    # ------------------------------------------------------------------

    def on_send_pressed(self) -> None:
        chat_area = self._chat_area
        body = chat_area.message_text
        if not body:
            return
        app = App.get_running_app()
        if not app.core_session.is_unlocked or self._active_channel is None:
            return
        try:
            grid = chat_area.grid_ref_text if chat_area.grid_active else None
            result = app.core_session.command(
                "chat.send_message",
                channel_id=self._active_channel.id,
                body=body,
                is_urgent=chat_area.urgent_active,
                grid_ref=grid,
            )
            chat_area.clear_input()

            callsign = self._get_my_callsign(app)
            chat_area.append_message(result.message, callsign)
            self._refresh_alerts()
        except Exception as exc:
            _log.error("Failed to send message: %s", exc)

    def _get_my_operator_id(self, app) -> int:
        return app.require_local_operator_id(
            allow_server_sentinel=(app.mode == "server")
        )

    def _get_my_callsign(self, app) -> str:
        try:
            return app.core_session.read_model("chat.current_operator")["callsign"]
        except Exception:
            pass
        return "UNKNOWN"

    # ------------------------------------------------------------------
    # Operators panel
    # ------------------------------------------------------------------

    def _refresh_operators(self) -> None:
        app = App.get_running_app()
        if not app.core_session.is_unlocked:
            return
        try:
            operators = app.core_session.read_model(
                "chat.operators",
                {"online_peers": getattr(app, "_online_peers", set())},
            )
            self._right_panel.populate_operators(operators)
        except Exception as exc:
            _log.error("Failed to load operators: %s", exc)

    # ------------------------------------------------------------------
    # Alert feed
    # ------------------------------------------------------------------

    def _refresh_alerts(self) -> None:
        app = App.get_running_app()
        if not app.core_session.is_unlocked:
            return
        try:
            alerts = [
                {
                    **alert,
                    "time": _ts_to_local(alert["sent_at"]),
                }
                for alert in app.core_session.read_model("chat.alerts")
            ]
            self._right_panel.populate_alerts(alerts)
        except Exception as exc:
            _log.error("Failed to load alerts: %s", exc)

    # ------------------------------------------------------------------
    # Footer
    # ------------------------------------------------------------------

    def _update_footer(self) -> None:
        app = App.get_running_app()
        callsign = "—"
        role = ""
        if app.core_session.is_unlocked:
            try:
                current = app.core_session.read_model("chat.current_operator")
                callsign = current["callsign"]
                role = current.get("role", "")
            except Exception:
                pass
        self._channel_panel.update_footer(callsign, role)

    # ------------------------------------------------------------------
    # New channel / DM dialogs (preserved from previous implementation)
    # ------------------------------------------------------------------

    def on_new_channel_pressed(self) -> None:
        modal = ModalView(size_hint=(0.4, None), height=dp(220), auto_dismiss=False)
        from kivy.uix.boxlayout import BoxLayout as _BL
        from kivy.uix.label import Label as _Lbl
        from kivy.uix.textinput import TextInput as _TI
        from kivy.uix.button import Button as _Btn
        content = _BL(orientation="vertical", padding=dp(20), spacing=dp(12))
        content.add_widget(_Lbl(text="New Channel", bold=True,
                                 size_hint_y=None, height=dp(32), halign="center"))
        name_field = _TI(hint_text="Channel name (e.g. ops-north)",
                          multiline=False, size_hint_y=None, height=dp(36))
        content.add_widget(name_field)
        btn_row = _BL(orientation="horizontal", size_hint_y=None, height=dp(48), spacing=dp(8))
        cancel = _Btn(text="CANCEL")
        cancel.bind(on_release=lambda _: modal.dismiss())
        create = _Btn(text="CREATE")
        create.bind(on_release=lambda _: self._do_create_channel(modal, name_field.text))
        btn_row.add_widget(cancel)
        btn_row.add_widget(create)
        content.add_widget(btn_row)
        modal.add_widget(content)
        modal.open()

    def _do_create_channel(self, modal: ModalView, name: str) -> None:
        name = name.strip()
        if not name:
            return
        app = App.get_running_app()
        if not app.core_session.is_unlocked:
            return
        try:
            app.core_session.command("chat.create_channel", name=name)
            modal.dismiss()
            self._load_channels()
        except Exception as exc:
            _log.error("Failed to create channel: %s", exc)

    # ------------------------------------------------------------------
    # Delete message (server operator only, long-press hook)
    # ------------------------------------------------------------------

    def _confirm_delete_message(self, message_id: int) -> None:
        modal = ModalView(size_hint=(0.45, None), height=dp(160), auto_dismiss=False)
        from kivy.uix.boxlayout import BoxLayout as _BL
        from kivy.uix.label import Label as _Lbl
        from kivy.uix.button import Button as _Btn
        content = _BL(orientation="vertical", padding=dp(20), spacing=dp(12))
        content.add_widget(_Lbl(text="Delete this message?\nThis cannot be undone.",
                                 halign="center", size_hint_y=None, height=dp(56)))
        btn_row = _BL(orientation="horizontal", size_hint_y=None, height=dp(48), spacing=dp(8))
        cancel = _Btn(text="CANCEL")
        cancel.bind(on_release=lambda _: modal.dismiss())
        delete = _Btn(text="DELETE")
        delete.bind(on_release=lambda _: self._do_delete_message(modal, message_id))
        btn_row.add_widget(cancel)
        btn_row.add_widget(delete)
        content.add_widget(btn_row)
        modal.add_widget(content)
        modal.open()

    def _do_delete_message(self, modal: ModalView, message_id: int) -> None:
        app = App.get_running_app()
        if not app.core_session.is_unlocked:
            return
        try:
            app.core_session.command("chat.delete_message", message_id=message_id)
            modal.dismiss()
            self._load_messages()
        except Exception as exc:
            _log.error("Failed to delete message: %s", exc)
