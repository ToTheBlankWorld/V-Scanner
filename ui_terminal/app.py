"""V-Scanner 3.0 terminal application (Stage 05 TUI foundation).

Launch: ``vscanner-tui`` (installed entry point) or ``python -m
ui_terminal``. Design tokens live in ``ui_terminal.theme``; navigation in
``ui_terminal.sections``; screens in ``ui_terminal.screens``.

Boundaries (ARCHITECTURE_DECISIONS A-03/A-04, mission §6):

* Presentation-only. Business logic stays in ``vscanner``: settings are
  read/written via :class:`vscanner.services.config.ConfigService`, the
  environment report comes from
  :func:`vscanner.services.doctor.collect_dependency_report` — never
  duplicated here. Nothing probes devices or performs network/subprocess
  work at startup; subprocess-level validation happens only on explicit
  user action (Settings → "Validate path now", worker thread).
* Startup is honest: the dashboard shows real config state and explicitly
  "not checked / not built yet" labels for everything Stage 05 does not
  own.
* Navigation replaces the top of the screen stack (``switch_screen``) from
  a per-section instance cache — repeated navigation can never create
  duplicate screens, subscriptions, or timers.

Non-interactive behavior: when stdin/stdout is not a terminal the app
prints a concise explanation and exits successfully without touching any
device state (mission §9; safe for scripts and CI).
"""

from __future__ import annotations

import sys
from typing import Optional

from textual.app import get_system_commands_provider, App
from textual.binding import Binding
from textual.command import DiscoveryHit, Hit, Hits, Provider
from textual.screen import Screen
from typing import Callable

from typing_extensions import cast

from vscanner.core.paths import config_dir, ensure_dir
from vscanner.services.config import ConfigService

from ui_terminal import sections as reg
from ui_terminal.backend import DeviceBackend, WorkspaceBackend
from ui_terminal.theme import (
    APP_TCSS, REPORTS_TCSS, SCAN_TCSS, SECTION_TCSS, STAGE08_TCSS,
    THEME_NAME, VSCANNER_THEME, WORKSPACE_TCSS,
)

__all__ = ["VScannerApp", "VScannerCommands", "main", "SECTION_TCSS", "APP_TCSS"]


class VScannerCommands(Provider):
    """Real command-palette source built from the section registry.

    Palette search filters these entries with Textual's fuzzy matcher;
    selecting one executes its callback. There are no decorative entries.
    """

    def _entries(self) -> tuple:
        """(display, search_text, help, callback) records for the palette."""
        app = self.app
        entries: list = []
        for section in reg.SECTION_REGISTRY:
            stage_note = (
                f" — coming in Stage {section.owner_stage}"
                if section.kind == "future"
                else ""
            )
            entries.append((
                f"Go to {section.title}{stage_note}",
                f"goto {section.section_id} {section.title.lower()}",
                section.title,
                _make_goto(app, section.section_id),
            ))
        entries.append((
            "Refresh environment report",
            "doctor refresh environment check report",
            "report-only environment check",
            _make_goto(app, "doctor"),
        ))
        entries.append((
            "Quit V-Scanner",
            "quit exit close application",
            "leave the application",
            app.action_quit,
        ))
        return tuple(entries)

    async def search(self, query: str) -> Hits:
        if query.strip() == "":
            # Empty queries list everything as DiscoveryHits. Never build a
            # Matcher here: Textual 8.2.8 fuzzy matching crashes on "" input
            # (verified against stock providers — guard at our boundary).
            for display, text, help_text, callback in self._entries():
                yield DiscoveryHit(display, callback, text=text, help=help_text)
            return
        matcher = self.matcher(query)
        for display, text, help_text, callback in self._entries():
            score = 0.0
            try:
                score = matcher.match(text)
            except ValueError:  # defensive: upstream fuzzy edge cases
                score = 0.0
            if score > 0:
                yield Hit(score, matcher.highlight(display), callback,
                          text=text, help=help_text)


def _make_goto(app: App, section_id: str) -> Callable[[], None]:
    vscanner_app = cast("VScannerApp", app)

    def go() -> None:
        vscanner_app.switch_to_section(section_id)

    return go


class VScannerApp(App):
    """The V-Scanner terminal application shell."""

    NAME = "V-Scanner"
    TITLE = "V-Scanner 3.0"
    SUB_TITLE = "Android security auditing"

    CSS = (APP_TCSS + SECTION_TCSS + WORKSPACE_TCSS + SCAN_TCSS
           + REPORTS_TCSS + STAGE08_TCSS)
    theme = THEME_NAME  # dispatched only after on_mount registers the palette

    COMMANDS = {VScannerCommands, get_system_commands_provider}
    """Palette sources: our command registry + Textual system commands."""

    BINDINGS = [
        Binding("d", "goto('dashboard')", "Dashboard"),
        Binding("w", "goto('devices')", "Device workspace"),
        Binding("f", "goto('scan')", "Scanning & findings"),
        Binding("h", "goto('reports')", "Reports & history"),
        Binding("m", "goto('monitoring')", "Live monitoring"),
        Binding("o", "goto('forensics')", "Forensics"),
        Binding("i", "goto('mirroring')", "Mirroring"),
        Binding("b", "goto('demo')", "Demo data"),
        Binding("e", "goto('doctor')", "Doctor"),
        Binding("s", "goto('settings')", "Settings"),
        Binding("f1", "goto('help')", "Help & keys"),
        Binding("escape", "goto('dashboard')", "Back to dashboard", show=False),
    ]
    """Direct navigation keys; ctrl+q (quit) and ctrl+p (palette) are
    inherited Textual defaults."""

    def __init__(
        self,
        config_service: Optional[ConfigService] = None,
        backend: Optional[DeviceBackend] = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        if config_service is None:
            # Production launch (A-07): user-directory config; repo-local
            # mode via VSCANNER_LOCAL is resolved by the engine.
            ensure_dir(config_dir())
            config_service = ConfigService(config_dir() / "config.json")
        self._config_service = config_service
        self._backend = backend or WorkspaceBackend(config_service)
        self._screen_cache: dict = {}
        self.last_doctor_summary: Optional[str] = None
        """Honest doctor summary the dashboard can quote; None = not run."""

    @property
    def config_service(self) -> ConfigService:
        """The authoritative config service (R-02): injected in tests."""
        return self._config_service

    @property
    def backend(self) -> DeviceBackend:
        """The single UI→engine seam (widgets never touch ADB directly)."""
        return self._backend

    # -- theme ------------------------------------------------------------ #

    def get_theme_variable_defaults(self) -> dict:
        """Fallback variables so CSS never fails to parse (single source:
        ``ui_terminal.theme.VSCANNER_THEME``)."""
        return dict(VSCANNER_THEME.variables)

    def on_mount(self) -> None:
        self.register_theme(VSCANNER_THEME)
        self.theme = THEME_NAME
        # Startup pushes the dashboard onto Textual's internal default
        # screen; after this, every stack entry carries a result callback,
        # so switch_screen (the only navigation primitive we use) is always
        # valid and can never grow the stack beyond two entries.
        self.push_screen(self._cached_screen("dashboard"))
        # One job-event pump for the whole app (Stage 06): events from the
        # engine reach the CURRENT screen only, so an unmounted workspace
        # never accumulates subscriptions.
        self._backend.start_pump(self._dispatch_job_event)

    def _dispatch_job_event(self, event) -> None:
        """Loop-thread fan-out: only the visible screen listens (gathered
        per Stage 07 to the scan + reports screens as well)."""
        from vscanner.core.events import JobEvent
        from ui_terminal.screens.reports import ReportsScreen
        from ui_terminal.screens.scan import ScanScreen
        from ui_terminal.screens.workspace import DeviceWorkspaceScreen

        if not isinstance(event, JobEvent):
            return
        screen = self.screen
        if isinstance(screen, DeviceWorkspaceScreen):
            screen.on_job_event(event)
        elif isinstance(screen, ScanScreen):
            screen.on_job_event(event)
        elif isinstance(screen, ReportsScreen):
            screen.on_job_event(event)

    def _cached_screen(self, section_id: str) -> Screen:
        """One reusable instance per section — navigation never duplicates."""
        screen = self._screen_cache.get(section_id)
        if screen is None:
            section = reg.get_section(section_id)
            assert section is not None and section.factory is not None
            screen = section.factory()
            self._screen_cache[section_id] = screen
        return screen

    def switch_to_section(self, section_id: str) -> None:
        """Navigate to a registry section, replacing the current screen.

        Unknown ids are impossible through real UI paths (rail, palette,
        bindings all read the registry); any manual call receives honest
        feedback instead of a crash.
        """
        section = reg.get_section(section_id)
        if section is None:
            self.notify(
                f"Unknown destination '{section_id}' — press f1 for the list "
                "of available sections",
                title="Navigation",
                severity="warning",
            )
            return
        self.switch_screen(self._cached_screen(section_id))

    def action_goto(self, section_id: str) -> None:
        """Binding target for direct navigation keys."""
        self.switch_to_section(section_id)

    async def action_quit(self) -> None:
        """Quit with engine cleanup: the job engine gets its documented
        grace (Stage 04 §8); the pump subscription is released first."""
        self._backend.shutdown_jobs()
        await super().action_quit()

    # App-level compose is not used: screens carry all content (the default
    # screen is built by get_default_screen()).


def main(argv: Optional[list] = None) -> int:
    """Console entry point (``vscanner-tui`` / ``python -m ui_terminal``).

    Non-interactive chains get a concise explanation and a clean exit; real
    startup failures print a short typed message without tracebacks.
    """
    del argv  # argparse-free on purpose; the TUI is its own UI
    try:
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            print(
                "vscanner-tui: this interface is interactive and needs a real "
                "terminal (stdin/stdout attached to a TTY). Nothing was probed "
                "and nothing changed. The non-TUI CLI remains available: "
                "python cli/main.py",
            )
            return 0
        app = VScannerApp()
        app.run()
        return 0
    except Exception as exc:  # concise, typed, no traceback, no secrets
        print(
            f"vscanner-tui could not start ({type(exc).__name__}): {exc}",
            file=sys.stderr,
        )
        return 1
