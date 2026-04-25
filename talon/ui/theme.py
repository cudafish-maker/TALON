"""
KivyMD dark tactical theme constants and selectable UI palettes.

Apply at app startup:
    from talon.ui.theme import apply_theme
    apply_theme(self)   # self = MDApp instance
"""
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from kivymd.app import MDApp

RGBA = tuple[float, float, float, float]

THEME_META_KEY = "global_theme"
DEFAULT_THEME_KEY = "phosphor"


class ThemeColor(Sequence[float]):
    """Mutable RGBA token used by screens that imported constants directly."""

    def __init__(self, name: str, rgba: RGBA = (0, 0, 0, 1)) -> None:
        self.name = name
        self._rgba = rgba

    def set(self, rgba: RGBA) -> None:
        if len(rgba) != 4:
            raise ValueError(f"{self.name} requires 4 RGBA components")
        self._rgba = tuple(float(component) for component in rgba)  # type: ignore[assignment]

    def as_tuple(self) -> RGBA:
        return self._rgba

    def __iter__(self) -> Iterator[float]:
        return iter(self._rgba)

    def __len__(self) -> int:
        return 4

    def __getitem__(self, index):
        return self._rgba[index]

    def __repr__(self) -> str:
        return repr(self._rgba)


@dataclass(frozen=True)
class ThemeDefinition:
    key: str
    label: str
    primary_palette: str
    primary_hue: str
    accent_palette: str
    colors: dict[str, RGBA]


_ALERT_COLORS: dict[str, RGBA] = {
    "COLOR_ACCENT": (1.00, 0.76, 0.03, 1),      # Amber A400
    "COLOR_DANGER": (0.86, 0.15, 0.15, 1),      # tactical red
    "CHAT_RED": (0.753, 0.188, 0.000, 1),       # #c03000 — badge bg
    "CHAT_RED2": (1.000, 0.267, 0.000, 1),      # #ff4400 — emergency text
    "CHAT_AMBER": (0.722, 0.471, 0.000, 1),     # #b87800 — urgent bg
    "CHAT_AMBER2": (1.000, 0.667, 0.000, 1),    # #ffaa00 — urgent text
}


_THEMES: dict[str, ThemeDefinition] = {
    "phosphor": ThemeDefinition(
        key="phosphor",
        label="Tactical Green",
        primary_palette="Green",
        primary_hue="700",
        accent_palette="Amber",
        colors={
            **_ALERT_COLORS,
            "COLOR_BG": (0.07, 0.07, 0.07, 1),
            "COLOR_SURFACE": (0.12, 0.12, 0.12, 1),
            "COLOR_PRIMARY": (0.18, 0.49, 0.20, 1),
            "COLOR_TEXT": (0.92, 0.92, 0.92, 1),
            "COLOR_TEXT_SECONDARY": (0.60, 0.60, 0.60, 1),
            "CHAT_BG0": (0.016, 0.031, 0.016, 1),   # #040804 — app bg
            "CHAT_BG1": (0.031, 0.055, 0.031, 1),   # #080e08 — panel bg
            "CHAT_BG2": (0.047, 0.078, 0.047, 1),   # #0c140c — surface / hover
            "CHAT_BG3": (0.067, 0.102, 0.067, 1),   # #111a11 — input / item hover
            "CHAT_BG4": (0.086, 0.125, 0.086, 1),   # #162016 — active channel
            "CHAT_G1": (0.110, 0.188, 0.110, 1),    # #1c301c — subtle borders
            "CHAT_G2": (0.153, 0.271, 0.153, 1),    # #274527 — dim / offline
            "CHAT_G3": (0.227, 0.431, 0.227, 1),    # #3a6e3a — secondary text
            "CHAT_G4": (0.322, 0.627, 0.322, 1),    # #52a052 — primary text
            "CHAT_G5": (0.471, 0.784, 0.471, 1),    # #78c878 — active / online
            "CHAT_G6": (0.690, 0.941, 0.690, 1),    # #b0f0b0 — highlights
            "CHAT_BORDER": (0.090, 0.133, 0.090, 1),# #172217 — dividers
        },
    ),
    "readable": ThemeDefinition(
        key="readable",
        label="Readable Dark",
        primary_palette="Blue",
        primary_hue="700",
        accent_palette="Amber",
        colors={
            **_ALERT_COLORS,
            "COLOR_BG": (0.055, 0.059, 0.067, 1),          # #0e0f11
            "COLOR_SURFACE": (0.110, 0.122, 0.145, 1),     # #1c1f25
            "COLOR_PRIMARY": (0.267, 0.522, 0.847, 1),     # readable blue
            "COLOR_TEXT": (0.900, 0.925, 0.950, 1),
            "COLOR_TEXT_SECONDARY": (0.650, 0.690, 0.735, 1),
            "CHAT_BG0": (0.055, 0.059, 0.067, 1),
            "CHAT_BG1": (0.086, 0.098, 0.118, 1),
            "CHAT_BG2": (0.118, 0.137, 0.165, 1),
            "CHAT_BG3": (0.153, 0.176, 0.212, 1),
            "CHAT_BG4": (0.188, 0.220, 0.267, 1),
            "CHAT_G1": (0.235, 0.267, 0.318, 1),
            "CHAT_G2": (0.545, 0.588, 0.647, 1),
            "CHAT_G3": (0.680, 0.720, 0.775, 1),
            "CHAT_G4": (0.835, 0.870, 0.910, 1),
            "CHAT_G5": (0.420, 0.660, 0.950, 1),
            "CHAT_G6": (0.965, 0.975, 0.990, 1),
            "CHAT_BORDER": (0.235, 0.263, 0.310, 1),
        },
    ),
}


_COLOR_TOKEN_NAMES = (
    "COLOR_BG", "COLOR_SURFACE", "COLOR_PRIMARY", "COLOR_ACCENT",
    "COLOR_DANGER", "COLOR_TEXT", "COLOR_TEXT_SECONDARY",
    "CHAT_BG0", "CHAT_BG1", "CHAT_BG2", "CHAT_BG3", "CHAT_BG4",
    "CHAT_G1", "CHAT_G2", "CHAT_G3", "CHAT_G4", "CHAT_G5", "CHAT_G6",
    "CHAT_RED", "CHAT_RED2", "CHAT_AMBER", "CHAT_AMBER2", "CHAT_BORDER",
)


_COLOR_TOKENS: dict[str, ThemeColor] = {
    name: ThemeColor(name) for name in _COLOR_TOKEN_NAMES
}

globals().update(_COLOR_TOKENS)

PRIMARY_PALETTE = "Green"
PRIMARY_HUE = "700"
ACCENT_PALETTE = "Amber"
_active_theme_key = DEFAULT_THEME_KEY

# SITREP severity colours — maps SITREP_LEVELS to RGBA
SITREP_COLORS: dict[str, Sequence[float]] = {
    "ROUTINE":        COLOR_PRIMARY,
    "PRIORITY":       (0.13, 0.59, 0.95, 1),   # blue
    "IMMEDIATE":      COLOR_ACCENT,
    "FLASH":          COLOR_DANGER,
    "FLASH_OVERRIDE": (0.60, 0.00, 0.80, 1),   # purple — maximum severity
}


def _normalise_theme_key(theme_key: str | None) -> str:
    key = (theme_key or "").strip().lower()
    return key if key in _THEMES else DEFAULT_THEME_KEY


def set_ui_theme(theme_key: str | None) -> str:
    """Switch the active in-memory UI palette and return the normalized key."""
    global PRIMARY_PALETTE, PRIMARY_HUE, ACCENT_PALETTE, _active_theme_key

    key = _normalise_theme_key(theme_key)
    definition = _THEMES[key]
    _active_theme_key = key
    PRIMARY_PALETTE = definition.primary_palette
    PRIMARY_HUE = definition.primary_hue
    ACCENT_PALETTE = definition.accent_palette
    for name, token in _COLOR_TOKENS.items():
        token.set(definition.colors[name])
    return key


def get_ui_theme_key() -> str:
    return _active_theme_key


def get_ui_theme_label(theme_key: str | None = None) -> str:
    key = _normalise_theme_key(theme_key) if theme_key is not None else _active_theme_key
    return _THEMES[key].label


def available_ui_themes() -> tuple[tuple[str, str], ...]:
    return tuple((definition.key, definition.label) for definition in _THEMES.values())


def load_ui_theme_from_db(conn) -> str:
    """Load and apply the persisted UI theme from the encrypted meta table."""
    if conn is None:
        return set_ui_theme(DEFAULT_THEME_KEY)
    try:
        row = conn.execute(
            "SELECT value FROM meta WHERE key=?", (THEME_META_KEY,)
        ).fetchone()
    except Exception:
        row = None
    return set_ui_theme(row[0] if row else DEFAULT_THEME_KEY)


def save_ui_theme_to_db(conn, theme_key: str | None) -> str:
    """Persist and apply the selected UI theme."""
    key = set_ui_theme(theme_key)
    if conn is not None:
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
            (THEME_META_KEY, key),
        )
        conn.commit()
    return key


def apply_theme(app: "MDApp") -> None:
    """
    Configure KivyMD dark tactical theme on the MDApp instance.
    Call once in TalonApp.build() before returning the root widget.
    """
    app.theme_cls.theme_style = "Dark"
    app.theme_cls.primary_palette = PRIMARY_PALETTE
    app.theme_cls.primary_hue = PRIMARY_HUE
    app.theme_cls.accent_palette = ACCENT_PALETTE
    try:
        from kivy.core.window import Window
        Window.clearcolor = COLOR_BG.as_tuple()
    except Exception:
        pass


set_ui_theme(DEFAULT_THEME_KEY)
