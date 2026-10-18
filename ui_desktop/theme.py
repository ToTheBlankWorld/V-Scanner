"""V-Scanner 3.0 desktop design system (Stage 09 visual foundation).

This module is the SINGLE source of truth for the PySide6/Qt-Widgets look —
the desktop counterpart of ``ui_terminal/theme.py`` (shared product identity,
desktop-appropriate mechanisms: Qt stylesheets generated from the tokens
below, never inline colors elsewhere).

Design rules (ARCHITECTURE_DECISIONS A-03/T-04, Stage 09 mission §4/§5):

* Dark-first developer/security-tool identity. No hex/color literals are
  written outside this module (enforced by an AST test) — widgets reference
  the constants declared here.
* Restrained accents: one blue accent family, four semantic status colors
  with **textual labels** (status is never communicated by color alone).
* Layered surfaces: window background < sidebar < panel < elevated controls,
  separated by 1px borders with a restrained 6px corner radius.
* Compact, intentional branding ("V-Scanner" + version) — no terminal-space
  logos, no decorative titles, no emoji iconography.
* System font fallbacks ("Segoe UI" on Windows with a plain sans-serif
  fallback); sizes/weights live here too.

Mechanism: :func:`build_app_stylesheet` returns one stylesheet string for
the whole application (applied once on the ``QApplication``); per-widget
patterns (primary/secondary buttons, status chips) are Qt dynamic-property
selectors defined centrally here.
"""

from __future__ import annotations

__all__ = [
    # palette
    "WINDOW_BG", "SIDEBAR_BG", "SURFACE_BG", "ELEVATED_BG",
    "BORDER", "SEPARATOR", "SELECTION_BG",
    "TEXT_PRIMARY", "TEXT_SECONDARY", "TEXT_MUTED", "TEXT_ON_ACCENT",
    "ACCENT", "ACCENT_HOVER", "ACCENT_PRESSED",
    "SUCCESS_COLOR", "WARNING_COLOR", "ERROR_COLOR", "INFO_COLOR",
    "FOCUS_RING", "STATUS_COLORS", "STATUS_LABELS", "STATUS_GLYPHS",
    # layout / type
    "FONT_FAMILY", "SPACING", "CONTROL_HEIGHT", "RADIUS",
    "NAV_WIDTH", "MIN_WINDOW_WIDTH", "MIN_WINDOW_HEIGHT", "TITLE_SIZE",
    "HEADING_SIZE", "BODY_SIZE", "META_SIZE",
    # helpers
    "status_color", "status_label", "status_glyph", "status_chip_qss",
    "build_app_stylesheet",
]

# ---------------------------------------------------------------------------
# Layered surface palette
# ---------------------------------------------------------------------------

WINDOW_BG = "#141820"       # app background (title bar, status bar, gaps)
SIDEBAR_BG = "#171C26"      # navigation layer — one step above the window
SURFACE_BG = "#1B222E"      # content panels
ELEVATED_BG = "#242C3A"     # interactive controls (inputs, secondary buttons)
BORDER = "#2E3745"          # panel + control borders
SEPARATOR = "#262D39"       # hairlines inside surfaces (status bar rule)
SELECTION_BG = "#29344A"    # selected navigation item background

TEXT_PRIMARY = "#E8ECF4"    # headings and primary copy
TEXT_SECONDARY = "#9FA8B8"  # subtitles, metadata keys, secondary nav items
TEXT_MUTED = "#6E7686"      # hints, placeholders, disabled/discreet info
TEXT_ON_ACCENT = "#FFFFFF"  # text on the accent fill

ACCENT = "#5B8AF5"          # the single accent family (restrained blue)
ACCENT_HOVER = "#6C97F7"
ACCENT_PRESSED = "#4A79E0"
FOCUS_RING = ACCENT

# Semantic status colors (paired with textual labels/glyphs — never color
# alone). INFO deliberately sits slightly cooler than the brand accent.
SUCCESS_COLOR = "#46B584"
WARNING_COLOR = "#D9A441"
ERROR_COLOR = "#E2655F"
INFO_COLOR = "#6EA8D8"
NEUTRAL_COLOR = TEXT_MUTED

STATUS_COLORS = {
    "ok": SUCCESS_COLOR,
    "warning": WARNING_COLOR,
    "error": ERROR_COLOR,
    "info": INFO_COLOR,
    "neutral": NEUTRAL_COLOR,
}

STATUS_LABELS = {
    "ok": "OK",
    "warning": "ATTENTION",
    "error": "FAILING",
    "info": "INFO",
    "neutral": "NOT SET",
}

# Small geometric glyphs (typographic, not emoji) repeated next to the label.
STATUS_GLYPHS = {
    "ok": "●",
    "warning": "▲",
    "error": "✖",
    "info": "◆",
    "neutral": "○",
}

# ---------------------------------------------------------------------------
# Typography, spacing, control sizing
# ---------------------------------------------------------------------------

FONT_FAMILY = '"Segoe UI", "Helvetica Neue", Arial, sans-serif'

SPACING = {"xs": 4, "s": 8, "m": 12, "l": 16, "xl": 24}
CONTROL_HEIGHT = 30
RADIUS = 6
NAV_WIDTH = 216

MIN_WINDOW_WIDTH = 960
MIN_WINDOW_HEIGHT = 640

TITLE_SIZE = "18px"      # current-section title in the header
HEADING_SIZE = "14px"    # panel headings
BODY_SIZE = "12px"       # base widget size
META_SIZE = "11px"       # metadata keys, footer, hints


def status_color(severity: str) -> str:
    """Color token for a severity name (raises on unknown names)."""
    return STATUS_COLORS[severity]


def status_label(severity: str) -> str:
    """Textual status label — every status is also readable as prose."""
    return STATUS_LABELS[severity]


def status_glyph(severity: str) -> str:
    """Typographic glyph shown before the label (color-adjacent, not alone)."""
    return STATUS_GLYPHS[severity]


def status_chip_qss(severity: str) -> str:
    """Stylesheet for one status chip (centralized per-severity styling)."""
    color = STATUS_COLORS[severity]
    return (
        f"color: {color}; font-weight: 600; background: transparent; "
        "border: none; padding: 0;"
    )


# ---------------------------------------------------------------------------
# Application stylesheet (one string, applied once on the QApplication)
# ---------------------------------------------------------------------------

def build_app_stylesheet() -> str:
    """Generate the canonical dark application stylesheet from the tokens."""
    return f"""
/* ---- base ---------------------------------------------------------- */
QWidget {{
    background: {WINDOW_BG};
    color: {TEXT_PRIMARY};
    font-family: {FONT_FAMILY};
    font-size: {BODY_SIZE};
}}
QMainWindow, QDialog {{ background: {WINDOW_BG}; }}
QToolTip {{
    background: {ELEVATED_BG};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: {RADIUS - 2}px;
    padding: 3px 6px;
}}
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}

/* ---- navigation sidebar -------------------------------------------- */
QFrame#sidePanel {{
    background: {SIDEBAR_BG};
    border: none;
    border-right: 1px solid {SEPARATOR};
}}
QLabel#brandName {{
    font-size: 13px; font-weight: 700; color: {TEXT_PRIMARY};
    background: transparent;
}}
QLabel#brandVersion {{
    font-size: 10px; color: {TEXT_MUTED}; background: transparent;
}}
QListWidget#navRail {{
    background: transparent;
    border: none;
    outline: 0;
    font-size: 12px;
}}
QListWidget#navRail::item {{
    padding: 7px 10px;
    margin: 1px 6px;
    border-radius: 4px;
    color: {TEXT_SECONDARY};
    border: 1px solid transparent;
}}
QListWidget#navRail::item:hover {{
    background: {SURFACE_BG};
    color: {TEXT_PRIMARY};
}}
QListWidget#navRail::item:selected {{
    background: {SELECTION_BG};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
}}
QListWidget#navRail:focus::item:selected {{
    border: 1px solid {FOCUS_RING};
}}

/* ---- panels and headings ------------------------------------------- */
QFrame#panel {{
    background: {SURFACE_BG};
    border: 1px solid {BORDER};
    border-radius: {RADIUS}px;
}}
QLabel#sectionTitle {{
    font-size: {TITLE_SIZE}; font-weight: 600; color: {TEXT_PRIMARY};
    background: transparent;
}}
QLabel#sectionSubtitle {{
    font-size: {BODY_SIZE}; color: {TEXT_SECONDARY}; background: transparent;
}}
QLabel#panelHeading {{
    font-size: {HEADING_SIZE}; font-weight: 600; color: {TEXT_PRIMARY};
    background: transparent;
}}
QLabel#bodyText {{
    color: {TEXT_PRIMARY}; background: transparent;
}}
QLabel#hintText {{
    color: {TEXT_MUTED}; font-size: {META_SIZE}; background: transparent;
}}
QLabel#secondaryText {{
    color: {TEXT_SECONDARY}; background: transparent;
}}
QLabel#brandMark {{
    color: {ACCENT}; font-weight: 700; background: transparent;
    font-size: 13px;
}}

/* ---- metadata rows -------------------------------------------------- */
QLabel#metaKey {{
    color: {TEXT_SECONDARY}; font-size: {META_SIZE};
    background: transparent;
}}
QLabel#metaValue {{
    color: {TEXT_PRIMARY};
    background: transparent;
}}

/* ---- buttons --------------------------------------------------------- */
QPushButton {{
    background: {ELEVATED_BG};
    border: 1px solid {BORDER};
    border-radius: 4px;
    padding: 5px 14px;
    min-height: 18px;
    color: {TEXT_PRIMARY};
}}
QPushButton:hover {{ border-color: {ACCENT}; }}
QPushButton:pressed {{ background: {SELECTION_BG}; }}
QPushButton:focus {{ border: 1px solid {FOCUS_RING}; }}
QPushButton:disabled {{
    color: {TEXT_MUTED};
    background: {SURFACE_BG};
    border-color: {SEPARATOR};
}}
QPushButton[variant="primary"] {{
    background: {ACCENT};
    border: 1px solid {ACCENT};
    color: {TEXT_ON_ACCENT};
    font-weight: 600;
}}
QPushButton[variant="primary"]:hover {{ background: {ACCENT_HOVER}; }}
QPushButton[variant="primary"]:pressed {{ background: {ACCENT_PRESSED}; }}
QPushButton[variant="primary"]:focus {{ border: 1px solid {TEXT_ON_ACCENT}; }}
QPushButton[variant="primary"]:disabled {{
    background: {ACCENT};
    color: rgba(255, 255, 255, 170);
}}

/* ---- inputs ---------------------------------------------------------- */
QLineEdit {{
    background: {ELEVATED_BG};
    border: 1px solid {BORDER};
    border-radius: 4px;
    padding: 5px 8px;
    selection-background-color: {ACCENT};
    selection-color: {TEXT_ON_ACCENT};
}}
QLineEdit:focus {{ border: 1px solid {FOCUS_RING}; }}
QLineEdit:disabled {{ color: {TEXT_MUTED}; }}

/* ---- status bar / footer --------------------------------------------- */
QStatusBar {{
    background: {WINDOW_BG};
    border-top: 1px solid {SEPARATOR};
    color: {TEXT_MUTED};
    font-size: {META_SIZE};
}}
QStatusBar::item {{ border: none; }}
QStatusBar QLabel {{ color: {TEXT_MUTED}; font-size: {META_SIZE}; }}

/* ---- progress (busy indicator) ---------------------------------------- */
QProgressBar#busyBar {{
    background: {ELEVATED_BG};
    border: none;
    border-radius: 3px;
    max-height: 6px;
}}
QProgressBar#busyBar::chunk {{
    background: {ACCENT};
    border-radius: 3px;
}}

/* ---- scrollbars (subtle, desktop appropriate) -------------------------- */
QScrollBar:vertical {{
    background: transparent; width: 10px; margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {BORDER}; min-height: 24px; border-radius: 5px;
    margin: 2px;
}}
QScrollBar::handle:vertical:hover {{ background: {TEXT_MUTED}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: transparent;
}}
"""
