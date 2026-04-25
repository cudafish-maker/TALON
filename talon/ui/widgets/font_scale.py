"""
Shared font-scale popup widget used by all screens that support text resizing.

Each screen keeps its own module-level scale variable and _fs() helper (so
its _lbl/_btn factories close over the right global).  This module owns the
popup widget, the step list, and the DB-persist logic — the only things that
were identical across every screen.

Usage
-----
    from talon.ui.widgets.font_scale import FontScalePopup, FONT_SCALE_STEPS, FONT_SCALE_LABELS

    # module level in the screen file:
    _MY_SCALE: float = 1.0

    def _set_my_scale(s: float) -> None:
        global _MY_SCALE
        _MY_SCALE = s

    # inside _show_font_popup:
    popup = FontScalePopup(
        get_scale  = lambda: _MY_SCALE,
        set_scale  = _set_my_scale,
        meta_key   = 'my_screen_font_scale',
        on_apply   = self._rebuild_content,
        on_dismiss = self._hide_font_popup,
    )
"""
import typing

from kivy.app import App
from kivy.graphics import Color, Line, Rectangle
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label

from talon.ui.theme import (
    CHAT_BG2, CHAT_BG3, CHAT_BG4,
    CHAT_G2, CHAT_G4, CHAT_G5, CHAT_G6,
)

FONT_SCALE_STEPS:  list[float] = [1.0, 1.15, 1.30, 1.50]
FONT_SCALE_LABELS: list[str]   = ["100%", "115%", "130%", "150%"]


class FontScalePopup(BoxLayout):
    """Small overlay with 4 discrete text-size steps.

    Dismissed automatically when a touch lands outside the widget.

    Parameters
    ----------
    get_scale:  returns the current scale value from the caller's module global.
    set_scale:  writes a new scale value to the caller's module global.
    meta_key:   key used to persist the chosen scale in the ``meta`` DB table.
    on_apply:   called after scale is written; should rebuild/refresh the screen.
    on_dismiss: called when an outside touch is detected (hide the popup).
    """

    def __init__(
        self,
        get_scale:  typing.Callable[[], float],
        set_scale:  typing.Callable[[float], None],
        meta_key:   str,
        on_apply:   typing.Callable[[], None],
        on_dismiss: typing.Callable[[], None],
        **kwargs,
    ):
        super().__init__(
            orientation='vertical',
            size_hint=(None, None),
            width=dp(140),
            spacing=dp(4),
            padding=(dp(8), dp(8)),
            **kwargs,
        )
        self._get_scale  = get_scale
        self._set_scale  = set_scale
        self._meta_key   = meta_key
        self._on_apply   = on_apply
        self._on_dismiss = on_dismiss

        with self.canvas.before:
            Color(*CHAT_BG2)
            self._bg = Rectangle(pos=self.pos, size=self.size)
            Color(*CHAT_G2)
            self._border = Line(rectangle=(self.x, self.y, self.width, self.height), width=1)
        self.bind(pos=self._upd_canvas, size=self._upd_canvas)
        self.height = dp(8 + 8 + 4 * 28 + 3 * 4 + 20)

        title = Label(
            text='TEXT SIZE', color=CHAT_G5, font_size=dp(10), bold=True,
            size_hint_y=None, height=dp(20), halign='center',
        )
        title.bind(size=title.setter('text_size'))
        self.add_widget(title)

        current = get_scale()
        self._btns: list[Button] = []
        for i, lbl in enumerate(FONT_SCALE_LABELS):
            active = abs(FONT_SCALE_STEPS[i] - current) < 0.01
            btn = Button(
                text=lbl, font_size=dp(11),
                size_hint_y=None, height=dp(28),
                background_normal='',
                background_color=CHAT_BG4 if active else CHAT_BG3,
                color=CHAT_G6 if active else CHAT_G4,
            )
            step = FONT_SCALE_STEPS[i]
            btn.bind(on_release=lambda _, s=step: self._apply(s))
            self._btns.append(btn)
            self.add_widget(btn)

    def _upd_canvas(self, *_) -> None:
        self._bg.pos = self.pos
        self._bg.size = self.size
        self._border.rectangle = (self.x, self.y, self.width, self.height)

    def _apply(self, scale: float) -> None:
        self._set_scale(scale)
        app = App.get_running_app()
        if app.conn:
            try:
                app.conn.execute(
                    "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                    (self._meta_key, str(scale)),
                )
                app.conn.commit()
            except Exception:
                pass
        for i, btn in enumerate(self._btns):
            active = abs(FONT_SCALE_STEPS[i] - scale) < 0.01
            btn.background_color = CHAT_BG4 if active else CHAT_BG3
            btn.color = CHAT_G6 if active else CHAT_G4
        self._on_apply()

    def on_touch_down(self, touch):
        if not self.collide_point(*touch.pos):
            self._on_dismiss()
            return False
        return super().on_touch_down(touch)
