# talon/ui/theme.py
# T.A.L.O.N. color palette and theme constants.
#
# Dark tactical theme — designed for low-light field use.
# High contrast, minimal color, nothing decorative.
#
# Color hierarchy:
#   Background layers:  darkest → dark → surface → elevated
#   Accent colors:      tactical green (primary), amber (warning), red (critical)
#   Text:               bright white → muted grey → disabled

# ---------- Background layers ----------

BG_BASE       = "#0a0e14"   # Outermost background — almost black
BG_DARK       = "#0f1520"   # Panels, sidebars
BG_SURFACE    = "#151d2b"   # Cards, list items
BG_ELEVATED   = "#1c2637"   # Modals, dropdowns, focused items

# ---------- Accent / status ----------

COLOR_PRIMARY  = "#00e5a0"   # Tactical green — primary action, online indicator
COLOR_AMBER    = "#f5a623"   # Warning, LoRa-only mode, PRIORITY SITREP
COLOR_RED      = "#ff3b3b"   # Critical, FLASH SITREP, revoked status, danger
COLOR_BLUE     = "#4a9eff"   # Informational, links, ROUTINE SITREP

# ---------- Text ----------

TEXT_PRIMARY   = "#e8edf4"   # Main readable text
TEXT_SECONDARY = "#8a9bb0"   # Labels, secondary info
TEXT_DISABLED  = "#3d4f63"   # Placeholder, inactive items

# ---------- Borders / dividers ----------

BORDER_SUBTLE  = "#1e2d3d"   # Hairline dividers
BORDER_ACTIVE  = "#00e5a0"   # Focused input, selected item border

# ---------- SITREP importance colors ----------
# Maps to ImportanceLevel enum in constants.py

IMPORTANCE_COLORS = {
    "ROUTINE":  COLOR_BLUE,
    "PRIORITY": COLOR_AMBER,
    "FLASH":    COLOR_RED,
}

# ---------- Transport / connection status colors ----------

TRANSPORT_COLORS = {
    "yggdrasil": COLOR_PRIMARY,   # Full broadband
    "i2p":       COLOR_PRIMARY,   # Full broadband (anonymous)
    "tcp":       COLOR_PRIMARY,   # Full broadband (direct)
    "rnode":     COLOR_AMBER,     # LoRa — bandwidth limited
    "offline":   COLOR_RED,       # No connection
}

# ---------- KivyMD theme dict ----------
# These values are passed to MDApp.theme_cls at startup.
# KivyMD uses Material Design colour roles — we override them
# to match the tactical palette.

KIVYMD_THEME = {
    "theme_style": "Dark",
    "primary_palette": "Teal",       # Closest built-in to #00e5a0
    "accent_palette": "Amber",
    "primary_hue": "A400",
    "accent_hue": "600",
}

# ---------- Typography ----------

FONT_MONO  = "RobotoMono"   # Callsigns, coordinates, IDs
FONT_SANS  = "Roboto"       # Body text, labels

# ---------- Spacing / sizing ----------
# Consistent spacing prevents the UI from looking crowded on small screens.

PADDING_SM  = "8dp"
PADDING_MD  = "16dp"
PADDING_LG  = "24dp"

RADIUS_SM   = "4dp"
RADIUS_MD   = "8dp"

# Minimum touch target size (Material Design: 48dp)
TOUCH_TARGET = "48dp"

# ---------- Layout breakpoints ----------
# Used by the main layout to switch between three-column (desktop/laptop)
# and nav-rail (Android landscape) layouts.

DESKTOP_MIN_WIDTH = 900    # dp — below this, use mobile layout
