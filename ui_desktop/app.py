"""Desktop application entry point (Stage 09).

Launch paths (documented for Stage 14 packaging):

* ``python -m ui_desktop``            — primary development launch.
* ``vscanner-desktop``                — console script (optional extra).
* ``python -m ui_desktop --smoke``    — offscreen-safe startup smoke test:
  builds the app and window, closes after a short delay, prints
  ``DESKTOP_SMOKE_OK`` and exits 0 on success.

Startup rules (Stage 09 mission §6/§12):

* ``QApplication`` is created and owned here — exactly one; a second
  attempt raises a typed error instead of silently reusing a foreign loop.
* No device discovery, no process launches, no network: missing/invalid
  configuration renders an honest ``ErrorState`` on the dashboard instead
  of a blank window or a crash.
* Fusion is the application style for a deterministic dark desktop look;
  every color comes from ``ui_desktop.theme`` (stylesheets applied once).
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Optional

from PySide6.QtCore import QTimer
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from vscanner.core.errors import ConfigError
from vscanner.core.paths import config_dir, ensure_dir
from vscanner.services.config import ConfigService

from . import APP_NAME, APP_VERSION
from . import theme
from .backend import DesktopBackend
from .main_window import MainWindow

__all__ = ["create_application", "bootstrap_window", "run", "main"]


def default_config_service() -> ConfigService:
    """The production config location (same contract as the TUI, A-07)."""
    ensure_dir(config_dir())
    return ConfigService(config_dir() / "config.json")


def create_application(argv: Optional[list[str]] = None) -> QApplication:
    """Create the single QApplication with the V-Scanner theme applied."""
    if QApplication.instance() is not None:
        raise RuntimeError(
            "a QApplication already exists — create exactly one per process")
    app = QApplication(argv or [])
    app.setObjectName(f"{APP_NAME}Desktop")
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName(APP_NAME)
    app.setStyle("Fusion")
    app.setStyleSheet(theme.build_app_stylesheet())
    # Stage 13: QLineEdit placeholder color (QSS cannot style the
    # placeholder text itself; the palette role can). Token-driven, so the
    # color still lives only in ui_desktop.theme.
    palette = app.palette()
    palette.setColor(QPalette.ColorRole.PlaceholderText,
                     QColor(theme.TEXT_MUTED))
    app.setPalette(palette)
    return app


def bootstrap_window(config_service: Optional[ConfigService] = None) -> MainWindow:
    """Create the shell; failures render honest error state, never blank.

    Configuration is only *read* at startup (strict ``ConfigService.load``).
    A missing file is a valid first-run state; unreadable/invalid content
    becomes the dashboard error message. No device or subprocess work: the
    ``DesktopBackend`` is composed but performs no I/O here (its registry,
    job manager threads and probes start lazily on user actions).
    """
    if config_service is None:
        config_service = default_config_service()
    config_error: Optional[str] = None
    try:
        config_service.load()
    except ConfigError as exc:
        config_error = str(exc)
    except OSError as exc:
        config_error = f"config file is not accessible: {exc}"
    backend = DesktopBackend(config_service)
    return MainWindow(config_service, backend=backend,
                      config_error=config_error)


def run(argv: Optional[list[str]] = None, *,
        smoke: bool = False) -> int:
    """Run the desktop application; returns the Qt exit code.

    ``smoke=True`` forces the offscreen platform (unless the user already
    chose one), runs a short visible-life window, and exits — usable in
    consoles/CI without flashing a real window.
    """
    if smoke:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = create_application(argv)
    window = bootstrap_window()
    window.show()
    if smoke:
        smoke_timer = QTimer(app)
        smoke_timer.setSingleShot(True)
        smoke_timer.timeout.connect(app.quit)
        smoke_timer.start(300)
    exit_code = app.exec()
    if smoke and exit_code == 0:
        print("DESKTOP_SMOKE_OK")
    return exit_code


def main(argv: Optional[list[str]] = None) -> int:
    """Console entry point parsing ``--version`` / ``--smoke``."""
    parser = argparse.ArgumentParser(
        prog=APP_NAME.lower() + "-desktop",
        description="V-Scanner desktop application shell (Stage 09)")
    parser.add_argument("--version", action="version",
                        version=f"{APP_NAME} {APP_VERSION} desktop")
    parser.add_argument("--smoke", action="store_true",
                        help="start, verify, close (offscreen-friendly)")
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    return run(smoke=args.smoke)
