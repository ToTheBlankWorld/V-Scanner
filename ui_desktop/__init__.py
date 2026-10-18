"""V-Scanner 3.0 — ``ui_desktop`` (PySide6 application interface layer).

Stage 09 delivers the desktop foundation: the application shell
(:mod:`ui_desktop.app`), the design system (:mod:`ui_desktop.theme`),
navigation (:mod:`ui_desktop.sections`), reusable widgets
(:mod:`ui_desktop.widgets`), the Qt job bridge (:mod:`ui_desktop.jobs_bridge_qt`)
and the live Stage 09 screens.

Boundaries (ARCHITECTURE_DECISIONS A-03/T-04, enforced by tests):

* PySide6 is *this package's* presentation framework. It must never leak
  into ``vscanner/**`` (engine) or ``ui_terminal`` (Textual TUI).
* The engine never imports this package — the interface seam consumes
  documented services only (A-10/A-11).
* Qt-specific module constants, declared without importing PySide6 so the
  metadata below stays engine-environment friendly:

  - ``APP_NAME``  — window title/brand text.
  - ``APP_VERSION`` — kept in lockstep with ``pyproject.toml`` (checked by test).
"""

APP_NAME = "V-Scanner"
APP_VERSION = "3.0.0a0"
APP_SUBTITLE = "Android security auditing"

__version__ = APP_VERSION
"""Backwards-friendly alias used by screens/widgets (metadata lockstep)."""
