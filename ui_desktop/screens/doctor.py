"""Doctor screen (Stage 09 desktop).

Direct consumer of :func:`vscanner.services.doctor.collect_dependency_report`
— the same report the TUI shows; never duplicated, never side-effecting
(R-14: doctor is report-only).
"""

from __future__ import annotations

import platform

from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from vscanner.services.doctor import (
    DESKTOP_REQUIRED_PACKAGES,
    collect_dependency_report,
    is_frozen,
)

from ..widgets import MetadataRow, Panel, StatusChip

__all__ = ["build_doctor"]


def _package_lines_frozen() -> tuple:
    """Frozen (packaged) rendering of the Runtime packages panel.

    In a packaged executable the loading question is not "is it installed
    in a source environment" (F-1: that verdict misleads) but "what is
    part of this build". Only the desktop-surface-required packages
    (``DESKTOP_REQUIRED_PACKAGES`` — grep-verifiable engine truth) judge
    the status; CLI-surface packages absent by design must not fail.
    """
    report = collect_dependency_report()
    missing = [p.name for p in report.packages if not p.installed]
    required_missing = [n for n in DESKTOP_REQUIRED_PACKAGES
                        if n in missing]
    non_required = [n for n in missing
                    if n not in DESKTOP_REQUIRED_PACKAGES]
    total = len(report.packages)
    present = total - len(missing)
    return report, present, total, required_missing, non_required


def _frozen_packages_layout(layout) -> None:
    report, present, total, required_missing, non_required = \
        _package_lines_frozen()
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(8)
    row.addWidget(MetadataRow(
        "Summary", f"packaged build - {present} of {total} compiled in"))
    # Only a genuinely required package absent from the build is a
    # failure; CLI-surface packages absent by design must stay "ok" (F-1).
    row.addWidget(
        StatusChip("error" if required_missing else "ok"))
    layout.addLayout(row)
    for package in report.packages:
        layout.addWidget(MetadataRow(
            package.name,
            "compiled into this executable" if package.installed
            else "not part of this packaged build"))
    if required_missing:
        hint = QLabel(
            f"Broken build: {', '.join(required_missing)} must be part of "
            "this packaged executable but is not importable there — "
            "rebuild from the approved packaging pipeline. The doctor "
            "never installs anything itself (R-14).")
        hint.setObjectName("hintText")
        hint.setWordWrap(True)
        layout.addWidget(hint)
    elif non_required:
        hint = QLabel(
            f"{', '.join(non_required)} belong to the CLI surface only; a "
            "packaged desktop executable contains what its surface "
            "imports, so they are absent by design - nothing to "
            "reinstall. The doctor never installs anything (R-14).")
        hint.setObjectName("hintText")
        hint.setWordWrap(True)
        layout.addWidget(hint)


def build_doctor(*, host_details: bool = True) -> QWidget:
    page = QWidget()
    outer = QVBoxLayout(page)
    outer.setContentsMargins(0, 0, 0, 0)
    outer.setSpacing(12)

    # Packages ----------------------------------------------------------- #
    packages_panel = Panel(page)
    layout = Panel.body_layout(packages_panel)
    heading = QLabel("Runtime packages", packages_panel)
    heading.setObjectName("panelHeading")
    layout.addWidget(heading)

    if is_frozen():
        _frozen_packages_layout(layout)
    else:
        report = collect_dependency_report()
        missing = [p.name for p in report.packages if not p.installed]
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        row.addWidget(MetadataRow(
            "Summary", f"{len(report.packages) - len(missing)} of "
                       f"{len(report.packages)} packages present"))
        row.addWidget(StatusChip("ok" if not missing else "error"))
        layout.addLayout(row)
        for package in report.packages:
            layout.addWidget(MetadataRow(
                package.name,
                "installed" if package.installed else "NOT INSTALLED"))
        if missing:
            hint = QLabel(
                f"Missing: {', '.join(missing)}. Reinstall the engine "
                "environment (pip install -e .). The doctor never installs "
                "anything itself (R-14).")
            hint.setObjectName("hintText")
            hint.setWordWrap(True)
            layout.addWidget(hint)
    outer.addWidget(packages_panel)

    # Owned tool (read-only, never probed at startup) --------------------- #
    tools_panel = Panel(page)
    layout = Panel.body_layout(tools_panel)
    heading = QLabel("ADB tool", tools_panel)
    heading.setObjectName("panelHeading")
    layout.addWidget(heading)
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(8)
    row.addWidget(MetadataRow(
        "Summary", "not checked — no provisioning runs at startup"))
    row.addWidget(StatusChip("neutral"))
    layout.addLayout(row)
    note = QLabel(
        "Validating or provisioning ADB requires launching a process; the "
        "Stage 09 shell never does that. Configure the path in Settings "
        "— live validation lands with device management (Stage 10).")
    note.setObjectName("hintText")
    note.setWordWrap(True)
    layout.addWidget(note)
    outer.addWidget(tools_panel)

    # Host environment ----------------------------------------------------- #
    env_panel = Panel(page)
    layout = Panel.body_layout(env_panel)
    heading = QLabel("Environment", env_panel)
    heading.setObjectName("panelHeading")
    layout.addWidget(heading)
    if host_details:
        layout.addWidget(MetadataRow(
            "Python", platform.python_version()))
        layout.addWidget(MetadataRow(
            "Platform", f"{platform.system()} {platform.release()}"))
    else:
        layout.addWidget(QLabel("Host details unavailable in this environment.",
                                env_panel))
    layout.addWidget(MetadataRow(
        "Report scope", "read-only; doctor never installs, downloads, or "
                        "touches the network (R-14)"))
    outer.addWidget(env_panel)

    outer.addStretch(1)
    page.setAccessibleName("Doctor report")
    return page
