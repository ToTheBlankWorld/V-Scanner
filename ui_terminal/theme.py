"""V-Scanner 3.0 TUI design tokens (Stage 05 visual design system).

This module is the SINGLE source of truth for the V-Scanner look:

* the registered Textual :class:`~textual.theme.Theme` (color roles — the
  palette the app activates on startup), and
* the shared Textual-CSS fragments (spacing, borders, focus/selection
  treatments) that screens compose from named token strings.

Design rules (ARCHITECTURE_DECISIONS A-03, mission §4):

* Dark-first developer-tool identity; no other color values are written
  outside this module — widgets reference theme variables (``$primary``,
  ``$surface``, ...) and the CSS constants defined here.
* Rich is allowed only inside ``ui_terminal`` (never below the interface
  seam); Textual does the layout work.
* Branding is compact and intentional — no terminal-space logos.

The theme is registered by :meth:`textual.app.App.register_theme` in
``ui_terminal.app``; tests assert every screen's raw colors come from here.
"""

from __future__ import annotations

from textual.theme import Theme

__all__ = [
    "VSCANNER_THEME",
    "THEME_NAME",
    "APP_TCSS",
    "SECTION_TCSS",
    "BRAND_TAGLINE",
    "APP_TITLE",
]

THEME_NAME = "vscanner-dark"

APP_TITLE = "V-Scanner 3.0"

BRAND_TAGLINE = "Android security auditing — local, offline, evidence-based"

# --- color token roles (the palette) -------------------------------------- #

_BACKGROUND = "#0a0e14"      # deep slate canvas
_SURFACE = "#10161e"         # card / widget body over the canvas
_PANEL = "#141c26"           # raised panel (rail, cards)
_BOOST = "#1b2634"           # hover/selection raise over panel
_FOREGROUND = "#d4dde6"      # primary text
_PRIMARY = "#3ecfc4"         # restrained teal accent — actions & focus
_SECONDARY = "#8ba2b8"       # muted slate — secondary text
_ACCENT = "#c9a54a"          # sparing gold highlight — brand marker
_SUCCESS = "#47c07a"
_WARNING = "#e0a437"
_ERROR = "#e05561"

VSCANNER_THEME = Theme(
    name=THEME_NAME,
    primary=_PRIMARY,
    secondary=_SECONDARY,
    warning=_WARNING,
    error=_ERROR,
    success=_SUCCESS,
    accent=_ACCENT,
    foreground=_FOREGROUND,
    background=_BACKGROUND,
    surface=_SURFACE,
    panel=_PANEL,
    boost=_BOOST,
    dark=True,
    variables={
        # extra named tokens used by the TUI CSS below
        "vs-muted": _SECONDARY,
        "vs-rail-width": "22",
    },
)

# --- shared CSS fragments (spacing / focus / status conventions) ---------- #
# Textual theme variables ($primary, $surface...) plus the extra $vs-* tokens
# above keep every color decision in the theme; these fragments fix layout
# and interaction conventions shared by all screens.

APP_TCSS = """
#brand-bar {
    height: 1;
    dock: top;
    background: $panel;
    color: $foreground;
    padding: 0 1;
}

#brand-name {
    color: $accent;
    text-style: bold;
    width: auto;
    margin-right: 2;
}

#brand-tagline {
    color: $vs-muted;
    width: 1fr;
}

#brand-section {
    color: $primary;
    width: auto;
    margin-right: 1;
}

#get_started {
    margin: 0 1;
}

Footer {
    background: $panel;
}
"""

SECTION_TCSS = """
#nav-rail {
    dock: left;
    width: 24;
    background: $panel;
    padding: 1 0;
}

#nav-rail .nav-item {
    height: auto;
    width: 1fr;
    background: $panel;
    border: none;
    color: $secondary;
    text-align: left;
    padding: 0 1;
    margin: 0 0 0 0;
    min-height: 1;
    content-align: left middle;
}

#nav-rail .nav-item > Label {
    width: 1fr;
    text-align: left;
}

#nav-rail .nav-item:hover {
    background: $boost;
}

#nav-rail .nav-item:focus {
    background: $boost;
    border-left: thick $primary;
    border-top: none;
    border-right: none;
    border-bottom: none;
    text-style: bold;
    color: $foreground;
}

#nav-rail .nav-section-caption {
    color: $vs-muted;
    padding: 0 1;
    margin-top: 1;
}

/* focused control gets a visible teal outline on every screen */
Screen:focus-within Button:focus {
    border: round $primary;
}

Input:focus {
    border: round $primary;
}

#vs-body {
    padding: 1 2;
}

#card {
    background: $surface;
    border: round $panel;
    padding: 0 1;
    margin-bottom: 1;
}

#status-line {
    dock: bottom;
    height: 1;
    background: $surface;
    color: $vs-muted;
    padding: 0 1;
}

.status-ok {
    color: $success;
}

.status-warn {
    color: $warning;
}

.status-error {
    color: $error;
}

.status-muted {
    color: $vs-muted;
}

.vs-placeholder-banner {
    background: $warning;
    color: $background;
    text-style: bold;
    padding: 0 1;
}

PlaceholderFuture {
    background: $surface;
    border: round $accent;
    padding: 1 2;
    color: $secondary;
}
"""
