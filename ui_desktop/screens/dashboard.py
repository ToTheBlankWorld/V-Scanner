"""Dashboard (Stage 10/11): honest engine/config/ADB readiness for the desktop.

What this page REALLY does (everything else is honestly declared absent):

* Real configuration state through ``ConfigService`` (path saved or not,
  unreadable config surfaced instead of swallowed).
* Real engine package state (``services.doctor`` dependency report).
* ADB availability is checked ONLY by an explicit user action: the probe
  validates the configured executable with the shared engine check
  (``services.adb.executable.check_adb_valid``) inside a background
  worker — never at startup, never on the GUI thread. The states "not
  checked / no path configured / invalid / validated" stay distinct.
* A navigation action into the real device workspace (Stage 10). The
  dashboard fabricates nothing about devices: no counts, no connection
  state, no scan/history/security claims. Scanning, findings, reports
  and history (Stage 11) and monitoring, forensics, mirroring, demo
  data and the administration operations (Stage 12) are real sections
  elsewhere in the shell; the boundaries panel states honestly what the
  desktop does NOT do (no provisioning UI, no Android background
  monitoring, no unverified scrcpy-window claims).
"""

from __future__ import annotations

import platform
from typing import Callable, Optional

from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from vscanner.services.adb.executable import check_adb_valid
from vscanner.services.config import ConfigService
from vscanner.services.doctor import (
    DESKTOP_REQUIRED_PACKAGES,
    collect_dependency_report,
    is_frozen,
)

from .. import __version__
from .. import theme
from ..workers import WorkerCoordinator
from ..widgets import MetadataRow, Panel, StatusChip, button

__all__ = ["build_dashboard"]


def build_dashboard(
    config_service: Optional[ConfigService],
    *,
    open_devices: Optional[Callable[[], None]] = None,
    adb_probe: Optional[Callable[[str], bool]] = None,
    config_error: Optional[str] = None,
    host_details: bool = True,
) -> QWidget:
    """Build the dashboard page.

    ``open_devices`` routes the navigation button to the shell's device
    workspace. ``adb_probe`` replaces the engine ADB launch-check in the
    deterministic test harness; the probe never runs during construction —
    checking is strictly user-initiated, exactly like the TUI settings
    screen (Stage 05).
    """
    page = QWidget()
    outer = QVBoxLayout(page)
    outer.setContentsMargins(0, 0, 0, 0)
    outer.setSpacing(12)

    outer.addWidget(_shell_status_panel(open_devices))
    outer.addWidget(_environment_panel(
        config_service, config_error, host_details))
    outer.addWidget(_adb_panel(config_service, config_error, adb_probe))
    outer.addWidget(_packages_panel())
    outer.addWidget(_boundaries_panel())
    outer.addStretch(1)
    page.setAccessibleName("Dashboard")
    return page


# ---------------------------------------------------------------------------
# panels
# ---------------------------------------------------------------------------

def _row(layout: QVBoxLayout) -> QHBoxLayout:
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(theme.SPACING["s"])
    layout.addLayout(row)
    return row


def _heading(layout: QVBoxLayout, text: str) -> None:
    label = QLabel(text)
    label.setObjectName("panelHeading")
    layout.addWidget(label)


def _shell_status_panel(
    open_devices: Optional[Callable[[], None]],
) -> Panel:
    panel = Panel()
    layout = Panel.body_layout(panel)
    row = _row(layout)
    row.addWidget(StatusChip("ok"))
    ready = QLabel(
        f"Desktop shell ready — V-Scanner 3.0 {__version__} "
        "(Stage 09 shell, Stage 10 device workspace, Stage 11 scanning "
        "& findings, reports & history, Stage 12 monitoring, forensics, "
        "mirroring, demo data & administration)")
    ready.setObjectName("bodyText")
    row.addWidget(ready)
    hint = QLabel(
        "Open the Device workspace to discover connected Android devices, "
        "read their details, browse their installed apps, and run the "
        "double-gated administration operations; the Scanning & findings "
        "section runs engine scans on an explicitly selected device; "
        "Reports & history exports the last completed full-device scan; "
        "Live monitoring, Forensics, Mirroring and Demo data provide the "
        "Stage 12 workflows on their own pages.")
    hint.setObjectName("hintText")
    hint.setWordWrap(True)
    layout.addWidget(hint)
    if open_devices is not None:
        actions = _row(layout)
        open_button = button(
            "Open Device workspace", variant="primary",
            tooltip="Go to real device discovery and the installed-app "
                    "inventory browser",
            accessible_name="Open device workspace")
        open_button.clicked.connect(open_devices)
        actions.addWidget(open_button)
    return panel


def _environment_panel(
    config_service: Optional[ConfigService],
    config_error: Optional[str],
    host_details: bool,
) -> Panel:
    panel = Panel()
    layout = Panel.body_layout(panel)
    _heading(layout, "Environment readiness")

    snapshot = None
    shown_error: Optional[str] = config_error
    if config_error is None and config_service is not None:
        try:
            snapshot = config_service.load()
        except Exception as exc:  # corrupted config must never crash startup
            shown_error = f"unexpected reader failure: {exc}"

    if shown_error is not None:
        error = QLabel(f"Configuration could not be read: {shown_error}")
        error.setObjectName("bodyText")
        error.setWordWrap(True)
        error.setStyleSheet(theme.feedback_qss("error"))
        layout.addWidget(error)
        config_value = "unreadable (see the error above)"
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


def _adb_panel(
    config_service: Optional[ConfigService],
    config_error: Optional[str],
    adb_probe: Optional[Callable[[str], bool]],
) -> Panel:
    """ADB tool state — three honest buckets, check strictly user-initiated.

    The saved path is read from the config (cheap, UI-thread safe); the
    launch probe itself is a subprocess and therefore runs in a background
    worker via :class:`~ui_desktop.workers.WorkerCoordinator` (deduped per
    slot — pressing the button while a probe runs is refused).
    """
    panel = Panel()
    layout = Panel.body_layout(panel)
    _heading(layout, "ADB tool")

    status_row = _row(layout)
    chip = StatusChip("neutral", panel)
    status_row.addWidget(chip)
    status_value = QLabel("", panel)
    status_value.setObjectName("secondaryText")
    status_value.setWordWrap(True)
    status_value.setAccessibleName("ADB tool status")
    status_row.addWidget(status_value, 1)

    # Saved path resolution (no probe at read time).
    saved_path: Optional[str] = None
    if config_service is not None and config_error is None:
        try:
            snapshot = config_service.load()
        except Exception:
            snapshot = None  # the config-read failure is already shown above
        else:
            if snapshot is not None and snapshot.has_path:
                saved_path = snapshot.adb_path

    if saved_path is None:
        state_value = "no_path"
    else:
        state_value = "untested"

    probe: Optional[Callable[[str], bool]] = \
        adb_probe if adb_probe is not None else (
            check_adb_valid if saved_path else None)
    coordinator = WorkerCoordinator(parent=panel)

    def render() -> None:
        current = state_value
        if current == "no_path":
            chip.set_status("neutral")
            status_value.setText(
                "not checked — no ADB path is configured "
                "(set one in Settings, Ctrl+,)")
        elif current == "untested":
            chip.set_status("neutral")
            status_value.setText(
                "not checked — a path is saved but not launch-probed here; "
                "the check runs one adb version subprocess (press Check)")
        elif current == "checking":
            chip.set_status("info")
            status_value.setText(
                "checking — one adb version probe is running in the "
                "background…")
        elif current == "valid":
            chip.set_status("ok")
            status_value.setText(
                f"validated — the saved executable launches and reports a "
                f"version ({saved_path})")
        else:  # invalid
            chip.set_status("error")
            status_value.setText(
                f"invalid — the saved path did not launch a working adb "
                f"({saved_path}); fix the path in Settings and check again")

    def finish(ok: bool, _exc: Optional[BaseException] = None) -> None:
        nonlocal state_value
        # A probe failure is an honest result — never a crash, never a
        # silent pass; the state stays invalid until the user re-checks.
        state_value = "valid" if ok else "invalid"
        render()

    def run_check() -> None:
        path = saved_path
        if probe is None or not path:
            return
        if not coordinator.run(
            "adb_check",
            lambda: bool(probe(path)),
            lambda result: finish(bool(result)),
            lambda exc: finish(False, exc),
        ):
            return  # already checking (deduped); the run finishes visibly
        render()

    render()

    actions = _row(layout)
    if saved_path and probe is not None:
        check_button = button(
            "Check ADB availability", variant="secondary",
            tooltip="One background adb version probe of the saved path "
                    "(strictly user-initiated; never automatic)",
            accessible_name="Check adb availability")
        check_button.clicked.connect(run_check)
        actions.addWidget(check_button)
    panel.setProperty("adbState", state_value)
    panel.setSizePolicy(QSizePolicy.Policy.Expanding,
                        QSizePolicy.Policy.Maximum)
    return panel


def _packages_panel() -> Panel:
    panel = Panel()
    layout = Panel.body_layout(panel)
    frozen = is_frozen()
    if frozen:
        # F-1: a packaged executable contains exactly what its surface
        # imports; source-environment verdicts (installed/"N of 3" with a
        # reinstall hint) mislead here. Only the desktop-required packages
        # (DESKTOP_REQUIRED_PACKAGES) judge the status.
        report = collect_dependency_report()
        missing = [p.name for p in report.packages if not p.installed]
        required_missing = [n for n in DESKTOP_REQUIRED_PACKAGES
                            if n in missing]
        non_required = [n for n in missing
                        if n not in DESKTOP_REQUIRED_PACKAGES]
        total = len(report.packages)
        present = total - len(missing)
        _heading(layout, "Engine packages")
        row = _row(layout)
        row.addWidget(MetadataRow(
            "Report", f"packaged build - {present} of {total} compiled in"))
        row.addWidget(MetadataRow(
            "Desktop toolkit", "PySide6 (Qt) available (compiled into "
                               "this executable)" if _pyside_ok() else
            "PySide6 not importable — broken packaged build"))
        row.addWidget(MetadataRow("Desktop extra", "not applicable in a "
                                                   "packaged build"
                                  if _pyside_ok() else "missing"))
        # Only a required package absent from the build is a failure.
        row.addWidget(StatusChip("error" if required_missing else "ok"))
        for package in report.packages:
            state = ("compiled into this executable" if package.installed
                     else "not part of this packaged build")
            layout.addWidget(MetadataRow(
                package.name, f"shared engine dependency - {state}"))
        if required_missing:
            hint = QLabel(
                f"Broken build: {', '.join(required_missing)} must be "
                "part of this packaged executable but is not importable "
                "there — rebuild from the approved packaging pipeline. "
                "The doctor is report-only — it never installs anything "
                "(R-14).")
            hint.setObjectName("hintText")
            hint.setWordWrap(True)
            layout.addWidget(hint)
        elif non_required:
            hint = QLabel(
                f"{', '.join(non_required)} belong to the CLI surface "
                "only; they are not part of this packaged desktop "
                "executable by design - nothing to reinstall. The doctor "
                "is report-only — it never installs anything (R-14).")
            hint.setObjectName("hintText")
            hint.setWordWrap(True)
            layout.addWidget(hint)
        return panel
    report = collect_dependency_report()
    missing = [p.name for p in report.packages if not p.installed]
    _heading(layout, "Engine packages")
    row = _row(layout)
    row.addWidget(MetadataRow(
        "Report", f"{len(report.packages) - len(missing)} of "
                  f"{len(report.packages)} installed"))
    row.addWidget(MetadataRow(
        "Desktop toolkit",
        "PySide6 (Qt) available" if _pyside_ok() else
        "PySide6 not importable — the desktop UI needs the 'desktop' extra"))
    row.addWidget(MetadataRow(
        "Desktop extra", "installed (pip install -e '.[desktop]')"
        if _pyside_ok() else "missing"))
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


def _boundaries_panel() -> Panel:
    panel = Panel()
    layout = Panel.body_layout(panel)
    _heading(layout, "Honest boundaries of the desktop shell")
    for title, detail in (
        ("No tool-provisioning UI",
         "scrcpy and ADB tools are provisioned and validated by the "
         "engine/CLI workflow — the desktop screens show the resulting "
         "state and refuse honestly when a tool is unvalidated"),
        ("No Android-side background monitoring",
         "Live monitoring is host-side, read-only dumpsys polling started "
         "and stopped explicitly; nothing runs continuously on the device"),
        ("No verified scrcpy window behavior",
         "Mirroring launches the real process; whether a window appears "
         "on screen is scrcpy's own behavior and is never claimed as "
         "verified by this project"),
        ("Redaction by default",
         "Forensics WiFi exports are redacted; the clear-text variant "
         "requires the exact typed acknowledgement and stays service-"
         "gated"),
    ):
        layout.addWidget(MetadataRow(title, detail))
    return panel


def _pyside_ok() -> bool:
    try:
        import PySide6  # noqa: F401
    except ImportError:
        return False
    return True
