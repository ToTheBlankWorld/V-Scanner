"""Device workspace (Stage 06): discovery, selection, details, inventory.

Layout (prompt §4) on top of the Stage 05 shell chrome:

* header — section title, explanation, last-success time, refresh action;
* device list — one honest row per discovered device (serial, connection
  state as words, model from ``adb devices`` properties when the device
  actually reported one);
* selected-device details — SC-4 profile fields through
  :class:`vscanner.services.adb.device_info.DeviceInfoService`, missing
  values rendered as "unknown" (never fabricated);
* inventory — the selected device's packages streamed from an APP_LISTING
  job (Stage 04 event pipeline), with filter + explicit pagination and
  honest ``derived`` label badges.

Hard honesty rules implemented here:

* Nothing runs at app startup; opening the workspace runs exactly ONE
  discovery (documented), further updates are explicit (``r``).
* Selection is explicit (Enter on a row); a single actionable device is
  selected automatically because the choice is unambiguous — with multiple
  devices NOTHING is auto-selected.
* Offline/unauthorized/recovery rows are visible but never silently become
  selection targets; feedback explains why.
* Root state is the engine tri-state: "not determined" until Stage 08 owns
  a verified probe. No phone-number row exists (the engine deliberately
  does not expose one — legacy showed a hardcoded N/A).
* Device facts are configuration reads, never presented as a security
  assessment; error text is redaction-safe engine output, no tracebacks.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, cast

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalGroup
from textual.widgets import Button, DataTable, Input, Label

from ui_terminal.backend import DeviceBackend
from ui_terminal.screens.shell import ShellScreen

__all__ = ["DeviceWorkspaceScreen"]

PAGE_SIZE = 100
"""Explicit inventory pagination; 150+ apps never render unpaginated."""

_STATE_WORDS = {
    "device": "connected",
    "offline": "offline",
    "unauthorized": "unauthorized",
    "recovery": "recovery",
}
_ROOT_WORDS = {
    "rooted": "rooted (verified probe)",
    "not_rooted": "not rooted (verified probe)",
    "unknown": "not determined (verified root probe arrives in Stage 08 — nothing is claimed)",
}

_PROFILE_FIELDS = (
    ("Manufacturer", "mfr"),
    ("Model", "model"),
    ("Brand", "brand"),
    ("Device (codename)", "device"),
    ("Hardware", "hardware"),
    ("Android version", "android"),
    ("SDK level", "sdk_int"),
    ("Security patch", "patch"),
    ("Build ID", "build_id"),
    ("Build fingerprint", "fingerprint"),
    ("Bootloader", "bootloader"),
    ("Kernel", "kernel"),
    ("IP address", "ip"),
    ("Wi-Fi MAC", "mac"),
    ("Locale", "locale"),
    ("Timezone", "timezone"),
)


def _honest(value) -> str:
    """One formatting rule for every displayed profile value."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return "unknown"
    return str(value)


class DeviceWorkspaceScreen(ShellScreen):
    """Discovery + selection + details + inventory for real devices."""

    SECTION_ID = "devices"

    BINDINGS = [
        Binding("r", "refresh", "Refresh devices"),
        Binding("a", "list_apps", "List apps"),
        Binding("t", "toggle_system", "System apps on/off"),
        Binding("c", "cancel_listing", "Cancel listing"),
        Binding("[", "prev_page", "Previous page"),
        Binding("]", "next_page", "Next page"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._devices: tuple = ()
        self._last_success: Optional[datetime] = None
        # discovery state: idle | discovering | ok | empty | failed | no-adb
        self._discovery_state = "idle"
        self._discovery_error: Optional[str] = None

        self._selected_serial: Optional[str] = None
        self._profile = None
        # details state: none | probing | ok | failed
        self._profile_state = "none"
        self._profile_error: Optional[str] = None

        self._apps: tuple = ()
        # listing state: idle | running | ok | cancelled | failed
        self._listing_state = "idle"
        self._listing_error: Optional[str] = None
        self._listing_job_id: Optional[str] = None
        self._include_system = False
        self._filter_text = ""
        self._page = 0
        self._auto_discovery_done = False

    @property
    def backend(self) -> DeviceBackend:
        """The app-owned engine seam, typed for the checker (no leaks)."""
        # the app genuinely owns this attribute; the narrow cast interface
        # avoids threading VScannerApp generics through every screen call
        return cast(DeviceBackend, getattr(self.app, "backend"))

    # -- composition -------------------------------------------------------- #

    def inner_body(self) -> ComposeResult:
        with Vertical(id="ws-body"):
            with Horizontal(id="ws-header"):
                yield Button("Refresh · r", id="ws-refresh-btn", flat=True,
                             compact=True)
                yield Label("", id="ws-updated", classes="status-muted")
            yield Label(
                "Discover real devices through the shared engine. Nothing is "
                "probed automatically at startup; opening this screen runs "
                "one discovery, later updates are explicit (r).",
                id="ws-explain", classes="status-muted",
            )
            yield Label("", id="ws-banner", classes="status-muted")
            yield DataTable(id="ws-devices", cursor_type="row")
            yield Label("", id="ws-selected", classes="status-muted")
            yield DataTable(id="ws-details", show_cursor=False)
            yield Label(
                "Device facts are configuration reads — not a security "
                "assessment; root state stays 'not determined' until a "
                "verified probe exists (Stage 08).",
                id="ws-security-note", classes="status-muted",
            )
            with VerticalGroup(id="ws-listing"):
                with Horizontal(id="ws-listing-row"):
                    yield Button("List apps · a", id="ws-list-btn", flat=True,
                                 compact=True)
                    yield Input(
                        placeholder="filter apps (package or label)",
                        id="ws-filter",
                    )
                yield Label("", id="ws-listing-banner", classes="status-muted")
                yield DataTable(id="ws-apps", show_cursor=True)

    def on_mount(self) -> None:
        super().on_mount()
        devices_table = self.query_one("#ws-devices", DataTable)
        devices_table.add_columns("Serial", "State", "Model (as reported)")
        details_table = self.query_one("#ws-details", DataTable)
        details_table.add_columns("Field", "Value")
        apps_table = self.query_one("#ws-apps", DataTable)
        apps_table.add_columns("Package", "Label", "Label source", "Kind")
        self._reconcile_listing_after_away()
        self._apply_all()
        if not self._auto_discovery_done:
            self._auto_discovery_done = True
            self.action_refresh()

    def _reconcile_listing_after_away(self) -> None:
        """Honest resume: job outcomes streamed while this screen was not
        the current one are LOST (the app dispatches to the visible screen
        only). If the tracked job is gone, say exactly that — never imply
        un-delivered results are on screen."""
        if self._listing_job_id is None or self._selected_serial is None:
            return
        try:
            handle = self.backend.active_listing_handle(self._selected_serial)
        except Exception:
            handle = None
        if handle is not None and handle.id == self._listing_job_id:
            return  # still running (or retained): events resume arriving
        self._listing_job_id = None
        if self._listing_state == "running":
            self._listing_state = "away"
            self._listing_error = None

    # -- status / rendering ------------------------------------------------- #

    def status_hint(self) -> str:
        count = len(self._devices)
        if self._discovery_state == "no-adb":
            return "device workspace · adb not configured — set the path in Settings (s)"
        if self._discovery_state == "discovering":
            base = "device workspace · discovering devices …"
        elif count == 1 and self._selected_serial:
            base = f"device workspace · 1 device · target {self._selected_serial}"
        elif count > 1:
            base = (
                f"device workspace · {count} devices · "
                f"select explicitly (enter on a row)"
            )
        elif count == 1:
            base = "device workspace · 1 device · not selected yet (enter on the row)"
        elif self._discovery_state == "failed":
            base = "device workspace · discovery failed — press r to retry"
        else:
            base = "device workspace · no devices"
        if self._listing_state == "running":
            base += " · listing apps …"
        return base

    def _apply_all(self) -> None:
        """Refit every pane from current state (cheap; explicit calls only)."""
        self._render_devices()
        self._render_selected()
        self._render_details()
        self._render_apps()
        self.refresh_status()
        self._render_updated()

    def _render_updated(self) -> None:
        stamp = (
            f"devices last updated {self._last_success:%Y-%m-%d %H:%M:%S UTC}"
            if self._last_success else ""
        )
        self.query_one("#ws-updated", Label).update(stamp)

    def _render_devices(self) -> None:
        table = self.query_one("#ws-devices", DataTable)
        table.clear()
        for info in self._devices:
            table.add_row(
                info.serial,
                _STATE_WORDS.get(info.state.value, f"unknown ({info.raw_state})"),
                _honest(info.usb_props.get("model")),
                key=info.serial,
            )
        banner = self.query_one("#ws-banner", Label)
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
            stale = (
                " — the rows below are the last successful list and may be "
                "stale" if self._devices else ""
            )
            banner.update(
                f"discovery failed: {self._discovery_error}{stale}"
            )
            banner.set_classes("status-error")
        elif not self._devices and self._discovery_state in ("ok", "empty"):
            banner.update(
                "no devices connected — check the cable/authorization, or "
                "press r to refresh"
            )
        elif self._devices:
            banner.update("")

    def _render_selected(self) -> None:
        label = self.query_one("#ws-selected", Label)
        if self._selected_serial:
            label.update(
                f"selected device: {self._selected_serial} "
                f"(later operations target this device; "
                f"enter a device row to change selection)"
            )
            label.set_classes("status-ok")
        else:
            label.set_classes("status-muted")
            if len(self._devices) == 1:
                label.update(
                    "device rows · press enter (or space) on the row to select "
                    "this device for details and app listing"
                )
            elif len(self._devices) > 1:
                label.update(
                    f"{len(self._devices)} devices detected — nothing is "
                    f"selected implicitly; choose one with enter on its row"
                )
            else:
                label.update("")

    def _render_details(self) -> None:
        table = self.query_one("#ws-details", DataTable)
        table.clear()
        if self._profile_state == "probing":
            table.add_row("profile", "collecting device facts … (SC-4 probes)")
            return
        if self._profile_state == "failed":
            table.add_row("profile", f"unavailable — {self._profile_error}")
            return
        if self._profile is None or self._selected_serial is None:
            table.add_row("profile", "not checked — select a device first")
            return
        profile = self._profile
        table.add_row("Serial", self._selected_serial)
        for caption, attr in _PROFILE_FIELDS:
            table.add_row(caption, _honest(getattr(profile, attr, None)))
        table.add_row(
            "Root state",
            _ROOT_WORDS.get(getattr(profile.root_status, "value", "unknown"),
                            "not determined"),
        )

    def _render_apps(self) -> None:
        table = self.query_one("#ws-apps", DataTable)
        rows = self._current_page_rows()
        table.clear()
        for info in rows:
            table.add_row(
                info.package_name,
                info.label if info.label != "(unknown)" else "unknown",
                "derived (heuristic)" if info.label_source.value == "heuristic"
                else info.label_source.value,
                "system" if info.is_system else "3rd-party",
            )
        banner = self.query_one("#ws-listing-banner", Label)
        banner.set_classes("status-muted")
        total = len(self._filtered_apps())
        if self._listing_state == "running":
            banner.update("listing installed apps … (cancel with c)")
        elif self._listing_state == "ok":
            pages = max(1, -(-total // PAGE_SIZE))
            page_word = (
                f"page {self._page + 1}/{pages}" if total else "no apps"
            )
            tail = f" · filter '{self._filter_text}'" if self._filter_text else ""
            banner.update(f"{total} apps · {page_word} · 100 per page{tail}")
        elif self._listing_state == "cancelled":
            banner.update("app listing cancelled — press a to start again")
        elif self._listing_state == "away":
            banner.update(
                "app listing finished while the screen was not visible — "
                "its results could not be streamed here; press a to list again"
            )
        elif self._listing_state == "failed":
            banner.update(
                f"app listing failed: {self._listing_error} — press a to retry"
            )
            banner.set_classes("status-error")
        elif not self._selected_serial:
            banner.update(
                "select a device (enter on a device row) to list its apps"
            )
        else:
            banner.update("apps not listed yet — press a")

    # -- filtering / pagination --------------------------------------------- #

    def _filtered_apps(self) -> list:
        needle = self._filter_text.strip().lower()
        if not needle:
            return list(self._apps)
        return [
            info for info in self._apps
            if needle in info.package_name.lower()
            or needle in (info.label or "").lower()
        ]

    def _current_page_rows(self) -> list:
        rows = self._filtered_apps()
        last_page = max(0, -(-len(rows) // PAGE_SIZE) - 1)
        self._page = min(self._page, last_page)
        start = self._page * PAGE_SIZE
        return rows[start:start + PAGE_SIZE]

    # -- discovery (explicit; one worker at a time) ------------------------- #

    def action_refresh(self) -> None:
        backend = self.backend
        if self._discovery_state == "discovering":
            self.notify(
                "a discovery is already running — it finishes shortly",
                title="Device refresh",
                severity="information",
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
            except Exception as exc:  # typed engine errors surface here
                reason = _failure_word(exc)
                self.app.call_from_thread(
                    self._apply_discovery, (), reason,
                )
            else:
                self.app.call_from_thread(self._apply_discovery, tuple(devices), None)

        self.app.run_worker(
            work, group="ws-refresh", exclusive=True, thread=True,
            exit_on_error=False, description="device discovery",
        )

    def _apply_discovery(self, devices: tuple, reason: Optional[str]) -> None:
        """Loop-thread application of one discovery outcome."""
        if reason is not None:
            # Failed refresh: the previous successful list is kept but
            # clearly marked stale — it must not look like fresh truth.
            self._discovery_state = "failed"
            self._discovery_error = reason
            self._apply_all()
            return
        self._devices = tuple(devices)
        self._discovery_state = "ok" if devices else "empty"
        self._last_success = datetime.now(timezone.utc)
        still_here = any(
            d.serial == self._selected_serial and d.state.value == "device"
            for d in devices
        )
        if self._selected_serial is not None and not still_here:
            self._invalidate_selection("selected device is no longer connected")
        actionable = [
            d.serial for d in devices if d.state.value == "device"
        ]
        if actionable and self._selected_serial is None:
            if len(actionable) == 1:
                # unambiguous: safe to preselect, clearly shown as selected
                self._select_device(actionable[0], announce=False)
            elif len(actionable) > 1:
                self.notify(
                    "multiple devices detected — select one explicitly "
                    "(enter on a device row)",
                    title="Device selection",
                    severity="warning",
                )
        self._apply_all()

    def _invalidate_selection(self, reason: str) -> None:
        self._selected_serial = None
        self._profile = None
        self._profile_state = "none"
        self._profile_error = None
        self._apps = ()
        self._listing_state = "idle"
        self._listing_error = None
        self._page = 0
        self.notify(reason, title="Device selection", severity="warning")

    # -- selection ---------------------------------------------------------- #

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id != "ws-devices":
            return
        serial = event.row_key.value
        if serial:
            self._select_device(serial, announce=True)

    def _select_device(self, serial: str, announce: bool) -> None:
        match = next(
            (d for d in self._devices if d.serial == serial), None)
        if match is None:
            self.notify(
                f"device {serial} is not connected right now — refresh (r) first",
                title="Device selection", severity="warning",
            )
            return
        if match.state.value != "device":
            word = _STATE_WORDS.get(match.state.value, match.raw_state)
            self.notify(
                f"device {serial} is {word} — details need an authorized, "
                f"connected device; resolve it on the device, then refresh (r)",
                title="Device selection", severity="warning",
            )
            return
        self._selected_serial = serial
        self._profile = None
        self._profile_state = "probing"
        self._profile_error = None
        if announce:
            self.notify(
                f"selected {serial} — details follow; press a to list apps",
                title="Device selection", severity="information",
            )
        self._apply_all()

        backend = self.backend

        def work() -> None:
            try:
                profile = backend.profile(serial)
            except Exception as exc:
                reason = _failure_word(exc)
                self.app.call_from_thread(
                    self._apply_profile, serial, None, reason)
            else:
                self.app.call_from_thread(
                    self._apply_profile, serial, profile, None)

        self.app.run_worker(
            work, group="ws-profile", exclusive=True, thread=True,
            exit_on_error=False, description="device profile",
        )

    def _apply_profile(self, serial: str, profile, reason: Optional[str]) -> None:
        if self._selected_serial != serial:
            return  # stale probe for a superseded selection
        if reason is not None:
            self._profile = None
            self._profile_state = "failed"
            self._profile_error = reason
        else:
            self._profile = profile
            self._profile_state = "ok"
            self._profile_error = None
        self._render_details()
        self.refresh_status()

    # -- inventory (job pipeline) ------------------------------------------- #

    def action_list_apps(self) -> None:
        if self._selected_serial is None:
            self.notify(
                "select a device first (enter on a device row)",
                title="App inventory", severity="warning",
            )
            return
        backend = self.backend
        self._listing_state = "running"
        self._listing_error = None
        self._render_apps()
        try:
            handle = backend.start_listing_job(
                self._selected_serial, include_system=self._include_system)
        except Exception as exc:
            self._listing_state = "failed"
            self._listing_error = _failure_word(exc)
            self._render_apps()
            return
        self._listing_job_id = handle.id

    def action_toggle_system(self) -> None:
        self._include_system = not self._include_system
        if self._selected_serial is None:
            self.notify(
                f"system apps will be {'included' if self._include_system else 'excluded'} "
                "next time you list (select a device first)",
                title="App inventory", severity="information",
            )
            return
        self.notify(
            f"system apps {'included' if self._include_system else 'excluded'} — "
            "re-listing",
            title="App inventory", severity="information",
        )
        self._listing_state = "idle"
        self.action_list_apps()

    def action_cancel_listing(self) -> None:
        if self._listing_state != "running" or not self._selected_serial:
            self.notify(
                "no listing is running", title="App inventory",
                severity="information",
            )
            return
        self.backend.cancel_listing_job(self._selected_serial)

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "ws-filter":
            return
        self._filter_text = event.value
        self._page = 0
        self._render_apps()

    def action_next_page(self) -> None:
        total = len(self._filtered_apps())
        last_page = max(0, -(-total // PAGE_SIZE) - 1)
        if self._page < last_page:
            self._page += 1
            self._render_apps()
        elif self._listing_state == "ok":
            self.notify("already on the last page", severity="information")

    def action_prev_page(self) -> None:
        if self._page > 0:
            self._page -= 1
            self._render_apps()
        elif self._apps:
            self.notify("already on the first page", severity="information")

    # -- job events (marshalled by the app from the engine pump) ------------- #

    def on_job_event(self, event) -> None:
        """APP_LISTING lifecycle events for the tracked job."""
        from vscanner.core.events import JobTerminalEvent

        if event.job_id != self._listing_job_id:
            return  # a stale or foreign job — never fabricate from it
        if isinstance(event, JobTerminalEvent):
            self._listing_job_id = None
            if event.outcome.value == "succeeded":
                rows = tuple(event.result or ())
                self._apps = rows
                self._listing_state = "ok"
                self._page = 0
            elif event.outcome.value == "cancelled":
                self._listing_state = "cancelled"
                self._listing_error = None
            else:
                self._listing_state = "failed"
                error = event.error
                self._listing_error = (
                    error.message if error is not None
                    else "the listing job failed (no detail provided)"
                )
            self._render_apps()
            self.refresh_status()


def _failure_word(exc: Exception) -> str:
    """Typed, redaction-honest one-liner for any discovery/probe failure."""
    from vscanner.core.errors import (
        AdbCommandError, AdbNotAvailable, ConfigError, VScannerError,
    )

    if isinstance(exc, AdbNotAvailable):
        return (
            "ADB executable not launchable — check the saved path in "
            "Settings (s), then press r"
        )
    if isinstance(exc, AdbCommandError):
        if exc.timeout:
            return "the adb command timed out — press r to retry"
        excerpt = (exc.stderr_excerpt or "").strip()
        tail = f" ({excerpt[:200]})" if excerpt else ""
        return f"adb command failed (exit code {exc.returncode}){tail} — press r to retry"
    if isinstance(exc, ConfigError):
        return "config file unreadable — open Settings (s) or Doctor (e)"
    if isinstance(exc, VScannerError):
        return f"{exc.message} — press r to retry"
    # unknown exception: no traceback, no internals, honest type name only
    return f"unexpected failure ({type(exc).__name__}); nothing was changed — press r to retry"
