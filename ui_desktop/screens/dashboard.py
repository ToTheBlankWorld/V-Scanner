"""Dashboard skeleton (Stage 09 desktop foundation).

Honest startup readiness only: real config state (``ConfigService``) and
real engine package state (``services.doctor``). No device discovery, no
subprocess launches, no decorative numbers — a device-independent view that
never fakes capability (Stage 09 mission §4/§12).
"""

from __future__ import annotations

import platform
from typing import Optional

from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from vscanner.services.config import ConfigService
from vscanner.services.doctor import collect_dependency_report

from .. import __version__
from ..theme import ERROR_COLOR
from ..widgets import MetadataRow, Panel, StatusChip

__all__ = ["build_dashboard"]


def build_dashboard(
    config_service: Optional[ConfigService],
    *,
    config_error: Optional[str] = None,
    host_details: bool = True,
) -> QWidget:
    """Build the dashboard skeleton.

    ``config_error`` carries a prepared, truthful description when the config
    file exists but is unreadable/invalid — the shell catches
    ``ConfigError`` in production; tests inject failures through the service.

    ``host_details=False`` renders a fully device/portable-independent page
    (used when a host probe would be inappropriate — the shell decides; the
    default ``True`` shows the honest runtime environment line).
    """
    page = QWidget()
    outer = QVBoxLayout(page)
    outer.setContentsMargins(0, 0, 0, 0)
    outer.setSpacing(12)

    outer.addWidget(_shell_status_panel())
    outer.addWidget(_environment_panel(
        config_service, config_error, host_details))
    outer.addWidget(_packages_panel())
    outer.addWidget(_adb_panel())
    outer.addStretch(1)
    page.setAccessibleName("Dashboard")
    return page


# ---------------------------------------------------------------------------
# panels
# ---------------------------------------------------------------------------

def _row(layout: QVBoxLayout) -> QHBoxLayout:
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(8)
    layout.addLayout(row)
    return row


def _heading(layout: QVBoxLayout, text: str) -> None:
    label = QLabel(text)
    label.setObjectName("panelHeading")
    layout.addWidget(label)


def _shell_status_panel() -> Panel:
    panel = Panel()
    layout = Panel.body_layout(panel)
    row = _row(layout)
    row.addWidget(StatusChip("ok"))
    ready = QLabel(
        f"Desktop shell ready — V-Scanner 3.0 {__version__} "
        "(Stage 09 foundation)")
    ready.setObjectName("bodyText")
    row.addWidget(ready)
    hint = QLabel(
        "Device operations, scanning, reports, and monitoring are delivered "
        "by Stages 10–12. This page shows only what exists today.")
    hint.setObjectName("hintText")
    hint.setWordWrap(True)
    layout.addWidget(hint)
    return panel


def _environment_panel(
    config_service: Optional[ConfigService],
    config_error: Optional[str],
    host_details: bool,
) -> Panel:
    panel = Panel()
    layout = Panel.body_layout(panel)
    _heading(layout, "Environment readiness")

    if config_error is not None:
        error = QLabel(f"Configuration could not be read: {config_error}")
        error.setObjectName("bodyText")
        error.setWordWrap(True)
        error.setStyleSheet(f"color: {ERROR_COLOR}; background: transparent;")
        layout.addWidget(error)
        config_value = "unreadable (see error above)"
    else:
        try:
            snapshot = config_service.load() if config_service else None
        except Exception as exc:  # corrupted config must never crash startup
            config_error = f"unexpected reader failure: {exc}"
            snapshot = None
            error = QLabel(f"Configuration could not be read: {config_error}")
            error.setObjectName("bodyText")
            error.setWordWrap(True)
            error.setStyleSheet(
                f"color: {ERROR_COLOR}; background: transparent;")
            layout.addWidget(error)
            config_value = "unreadable (see error above)"
        else:
            if config_service is None:
                config_value = "no configuration service wired"
            elif snapshot is not None and snapshot.has_path:
                config_value = f"configured — ADB path saved ({snapshot.adb_path})"
            else:
                config_value = (
                    "not configured yet — set the ADB path in Settings (Ctrl+,)")

    layout.addWidget(MetadataRow("Configuration", config_value))
    layout.addWidget(MetadataRow(
        "Config file",
        "(no configuration service)" if config_service is None
        else str(config_service.path)))
    if host_details:
        layout.addWidget(MetadataRow(
            "Runtime environment",
            f"Python {platform.python_version()} on {platform.system()}"))
    return panel


def _packages_panel() -> Panel:
    panel = Panel()
    layout = Panel.body_layout(panel)
    report = collect_dependency_report()
    missing = [p.name for p in report.packages if not p.installed]
    _heading(layout, "Engine packages")
    row = _row(layout)
    row.addWidget(MetadataRow(
        "Report", f"{len(report.packages) - len(missing)} of "
                  f"{len(report.packages)} installed"))
    row.addWidget(StatusChip("ok" if not missing else "error"))
    for package in report.packages:
        state = "installed" if package.installed else "not installed"
        layout.addWidget(MetadataRow(
            package.name, f"shared engine dependency — {state}"))
    if missing:
        hint = QLabel(f"Missing ({', '.join(missing)}): reinstall the engine "
                      "environment. The doctor is report-only — it never "
                      "installs anything (R-14).")
        hint.setObjectName("hintText")
        hint.setWordWrap(True)
        layout.addWidget(hint)
    return panel


def _adb_panel() -> Panel:
    panel = Panel()
    layout = Panel.body_layout(panel)
    _heading(layout, "ADB tool")
    row = _row(layout)
    row.addWidget(MetadataRow(
        "Status", "not checked in this stage"))
    row.addWidget(StatusChip("neutral"))
    note = QLabel(
        "The desktop shell never launches processes on its own; ADB "
        "validation and provisioning arrive with device management "
        "(Stage 10).")
    note.setObjectName("hintText")
    note.setWordWrap(True)
    layout.addWidget(note)
    return panel
