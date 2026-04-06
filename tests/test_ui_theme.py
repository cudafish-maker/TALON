# tests/test_ui_theme.py
# Tests for talon/ui/theme.py — color palette, constants, color maps.

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from talon.ui.theme import (
    BG_BASE, BG_DARK, BG_SURFACE, BG_ELEVATED,
    COLOR_PRIMARY, COLOR_AMBER, COLOR_RED, COLOR_BLUE,
    TEXT_PRIMARY, TEXT_SECONDARY, TEXT_DISABLED,
    BORDER_SUBTLE, BORDER_ACTIVE,
    IMPORTANCE_COLORS, TRANSPORT_COLORS,
    KIVYMD_THEME, DESKTOP_MIN_WIDTH,
    FONT_MONO, FONT_SANS,
    PADDING_SM, PADDING_MD, PADDING_LG,
    RADIUS_SM, RADIUS_MD,
    TOUCH_TARGET,
)


# ---------- Color format validation ----------

def _is_valid_hex(color: str) -> bool:
    """Check that a color string is #RRGGBB format."""
    if not color.startswith("#") or len(color) != 7:
        return False
    try:
        int(color[1:], 16)
        return True
    except ValueError:
        return False


def test_background_colors_are_valid_hex():
    for color in [BG_BASE, BG_DARK, BG_SURFACE, BG_ELEVATED]:
        assert _is_valid_hex(color), f"Invalid hex: {color}"


def test_accent_colors_are_valid_hex():
    for color in [COLOR_PRIMARY, COLOR_AMBER, COLOR_RED, COLOR_BLUE]:
        assert _is_valid_hex(color), f"Invalid hex: {color}"


def test_text_colors_are_valid_hex():
    for color in [TEXT_PRIMARY, TEXT_SECONDARY, TEXT_DISABLED]:
        assert _is_valid_hex(color), f"Invalid hex: {color}"


def test_border_colors_are_valid_hex():
    for color in [BORDER_SUBTLE, BORDER_ACTIVE]:
        assert _is_valid_hex(color), f"Invalid hex: {color}"


# ---------- Background ordering ----------

def _hex_brightness(color: str) -> int:
    """Return perceived brightness of a hex color (0-255)."""
    h = color.lstrip("#")
    r, g, b = (int(h[i:i+2], 16) for i in (0, 2, 4))
    return (r * 299 + g * 587 + b * 114) // 1000


def test_background_layers_darken_outward():
    """BG_BASE should be darkest, BG_ELEVATED lightest."""
    assert _hex_brightness(BG_BASE) < _hex_brightness(BG_DARK)
    assert _hex_brightness(BG_DARK) < _hex_brightness(BG_SURFACE)
    assert _hex_brightness(BG_SURFACE) < _hex_brightness(BG_ELEVATED)


def test_text_primary_is_brighter_than_secondary():
    assert _hex_brightness(TEXT_PRIMARY) > _hex_brightness(TEXT_SECONDARY)
    assert _hex_brightness(TEXT_SECONDARY) > _hex_brightness(TEXT_DISABLED)


# ---------- IMPORTANCE_COLORS ----------

def test_importance_colors_has_all_levels():
    expected = {"ROUTINE", "PRIORITY", "FLASH"}
    assert set(IMPORTANCE_COLORS.keys()) == expected


def test_importance_colors_values():
    assert IMPORTANCE_COLORS["ROUTINE"] == COLOR_BLUE
    assert IMPORTANCE_COLORS["PRIORITY"] == COLOR_AMBER
    assert IMPORTANCE_COLORS["FLASH"] == COLOR_RED


def test_importance_colors_are_valid_hex():
    for level, color in IMPORTANCE_COLORS.items():
        assert _is_valid_hex(color), f"Invalid hex for {level}: {color}"


# ---------- TRANSPORT_COLORS ----------

def test_transport_colors_has_expected_keys():
    expected = {"yggdrasil", "i2p", "tcp", "rnode", "offline"}
    assert set(TRANSPORT_COLORS.keys()) == expected


def test_broadband_transports_are_green():
    for t in ["yggdrasil", "i2p", "tcp"]:
        assert TRANSPORT_COLORS[t] == COLOR_PRIMARY


def test_lora_transport_is_amber():
    assert TRANSPORT_COLORS["rnode"] == COLOR_AMBER


def test_offline_transport_is_red():
    assert TRANSPORT_COLORS["offline"] == COLOR_RED


def test_transport_colors_are_valid_hex():
    for name, color in TRANSPORT_COLORS.items():
        assert _is_valid_hex(color), f"Invalid hex for {name}: {color}"


# ---------- KIVYMD_THEME ----------

def test_kivymd_theme_is_dark():
    assert KIVYMD_THEME["theme_style"] == "Dark"


def test_kivymd_theme_has_required_keys():
    required = {"theme_style", "primary_palette", "accent_palette",
                "primary_hue", "accent_hue"}
    assert required.issubset(set(KIVYMD_THEME.keys()))


# ---------- Layout constants ----------

def test_desktop_min_width_is_reasonable():
    assert 600 <= DESKTOP_MIN_WIDTH <= 1200


def test_font_names_are_strings():
    assert isinstance(FONT_MONO, str) and FONT_MONO
    assert isinstance(FONT_SANS, str) and FONT_SANS


def test_spacing_constants_are_dp_strings():
    for val in [PADDING_SM, PADDING_MD, PADDING_LG, RADIUS_SM, RADIUS_MD, TOUCH_TARGET]:
        assert isinstance(val, str)
        assert val.endswith("dp"), f"Expected dp suffix: {val}"


def test_padding_ordering():
    """SM < MD < LG."""
    sm = int(PADDING_SM.replace("dp", ""))
    md = int(PADDING_MD.replace("dp", ""))
    lg = int(PADDING_LG.replace("dp", ""))
    assert sm < md < lg


def test_touch_target_meets_material_minimum():
    """Material Design requires minimum 48dp touch targets."""
    size = int(TOUCH_TARGET.replace("dp", ""))
    assert size >= 48
