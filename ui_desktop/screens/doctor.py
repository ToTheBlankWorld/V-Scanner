"""Doctor screen (Stage 09 desktop).

Direct consumer of :func:`vscanner.services.doctor.collect_dependency_report`
— the same report the TUI shows; never duplicated, never side-effecting
(R-14: doctor is report-only).
"""

from __future__ import annotations

import platform

from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from vscanner.services.doctor import collect_dependency_report

from ..widgets import MetadataRow, Panel, StatusChip

__all__ = ["build_doctor"]


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
