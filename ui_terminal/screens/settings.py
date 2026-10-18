"""Settings — config round-trip over the authoritative ConfigService.

This screen owns ZERO persistence logic: it only edits values and calls
`vscanner.services.config.ConfigService.load()/save()` (R-02 single path,
R-08 legacy import). The effective config location follows A-07: user
directory, `.vscanner` repo-local mode with ``VSCANNER_LOCAL=1``, and
``VSCANNER_DATA_DIR`` master override.

An adb-path probe ("Validate path now") is strictly user-initiated and runs
in a worker; startup never validates or probes anything.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Optional

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Input, Label
from typing_extensions import cast

from vscanner.core.errors import ConfigError, ConfigSchemaOutdated
from vscanner.services.adb.executable import check_adb_valid
from vscanner.services.config import ConfigSnapshot, ConfigService

from ui_terminal.screens.shell import ShellScreen

if TYPE_CHECKING:
    from ui_terminal.app import VScannerApp


class SettingsScreen(ShellScreen):
    """Read → edit → save → verify config through the engine service only."""

    SECTION_ID = "settings"

    def __init__(self) -> None:
        super().__init__()
        self._snapshot: Optional[ConfigSnapshot] = None
        self._error: Optional[str] = None
        self._legacy_note: str = ""
        """Honest outcome of the first-run legacy import attempt."""

    def inner_body(self) -> ComposeResult:
        with Vertical(id="settings-body"):
            yield Label("", id="settings-path-note", classes="status-muted")
            yield Label("", id="settings-legacy-note", classes="status-muted")
            yield Label("", id="settings-error", classes="status-error")
            yield Label("Device bridge (adb) executable path", id="adb-caption")
            yield Input(placeholder="(not configured yet)", id="adb-path-input")
            with Horizontal(id="settings-actions"):
                yield Button("Save config", id="save-config", compact=True)
                yield Button("Validate path now", id="validate-adb", compact=True)
            yield Label(
                "Saving round-trips through vscanner.services.config with atomic "
                "writes; legacy cli/adb_config.json is imported on first run.",
                id="settings-note", classes="status-muted",
            )

    def on_mount(self) -> None:
        super().on_mount()
        self.reload_from_service()

    # -- load / save ------------------------------------------------------ #

    @property
    def config_service(self) -> ConfigService:
        """The app's authoritative config service (injected in tests)."""
        vscanner_app = cast("VScannerApp", self.app)
        return vscanner_app.config_service
    def reload_from_service(self) -> None:
        try:
            self._snapshot = self.config_service.load()
            self._error = None
        except (ConfigError, ConfigSchemaOutdated) as exc:
            self._snapshot = ConfigSnapshot()
            self._error = f"existing config is unreadable: {exc.message}"
        else:
            self._maybe_import_legacy()
        self._render_fields()

    def _maybe_import_legacy(self) -> None:
        """R-08 first-run legacy import (R-02: ConfigService stays the single
        authority). Only attempted on a genuinely first run AND in repo-local
        dev mode (``VSCANNER_LOCAL``): a real user profile must never silently
        absorb dev-repo values. The outcome is reported honestly either way."""
        if self.config_service.path.exists():
            return
        if not os.environ.get("VSCANNER_LOCAL"):
            self._legacy_note = ""
            return
        imported = self.config_service.import_repo_legacy_config()
        if imported is None:
            self._legacy_note = "first run: no legacy config found (cli/adb_config.json absent)"
        elif imported.has_path:
            self._legacy_note = "first run: imported legacy config (cli/adb_config.json)"
            self._snapshot = imported
        else:
            self._legacy_note = "first run: legacy config imported (no bridge path set yet)"
            self._snapshot = imported

    def _render_fields(self) -> None:
        snapshot = self._snapshot or ConfigSnapshot()
        self.query_one("#settings-path-note", Label).update(
            f"config file: {self.config_service.path}"
        )
        self.query_one("#settings-legacy-note", Label).update(self._legacy_note)
        input_widget = self.query_one("#adb-path-input", Input)
        input_widget.value = snapshot.adb_path or ""
        error_label = self.query_one("#settings-error", Label)
        error_label.update(self._error or "")

    def _save(self) -> None:
        new_path = self.query_one("#adb-path-input", Input).value.strip() or None
        try:
            self.config_service.save(new_path)
        except (ConfigError, ConfigSchemaOutdated) as exc:
            self._error = f"save refused: {exc.message}"
            self._render_fields()
            return
        self._error = None
        self.reload_from_service()
        self.notify("Settings saved", title="Settings", severity="information")
        self.refresh_status()

    # -- proactive signals ------------------------------------------------ #

    def _validate(self) -> None:
        """User-initiated adb executable probe (worker, never at startup)."""
        self.run_worker(self._validate_worker(), exclusive=True)

    async def _validate_worker(self) -> None:
        new_path = self.query_one("#adb-path-input", Input).value.strip() or None
        if not new_path:
            self.notify(
                "No path entered — nothing to validate",
                severity="warning",
            )
            return
        valid = check_adb_valid(new_path)
        if valid:
            self.notify(
                f"Validation passed: ADB executable found at {new_path}",
                severity="information",
            )
        else:
            self.notify(
                "Validation failed: path does not point at a working adb "
                "executable (checking never started any device work)",
                severity="warning",
            )

    # -- status/summary --------------------------------------------------- #

    def status_hint(self) -> str:
        if self._error:
            return f"settings · {self._error}"
        snapshot = self._snapshot or ConfigSnapshot()
        if snapshot.has_path:
            return f"settings · bridge path saved · {len(snapshot.extras)} extra keys"
        return "settings · no bridge path saved (first run) — nothing probed"

    def refresh_status(self) -> None:
        self.query_one("#status-line", Label).update(self.status_hint())

    # -- events ----------------------------------------------------------- #

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save-config":
            self._save()
        elif event.button.id == "validate-adb":
            self._validate()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "adb-path-input":
            self._save()
