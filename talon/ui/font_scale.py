"""
Global font scale — single source of truth for all screens.

Replaces the per-screen _FONT_SCALE globals.  Screens import get_font_scale()
in their _fs() helper; the nav rail cog writes via set_font_scale() so a
single button updates the whole app.
"""

_GLOBAL_FONT_SCALE: float = 1.0
FONT_SCALE_META_KEY = 'global_font_scale'


def get_font_scale() -> float:
    return _GLOBAL_FONT_SCALE


def set_font_scale(s: float) -> None:
    global _GLOBAL_FONT_SCALE
    _GLOBAL_FONT_SCALE = s


def load_font_scale_from_db(conn) -> None:
    """Load persisted scale from the meta table. Call once after DB opens."""
    global _GLOBAL_FONT_SCALE
    if conn is None:
        return
    try:
        row = conn.execute(
            "SELECT value FROM meta WHERE key=?", (FONT_SCALE_META_KEY,)
        ).fetchone()
        if row:
            _GLOBAL_FONT_SCALE = float(row[0])
    except Exception:
        pass
