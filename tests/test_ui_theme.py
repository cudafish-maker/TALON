"""Tests for selectable global UI themes."""

from talon.ui import theme


def test_readable_theme_changes_background_and_text_tokens():
    try:
        theme.set_ui_theme("phosphor")
        phosphor_bg = tuple(theme.CHAT_BG0)
        phosphor_text = tuple(theme.CHAT_G4)

        theme.set_ui_theme("readable")

        assert theme.get_ui_theme_key() == "readable"
        assert tuple(theme.CHAT_BG0) != phosphor_bg
        assert tuple(theme.CHAT_G4) != phosphor_text
    finally:
        theme.set_ui_theme("phosphor")


def test_alert_colours_are_stable_across_themes():
    try:
        theme.set_ui_theme("phosphor")
        alert_colours = {
            "accent": tuple(theme.COLOR_ACCENT),
            "danger": tuple(theme.COLOR_DANGER),
            "red": tuple(theme.CHAT_RED),
            "amber": tuple(theme.CHAT_AMBER2),
            "flash": tuple(theme.SITREP_COLORS["FLASH"]),
            "immediate": tuple(theme.SITREP_COLORS["IMMEDIATE"]),
        }

        theme.set_ui_theme("readable")

        assert tuple(theme.COLOR_ACCENT) == alert_colours["accent"]
        assert tuple(theme.COLOR_DANGER) == alert_colours["danger"]
        assert tuple(theme.CHAT_RED) == alert_colours["red"]
        assert tuple(theme.CHAT_AMBER2) == alert_colours["amber"]
        assert tuple(theme.SITREP_COLORS["FLASH"]) == alert_colours["flash"]
        assert tuple(theme.SITREP_COLORS["IMMEDIATE"]) == alert_colours["immediate"]
    finally:
        theme.set_ui_theme("phosphor")


def test_theme_selection_persists_to_meta(tmp_db):
    conn, _ = tmp_db
    try:
        saved = theme.save_ui_theme_to_db(conn, "readable")
        theme.set_ui_theme("phosphor")
        loaded = theme.load_ui_theme_from_db(conn)

        assert saved == "readable"
        assert loaded == "readable"
        assert theme.get_ui_theme_key() == "readable"
    finally:
        theme.set_ui_theme("phosphor")
