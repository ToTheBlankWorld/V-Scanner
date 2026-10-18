"""Scanning & findings (Stage 07): target selection, scope, live progress,
cancellation, findings exploration with filters/sorting, and detail view.

Everything device- or scan-related goes through the shared engine:

* the scan target is an EXPLICIT selection on this screen's own device
  table (same honesty rules as the Stage 06 workspace; one selectable
  device is preselected, several are never);
* scans run as FULL_DEVICE_SCAN / SINGLE_APP_SCAN jobs (Stage 04 mutex
  group ``scan`` — overlapping scans are impossible), with the engine's
  real progress / streamed findings events;
* a scan REQUEST is distinct from its CONFIRMED terminal event: cancel
  (`c`) only arms the engine token, the CANCELLED terminal event is the
  acknowledgement (JOB_AND_EVENT_CONTRACTS §5);
* before any job starts, the selected device is re-checked against a
  fresh discovery — the target is never silently switched;
* findings are exactly the typed engine findings: filters narrow the
  rendered subset and NEVER mutate the underlying results; severity and
  category filters cycle; sorting is deterministic (key + stable id);
* honesty anchors: no fabricated percentages, in-flight progress only
  from engine events; partial (cancelled/failed) findings are always
  labeled incomplete; zero findings is never presented as "secure";
  detail provenance words (observed vs heuristic) come from EvidenceKind.
"""

from __future__ import annotations

import uuid
from typing import Optional, cast

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalGroup
from textual.widgets import Button, DataTable, Input, Label

from vscanner.core.events import (
    JobFindingEvent,
    JobProgressEvent,
    JobTerminalEvent,
)
from vscanner.core.models import (
    AppScanResult,
    EvidenceKind,
    Finding,
    FindingCategory,
    FindingSeverity,
    ScanResultBundle,
)
from vscanner.services.history import HistoryEntry

from ui_terminal.backend import DeviceBackend
from ui_terminal.screens.shell import ShellScreen
from ui_terminal.screens.workspace import _STATE_WORDS, _failure_word

__all__ = ["ScanScreen", "PAGE_SIZE", "SEVERITY_CYCLE"]

PAGE_SIZE = 100
"""Same explicit pagination contract as the workspace inventory."""

SEVERITY_CYCLE: tuple = (None, FindingSeverity.CRITICAL, FindingSeverity.HIGH,
                         FindingSeverity.MEDIUM, FindingSeverity.LOW,
                         FindingSeverity.INFO)
"""Minimum-severity filter cycle; ``None`` = no threshold."""

_CATEGORY_CYCLE: tuple = (None,) + tuple(FindingCategory)

_SEVERITY_RANK = {
    FindingSeverity.CRITICAL: 0,
    FindingSeverity.HIGH: 1,
    FindingSeverity.MEDIUM: 2,
    FindingSeverity.LOW: 3,
    FindingSeverity.INFO: 4,
}

_SORT_CYCLE = ("severity", "category", "package", "title")

_EVIDENCE_WORDS = {
    EvidenceKind.CONFIRMED_ARTIFACT: "observed",
    EvidenceKind.CONFIRMED_COMMAND_OUTPUT: "observed (command output)",
    EvidenceKind.HEURISTIC_PATTERN: "heuristic",
    EvidenceKind.INFORMATIONAL: "informational",
    EvidenceKind.UNVERIFIED_CONDITION: "unverified",
}

_SEVERITY_LABEL = {
    FindingSeverity.CRITICAL: "critical",
    FindingSeverity.HIGH: "high",
    FindingSeverity.MEDIUM: "medium",
    FindingSeverity.LOW: "low",
    FindingSeverity.INFO: "info",
}

_CATEGORY_LABEL = {
    FindingCategory.PERMISSION_EXCESS: "permission excess",
    FindingCategory.SDK_COMPAT: "SDK compatibility",
    FindingCategory.INSECURE_URL: "insecure URL",
    FindingCategory.HARDCODED_SECRET: "hardcoded secret",
    FindingCategory.DEVICE_EXPOSURE: "device exposure",
    FindingCategory.FORENSICS_ARTIFACT: "forensics artifact",
    FindingCategory.INFO_NOTE: "info note",
}


def _honest(value) -> str:
    if value is None or (isinstance(value, str) and not value.strip()):
        return "unknown"
    return str(value)


class ScanScreen(ShellScreen):
    """Scan a selected device through the shared engine; explore findings."""

    SECTION_ID = "scan"

    BINDINGS = [
        Binding("r", "refresh", "Refresh devices"),
        Binding("a", "start_scan", "Start full-device scan"),
        Binding("n", "start_single", "Scan one app"),
        Binding("c", "cancel_scan", "Cancel scan"),
        Binding("t", "toggle_system", "System apps on/off"),
        Binding("u", "toggle_deep", "Deep scan on/off"),
        Binding("v", "cycle_severity", "Severity filter"),
        Binding("g", "cycle_category", "Category filter"),
        Binding("o", "cycle_sort", "Sort findings"),
        Binding("[", "prev_page", "Previous findings page", show=False),
        Binding("]", "next_page", "Next findings page", show=False),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._devices: tuple = ()
        # discovery state: idle | discovering | ok | empty | failed | no-adb
        self._discovery_state = "idle"
        self._discovery_error: Optional[str] = None
        self._auto_discovery_done = False

        self._selected_serial: Optional[str] = None

        self._include_system = False
        self._deep = False

        self._findings: tuple = ()
        """What the explorer shows right now — the bundle's findings for a
        finished scan, or the streamed findings of a running/partial scan;
        ALWAYS a real engine tuple, never hand-made."""
        self._findings_status = "none"
        """none | streaming | complete | partial-stream | from-bundle."""
        self._streamed: int = 0
        # scan state: idle | validating | running | completed | cancelled |
        #             failed | away
        self._scan_state = "idle"
        self._scan_error: Optional[str] = None
        self._scan_job_id: Optional[str] = None
        self._scan_kind_word = ""
        self._progress_text = ""

        self._severity_min = SEVERITY_CYCLE[0]
        self._category: Optional[FindingCategory] = None
        self._sort_key = "severity"
        self._text_filter = ""
        self._page = 0
        self._detail_finding: Optional[Finding] = None
        self._row_findings: dict = {}
        """Position → finding for the CURRENT page (row keys are view
        positions; the legacy duplicate stable-id quirk must never break
        row identity)."""

    @property
    def backend(self) -> DeviceBackend:
        return cast(DeviceBackend, getattr(self.app, "backend"))

    # -- composition --------------------------------------------------------- #

    def inner_body(self) -> ComposeResult:
        with Vertical(id="scan-body"):
            with Horizontal(id="scan-header"):
                yield Button("Refresh · r", id="scan-refresh-btn", flat=True,
                             compact=True)
                yield Label("", id="scan-target")
            yield Label(
                "Pick the scan target explicitly, choose the scope, then "
                "start. The engine alone reports progress and findings; this "
                "screen never invents them.",
                id="scan-explain", classes="status-muted",
            )
            yield Label("", id="scan-banner", classes="status-muted")
            yield DataTable(id="scan-devices", cursor_type="row")
            with Horizontal(id="scan-scope-row"):
                yield Button("Scan device · a", id="scan-start-btn", flat=True,
                             compact=True)
                yield Button("Cancel · c", id="scan-cancel-btn", flat=True,
                             compact=True)
                yield Input(
                    placeholder="package to scan (single-app mode)",
                    id="scan-package",
                )
                yield Button("Scan one app · n", id="scan-single-btn",
                             flat=True, compact=True)
            yield Label("", id="scan-scope-state", classes="status-muted")
            yield Label("", id="scan-progress", classes="status-muted")
            with VerticalGroup(id="scan-results"):
                with Horizontal(id="scan-input-row"):
                    yield Input(
                        placeholder="filter findings (text)",
                        id="scan-filter",
                    )
                    yield Label("", id="scan-findings-count")
                yield Label(
                    "severity ≥ any · category filter: any · sort: severity "
                    "(v/g/o cycle the filters; the bracket keys page)",
                    id="scan-badges",
                    classes="status-muted",
                )
                yield DataTable(id="scan-findings", cursor_type="row")
            with VerticalGroup(id="scan-detail"):
                yield Label("", id="scan-detail-title")
                yield Label("", id="scan-detail-body")
            yield Label(
                "Finding severity is qualitative evidence-based judgement, "
                "not a measurement. Zero findings here means the engine's "
                "host-side checks found nothing to report — the device is "
                "not thereby certified secure, and checks that could not "
                "run are not reported as passed.",
                id="scan-note", classes="status-muted",
            )

    def on_mount(self) -> None:
        super().on_mount()
        devices_table = self.query_one("#scan-devices", DataTable)
        devices_table.add_columns("Serial", "State", "Model (as reported)")
        findings_table = self.query_one("#scan-findings", DataTable)
        findings_table.add_columns(
            "Severity", "Category", "Title", "App", "Evidence")
        self._reconcile_scan_after_away()
        self._apply_all()
        if not self._auto_discovery_done:
            self._auto_discovery_done = True
            self.action_refresh()

    def _reconcile_scan_after_away(self) -> None:
        """Honest resume (workspace pattern): terminal outcomes streamed
        while this screen was not the visible one are LOST. If the tracked
        job is gone, say exactly that instead of pretending progress."""
        if self._scan_job_id is None or self._selected_serial is None:
            return
        try:
            handle = self.backend.active_scan_handle(self._selected_serial)
        except Exception:
            handle = None
        if handle is not None and handle.id == self._scan_job_id:
            return
        self._scan_job_id = None
        if self._scan_state == "running" or self._scan_state == "validating":
            self._scan_state = "away"
            self._progress_text = ""

    # -- status / rendering -------------------------------------------------- #

    def status_hint(self) -> str:
        if self._scan_state == "running":
            return f"scanning · target {self._selected_serial or '—'} · cancel with c"
        if self._scan_state == "completed":
            return f"scanning · last scan completed on {self._selected_serial or '—'}"
        if self._scan_state in ("cancelled", "failed", "away"):
            return f"scanning · last scan {self._scan_state}"
        return "scanning · select a device, then press a to scan"

    def _apply_all(self) -> None:
        self._render_devices()
        self._render_scope()
        self._render_banner()
        self._render_progress()
        self._render_findings()
        self._render_detail()
        self.refresh_status()

    def _render_devices(self) -> None:
        table = self.query_one("#scan-devices", DataTable)
        table.clear()
        for info in self._devices:
            table.add_row(
                info.serial,
                _STATE_WORDS.get(info.state.value, f"unknown ({info.raw_state})"),
                _honest(info.usb_props.get("model")),
                key=info.serial,
            )

    def _render_scope(self) -> None:
        target = self.query_one("#scan-target", Label)
        if self._selected_serial:
            target.update(f"target {self._selected_serial}")
        else:
            target.update("no target selected (enter on a device row)")
        scope = self.query_one("#scan-scope-state", Label)
        system_word = "included" if self._include_system else "excluded"
        deep_word = "on (engine unverified-condition note)" if self._deep else "off"
        scope.update(
            f"scope for the next scan · system apps: {system_word} · "
            f"deep scan: {deep_word} · full-device analysis reads apps and "
            "their declared permissions; it runs no destructive operation"
        )

    def _render_banner(self) -> None:
        banner = self.query_one("#scan-banner", Label)
        banner.set_classes("status-muted")
        if self._discovery_state == "no-adb":
            banner.update(
                "no bridge path saved yet — open Settings (s), save the ADB "
                "executable path, then press r"
            )
            banner.set_classes("status-warn")
        elif self._discovery_state == "discovering":
            banner.update("discovering devices … (one `adb devices` command)")
        elif self._discovery_state == "failed":
            banner.update(f"discovery failed: {self._discovery_error} — press r")
            banner.set_classes("status-error")
        elif not self._devices and self._discovery_state in ("ok", "empty"):
            banner.update(
                "no devices connected — check the cable/authorization, or "
                "press r to refresh"
            )
        elif self._devices:
            banner.update("")

    def _render_progress(self) -> None:
        progress = self.query_one("#scan-progress", Label)
        progress.set_classes("status-muted")
        if self._scan_state == "running":
            progress.update(self._progress_text or "scan started … (cancel with c)")
            progress.set_classes("")
        elif self._scan_state == "validating":
            progress.update(
                "checking that the selected device is still connected …")
        elif self._scan_state == "away":
            progress.update(
                "the scan finished while this screen was not visible — its "
                "outcome could not be streamed here; press a to scan again")
            progress.set_classes("status-warn")
        elif self._scan_state == "cancelled":
            progress.update(
                "scan cancelled by request — findings streamed before the "
                "stop remain visible below marked PARTIAL")
            progress.set_classes("status-warn")
        elif self._scan_state == "failed":
            progress.update(f"scan failed: {self._scan_error}")
            progress.set_classes("status-error")
        elif self._scan_state == "completed":
            totals = self._bundle_totals_word()
            progress.update(f"scan completed · {totals}")
            progress.set_classes("status-ok")
        else:
            progress.update("no scan yet for this target")

    def _bundle_totals_word(self) -> str:
        completed = self._completed_bundle
        if completed is None:
            return "no completed bundle this session"
        summary = completed.summary
        skipped = len(summary.skipped_apps)
        return (
            f"{summary.total_apps} app(s) analyzed ({skipped} skipped, "
            f"{summary.findings_total} finding(s)) — export via the reports "
            "screen (h)"
        )

    @property
    def _completed_bundle(self) -> Optional[ScanResultBundle]:
        try:
            last = cast("tuple", self.backend.last_scan())
        except Exception:
            return None
        if last and last[0] == "completed" and last[1] == self._selected_serial:
            return cast("ScanResultBundle", last[2])
        return None

    def _render_findings(self) -> None:
        table = self.query_one("#scan-findings", DataTable)
        rows = self._current_page_rows()
        table.clear()
        # Row keys are VIEW positions, not finding ids: the legacy parser
        # quirk can legitimately stream one stable id twice (documented),
        # so row identity must never depend on it. The position map below
        # keeps [enter]→detail exact.
        offset = self._page * PAGE_SIZE
        self._row_findings = {}
        for index, (finding, package) in enumerate(rows):
            position = offset + index
            self._row_findings[position] = finding
            table.add_row(
                _SEVERITY_LABEL.get(finding.severity, finding.severity.value),
                _CATEGORY_LABEL.get(finding.kind, finding.kind.value),
                finding.title,
                package or ("device scope" if finding.device_serial else "—"),
                str(len(finding.evidence)),
                key=str(position),
            )
        count = self.query_one("#scan-findings-count", Label)
        total = len(self._findings)
        shown = len(self._filtered_findings())
        tail = ""
        if total:
            pages = max(1, -(-shown // PAGE_SIZE))
            tail = f" · page {self._page + 1}/{pages} · {PAGE_SIZE}/page"
        count.update(f"{shown} of {total} findings{tail}")
        badges = self.query_one("#scan-badges", Label)
        severity_word = (
            "any" if self._severity_min is None
            else f"{_SEVERITY_LABEL[self._severity_min]}+"
        )
        category_word = (
            "any" if self._category is None
            else _CATEGORY_LABEL[self._category]
        )
        badges.update(
            f"severity ≥ {severity_word} · category filter: {category_word} · "
            f"sort: {self._sort_key} (v/g/o cycle the filters; the bracket "
            "keys page)"
        )

    # -- filtering / sorting -------------------------------------------------- #

    def _package_of(self, finding: Finding) -> str:
        return finding.app.package_name if finding.app is not None else ""

    def _filtered_findings(self) -> tuple:
        """Return the honest filtered VIEW — the underlying findings are
        never mutated by any filter (an explicit §10 contract)."""
        needle = self._text_filter.strip().lower()
        rows = []
        for finding in self._findings:
            if self._severity_min is not None:
                if _SEVERITY_RANK[finding.severity] > \
                        _SEVERITY_RANK[self._severity_min]:
                    continue
            if self._category is not None and finding.kind is not self._category:
                continue
            if needle:
                package = self._package_of(finding)
                hay = " ".join((
                    finding.title.lower(),
                    finding.detail.lower(),
                    _CATEGORY_LABEL.get(finding.kind, finding.kind.value).lower(),
                    package.lower(),
                ))
                if needle not in hay:
                    continue
            rows.append((finding, self._package_of(finding)))
        return self._sorted(tuple(rows))

    def _sorted(self, rows: tuple) -> tuple:
        def key(idx: int, pair: tuple) -> tuple:
            finding, package = pair
            if idx == 0:
                return (_SEVERITY_RANK[finding.severity],
                        finding.kind.value, package.lower(), finding.id)
            if idx == 1:
                return (finding.kind.value, _SEVERITY_RANK[finding.severity],
                        package.lower(), finding.id)
            if idx == 2:
                return (package.lower(), _SEVERITY_RANK[finding.severity],
                        finding.kind.value, finding.id)
            return (finding.title.lower(), _SEVERITY_RANK[finding.severity],
                    package.lower(), finding.id)

        return tuple(sorted(rows, key=lambda pair: key(_SORT_CYCLE.index(self._sort_key), pair)))

    def _current_page_rows(self) -> list:
        rows = self._filtered_findings()
        last_page = max(0, -(-len(rows) // PAGE_SIZE) - 1)
        self._page = min(self._page, last_page)
        start = self._page * PAGE_SIZE
        return list(rows[start:start + PAGE_SIZE])

    def _replace_findings(
        self, findings, status: str, streamed: Optional[int] = None,
    ) -> None:
        self._findings = tuple(findings)
        self._findings_status = status
        if streamed is not None:
            self._streamed = streamed
        self._page = 0
        self._detail_finding = None
        self._render_findings()

    # -- discovery (explicit; identical honesty to the workspace) ------------- #

    def action_refresh(self) -> None:
        backend = self.backend
        if self._discovery_state == "discovering":
            self.notify(
                "a discovery is already running — it finishes shortly",
                title="Device refresh", severity="information",
            )
            return
        try:
            saved = backend.adb_path_saved()
        except Exception as exc:
            self._discovery_state = "failed"
            self._discovery_error = _failure_word(exc)
            self._apply_all()
            return
        if saved is None:
            self._discovery_state = "no-adb"
            self._discovery_error = None
            self._apply_all()
            return
        self._discovery_state = "discovering"
        self._discovery_error = None
        self._apply_all()

        def work() -> None:
            try:
                devices = backend.list_devices()
            except Exception as exc:
                reason = _failure_word(exc)
                self.app.call_from_thread(self._apply_discovery, (), reason)
            else:
                self.app.call_from_thread(
                    self._apply_discovery, tuple(devices), None)

        self.app.run_worker(
            work, group="scan-refresh", exclusive=True, thread=True,
            exit_on_error=False, description="scan target discovery",
        )

    def _apply_discovery(self, devices: tuple, reason: Optional[str]) -> None:
        if reason is not None:
            self._discovery_state = "failed"
            self._discovery_error = reason
            self._apply_all()
            return
        self._devices = tuple(devices)
        self._discovery_state = "ok" if devices else "empty"
        serial_before = self._selected_serial
        still_here = any(
            d.serial == self._selected_serial and d.state.value == "device"
            for d in devices
        )
        if self._selected_serial is not None and not still_here:
            self._selected_serial = None
            self.notify(
                f"scan target {serial_before} is no longer connected — the "
                "scan was not started and no new target was chosen",
                title="Scan target", severity="warning",
            )
        actionable = [d.serial for d in devices if d.state.value == "device"]
        if self._selected_serial is None and len(actionable) == 1:
            self._selected_serial = actionable[0]
        elif self._selected_serial is None and len(actionable) > 1:
            self.notify(
                "multiple devices detected — select one explicitly "
                "(enter on a device row)",
                title="Scan target", severity="warning",
            )
        self._apply_all()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id == "scan-devices":
            serial = event.row_key.value
            if serial:
                self._select_device(serial)
        elif event.data_table.id == "scan-findings":
            self._open_detail(event.row_key.value)

    def _select_device(self, serial: str) -> None:
        match = next(
            (d for d in self._devices if d.serial == serial), None)
        if match is None:
            self.notify(
                f"device {serial} is not connected right now — refresh (r) first",
                title="Scan target", severity="warning",
            )
            return
        if match.state.value != "device":
            from ui_terminal.screens.workspace import _STATE_WORDS as WORDS

            word = WORDS.get(match.state.value, match.raw_state)
            self.notify(
                f"device {serial} is {word} — scans need an authorized, "
                "connected device; resolve it on the device, then refresh",
                title="Scan target", severity="warning",
            )
            return
        self._selected_serial = serial
        self._apply_all()

    # -- scan lifecycle -------------------------------------------------------- #

    def action_start_scan(self) -> None:
        self._validate_and_start(package=None)

    def action_start_single(self) -> None:
        package = self.query_one("#scan-package", Input).value.strip()
        if not package:
            self.notify(
                "type the package to analyze in the input first",
                title="Single-app scan", severity="warning",
            )
            return
        from vscanner.services.scanning.scanner import validate_package_name

        try:
            package = validate_package_name(package)
        except Exception as exc:
            self.notify(
                f"not a valid package name: {getattr(exc, 'message', exc)}",
                title="Single-app scan", severity="warning",
            )
            return
        self._validate_and_start(package=package)

    def _validate_and_start(self, package: Optional[str]) -> None:
        backend = self.backend
        if self._scan_state in ("running", "validating"):
            self.notify(
                "a scan is already in flight for this screen — cancel (c) "
                "or wait for it to finish",
                title="Scan", severity="warning",
            )
            return
        if self._selected_serial is None:
            self.notify(
                "select a device first (enter on a device row)",
                title="Scan", severity="warning",
            )
            return
        serial = self._selected_serial
        # stale-target safety: an explicit pre-flight re-check — never a
        # silent fallback to another device (§4)
        self._scan_state = "validating"
        self._scan_error = None
        self._apply_all()

        def work() -> None:
            try:
                devices = backend.list_devices()
            except Exception as exc:
                self.app.call_from_thread(
                    self._fail_preflight, serial, _failure_word(exc))
                return
            still = any(
                d.serial == serial and d.state.value == "device"
                for d in devices
            )
            if not still:
                self.app.call_from_thread(
                    self._fail_preflight, serial,
                    "the selected device is no longer connected or "
                    "authorized — refresh (r) and select an available one",
                )
                return
            self.app.call_from_thread(
                self._begin_scan_job, serial, package)

        self.app.run_worker(
            work, group="scan-preflight", exclusive=True, thread=True,
            exit_on_error=False, description="scan preflight",
        )

    def _fail_preflight(self, serial: str, reason: str) -> None:
        if self._selected_serial != serial:
            return
        self._scan_state = "failed"
        self._scan_error = reason
        self._apply_all()

    def _begin_scan_job(self, serial: str, package: Optional[str]) -> None:
        """Loop-thread job submission after the preflight passed."""
        if self._selected_serial != serial:
            return
        if self._scan_state == "running":
            return  # a job is already in flight; the preflight is stale
        try:
            handle = self.backend.start_scan_job(
                serial,
                include_system=self._include_system,
                deep=self._deep,
                package=package,
            )
        except Exception as exc:
            self._scan_state = "failed"
            self._scan_error = _failure_word(exc)
            self._apply_all()
            return
        self._scan_state = "running"
        self._scan_error = None
        self._scan_job_id = handle.id
        self._scan_kind_word = "single_app" if package else "full_device"
        self._progress_text = ""
        self._replace_findings((), "streaming", streamed=0)
        self._apply_all()

    def action_cancel_scan(self) -> None:
        if self._scan_state != "running" or self._selected_serial is None:
            self.notify(
                "no scan is running", title="Scan", severity="information",
            )
            return
        # request ≠ acknowledgement: the CANCELLED terminal event closes it
        self.backend.cancel_scan_job(self._selected_serial)
        self.notify(
            "cancellation requested — the engine stops at its next "
            "checkpoint (between apps / analysis boundary)",
            title="Scan", severity="information",
        )

    def action_toggle_system(self) -> None:
        self._include_system = not self._include_system
        self._render_scope()

    def action_toggle_deep(self) -> None:
        self._deep = not self._deep
        self._render_scope()

    # -- findings exploration ------------------------------------------------- #

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "scan-filter":
            self._text_filter = event.value
            self._page = 0
            self._render_findings()

    def action_cycle_severity(self) -> None:
        index = SEVERITY_CYCLE.index(self._severity_min)
        self._severity_min = SEVERITY_CYCLE[(index + 1) % len(SEVERITY_CYCLE)]
        self._page = 0
        self._render_findings()

    def action_cycle_category(self) -> None:
        index = (
            _CATEGORY_CYCLE.index(self._category)
            if self._category in _CATEGORY_CYCLE else 0
        )
        self._category = _CATEGORY_CYCLE[(index + 1) % len(_CATEGORY_CYCLE)]
        self._page = 0
        self._render_findings()

    def action_cycle_sort(self) -> None:
        index = _SORT_CYCLE.index(self._sort_key)
        self._sort_key = _SORT_CYCLE[(index + 1) % len(_SORT_CYCLE)]
        self._render_findings()

    def action_next_page(self) -> None:
        total = len(self._filtered_findings())
        last_page = max(0, -(-total // PAGE_SIZE) - 1)
        if self._page < last_page:
            self._page += 1
            self._render_findings()
        elif total:
            self.notify("already on the last page", severity="information")

    def action_prev_page(self) -> None:
        if self._page > 0:
            self._page -= 1
            self._render_findings()
        elif self._findings:
            self.notify("already on the first page", severity="information")

    def _open_detail(self, row_key) -> None:
        if row_key is None or not row_key.value:
            return
        try:
            position = int(row_key.value)
        except (TypeError, ValueError):
            return  # never fabricate a detail for a non-numeric row key
        finding = self._row_findings.get(position)
        if finding is None:
            return  # pagination/filter change raced the click — never fake
        self._detail_finding = finding
        self._render_detail()

    def _render_detail(self) -> None:
        detail = self.query_one("#scan-detail", VerticalGroup)
        title = self.query_one("#scan-detail-title", Label)
        body = self.query_one("#scan-detail-body", Label)
        finding = self._detail_finding
        if finding is None:
            detail.display = False
            return
        detail.display = True
        title.update(
            f"{_SEVERITY_LABEL.get(finding.severity, finding.severity.value)}"
            f" · {_CATEGORY_LABEL.get(finding.kind, finding.kind.value)}"
            f" · {finding.title}"
        )
        lines: list = [f"detail: {finding.detail}"]
        package = self._package_of(finding)
        if package:
            lines.append(f"app: {package}")
        elif finding.device_serial:
            lines.append(f"scope: device {finding.device_serial}")
        for evidence in finding.evidence:
            kind = _EVIDENCE_WORDS.get(evidence.kind, evidence.kind.value)
            lines.append(
                f"evidence ({kind}) from {_honest(evidence.source)}: "
                f"{_honest(evidence.description)}"
            )
        for remediation in finding.remediation:
            lines.append(
                f"recommended fix ({remediation.category.value}): "
                f"{remediation.recommendation}"
            )
        detected_word = (
            "review heuristic" if finding.detected_by != "scan-service"
            else "engine scanning service"
        )
        lines.append(
            f"provenance: detected by {finding.detected_by} ({detected_word}"
            f") · severity is qualitative evidence-based judgement; no "
            "per-finding numeric risk score exists in the engine (the "
            "app-level legacy risk score appears in exported reports)"
        )
        body.update("\n".join(lines[:12]))

    # -- job events ------------------------------------------------------------ #

    def on_job_event(self, event) -> None:
        if event.job_id != self._scan_job_id:
            return
        if isinstance(event, JobFindingEvent):
            # Streaming: only REAL engine findings reach the table; the
            # running scan keeps the honest stream (no counts invented).
            self._findings = tuple(self._findings) + (event.finding,)
            self._streamed += 1
            self._findings_status = "partial-stream" \
                if self._scan_state != "running" else "streaming"
            self._render_findings()
        elif isinstance(event, JobProgressEvent):
            total = event.total if event.total is not None else "…"
            current = event.context or ""
            self._progress_text = (
                f"running · {event.current}/{total} {event.unit}"
                + (f" · current: {current}" if current else "")
                + f" · findings so far: {self._streamed}"
            )
            self._render_progress()
        elif isinstance(event, JobTerminalEvent):
            self._apply_terminal(event)

    def _apply_terminal(self, event: JobTerminalEvent) -> None:
        self._scan_job_id = None
        self._progress_text = ""
        outcome = event.outcome.value
        if outcome == "succeeded":
            bundle = cast("ScanResultBundle", event.result)
            self._scan_state = "completed"
            self._apply_bundle(bundle)
            self._record_history("completed", bundle, None)
        elif outcome == "cancelled":
            self._scan_state = "cancelled"
            self._replace_findings(self._findings, "partial-stream")
            self._record_history("cancelled", None, self._streamed)
        else:
            self._scan_state = "failed"
            self._scan_error = (
                event.error.message if event.error is not None
                else "the scan job failed (no detail provided)"
            )
            self._replace_findings(self._findings, "partial-stream")
            self._record_history("failed", None, self._streamed)
        self._apply_all()

    def _apply_bundle(self, bundle: ScanResultBundle) -> None:
        findings = []
        for result in bundle.apps:
            for finding in result.findings:
                findings.append(finding)
        self._replace_findings(findings, "from-bundle")
        self.backend.remember_scan(bundle, "completed", self._selected_serial)

    def _record_history(self, status: str,
                        bundle: Optional[ScanResultBundle],
                        streamed: Optional[int]) -> None:
        """T-08 entry (counters only; NO findings text, no secret material)."""
        entry = self._history_entry(status, bundle, streamed)
        backend = self.backend

        def work() -> None:
            try:
                backend.history_entry(entry)
            except Exception as exc:
                self.app.call_from_thread(
                    self._history_write_failed, type(exc).__name__)

        self.app.run_worker(
            work, thread=True, exclusive=False, exit_on_error=False,
            description="scan history append",
        )

    def _history_write_failed(self, failure_name: str) -> None:
        self.notify(
            f"the local scan history could not be written ({failure_name}) "
            "— the scan outcome above is real and unaffected",
            title="Scan history", severity="warning",
        )

    def _history_entry(self, status: str,
                       bundle: Optional[ScanResultBundle],
                       streamed: Optional[int]) -> HistoryEntry:
        scan_id = uuid.uuid4().hex
        device_serial = self._selected_serial
        severity_counts = {key: 0 for key in
                           ("critical", "high", "medium", "low", "info")}
        if bundle is not None:
            try:
                scan_id = bundle.summary.run.request.id
            except Exception:
                pass
            for result in bundle.apps:
                for finding in result.findings:
                    severity_counts[_SEVERITY_LABEL[finding.severity]] += 1
        else:
            for finding in self._findings:
                severity_counts[_SEVERITY_LABEL[finding.severity]] += 1
        total_apps = 0
        if bundle is not None:
            total_apps = bundle.summary.total_apps
        return HistoryEntry(
            scan_id=scan_id,
            kind=self._scan_kind_word or "unknown",
            status=status,
            device_serial=device_serial,
            total_apps=total_apps,
            findings_total=(
                streamed if (streamed is not None and bundle is None)
                else _bundle_findings_total(bundle)
            ),
            severity_counts=severity_counts,
        )


def _bundle_findings_total(
    bundle: Optional[ScanResultBundle],
) -> int:
    if bundle is None:
        return 0
    return sum(len(result.findings) for result in bundle.apps)
