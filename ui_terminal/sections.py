"""Navigation registry for the V-Scanner TUI.

One table drives the whole navigation surface: the sidebar rail, the app
keyboard bindings, the command-palette entries, the help screen and the
keymap document all render from :data:`SECTION_REGISTRY` (checked by tests),
so shortcut text can never drift from actual behavior.

Sections are all ``kind="live"`` as of Stage 08; ``future_sections()``
returns nothing today but stays part of the API for later stages.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from textual.screen import Screen

__all__ = ["Section", "SECTION_REGISTRY", "get_section", "live_sections", "future_sections"]


@dataclass(frozen=True, slots=True)
class Section:
    """One navigable destination of the application shell."""

    section_id: str
    """Stable registry key (tests, palette, and dispatch address this)."""
    title: str
    """Human label shown in the rail / status line / palette."""
    binding: str
    """Key that jumps here directly (empty string → navigation-menu only)."""
    kind: str
    """``"live"`` for implemented screens, ``"future"`` for placeholders."""
    owner_stage: str
    """Delivering roadmap stage for ``future`` sections (``""`` for live)."""
    factory: Callable[[], Screen]
    """Builds a fresh screen instance (``switch_screen`` prevents duplicates)."""


def get_section(section_id: str):
    for section in SECTION_REGISTRY:
        if section.section_id == section_id:
            return section
    return None


def live_sections() -> tuple:
    return tuple(s for s in SECTION_REGISTRY if s.kind == "live")


def future_sections() -> tuple:
    return tuple(s for s in SECTION_REGISTRY if s.kind == "future")


# Lazy imports keep this module free of screen imports at load time (avoid
# import cycles: screens import this registry, so it must not import them
# at module level).
def _dashboard() -> Screen:
    from ui_terminal.screens.dashboard import DashboardScreen

    return DashboardScreen()


def _doctor() -> Screen:
    from ui_terminal.screens.doctor import DoctorScreen

    return DoctorScreen()


def _settings() -> Screen:
    from ui_terminal.screens.settings import SettingsScreen

    return SettingsScreen()


def _help() -> Screen:
    from ui_terminal.screens.help import HelpScreen

    return HelpScreen()


def _devices() -> Screen:
    from ui_terminal.screens.workspace import DeviceWorkspaceScreen

    return DeviceWorkspaceScreen()


def _scan() -> Screen:
    from ui_terminal.screens.scan import ScanScreen

    return ScanScreen()


def _reports() -> Screen:
    from ui_terminal.screens.reports import ReportsScreen

    return ReportsScreen()


def _monitoring() -> Screen:
    from ui_terminal.screens.monitoring import LiveMonitoringScreen

    return LiveMonitoringScreen()


def _forensics() -> Screen:
    from ui_terminal.screens.forensics import ForensicsScreen

    return ForensicsScreen()


def _mirroring() -> Screen:
    from ui_terminal.screens.mirroring import MirroringScreen

    return MirroringScreen()


def _demo() -> Screen:
    from ui_terminal.screens.demo import DemoScreen

    return DemoScreen()


def _future(section_id: str, title: str, stage: str) -> Section:
    """A later-stage destination rendered as an honest placeholder screen."""
    from ui_terminal.screens.placeholder import PlaceholderFutureScreen, SectionRef

    def build() -> Screen:
        return PlaceholderFutureScreen(
            section=SectionRef(section_id, title, stage)
        )

    return Section(section_id, title, "", "future", stage, build)


SECTION_REGISTRY: tuple[Section, ...] = (
    Section("dashboard", "Dashboard", "d", "live", "", _dashboard),
    Section("devices", "Device workspace", "w", "live", "", _devices),
    Section("scan", "Scanning & findings", "f", "live", "", _scan),
    Section("reports", "Reports & history", "h", "live", "", _reports),
    Section("monitoring", "Live monitoring", "m", "live", "", _monitoring),
    Section("forensics", "Forensics", "o", "live", "", _forensics),
    Section("mirroring", "Mirroring", "i", "live", "", _mirroring),
    Section("demo", "Demo data", "b", "live", "", _demo),
    Section("doctor", "Doctor", "e", "live", "", _doctor),
    Section("settings", "Settings", "s", "live", "", _settings),
    Section("help", "Help & keys", "f1", "live", "", _help),
)
