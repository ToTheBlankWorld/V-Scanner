"""Navigation registry for the V-Scanner desktop shell (Stage 09).

Mirrors the TUI pattern (``ui_terminal/sections.py``): one authoritative
table drives the navigation rail, the section headings, the honest
placeholder states and the help screen — so labels can never drift from
what is actually reachable.

Kinds:

* ``"live"``     — implemented in this stage; a builder in the shell.
* ``"future"``   — owned by a later stage; rendered as an honest
                   placeholder that fakes nothing (Stage 09 mission §3).
* ``"dialog"``   — activates a modal dialog; the Current-section selection
                   does not change (``Settings`` opens ``SettingsDialog``).

Section IDs are stable (tests and later stages address them directly).
Desktop navigation uses the rail (click / arrow keys / Enter) — no terminal
single-letter bindings; documented desktop shortcuts live in the help
section (F1) and TUI_KEYMAP stays terminal-only.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["DesktopSection", "SECTION_REGISTRY", "get_section",
           "live_sections", "future_sections", "UnknownSectionError"]


class UnknownSectionError(LookupError):
    """Raised when an invalid/unknown section id is addressed by code."""


@dataclass(frozen=True, slots=True)
class DesktopSection:
    """One navigable destination of the desktop application shell."""

    section_id: str
    """Stable registry key (tests, shell dispatch and docs address this)."""

    title: str
    """Human label shown in the rail / section header / page state."""

    subtitle: str
    """One-line description shown under the section title on switch."""

    kind: str
    """``"live"``, ``"future"`` or ``"dialog"`` — see module docstring."""

    owner_stage: str
    """Delivering roadmap stage for placeholders ("" for live sections)."""

    description: str
    """Honest accessible description (also the nav item tooltip)."""


SECTION_REGISTRY: tuple[DesktopSection, ...] = (
    DesktopSection(
        "dashboard", "Dashboard",
        "Engine readiness and environment overview",
        "live", "",
        "Environment readiness overview — real config and dependency state only.",
    ),
    DesktopSection(
        "devices", "Device workspace",
        "Device discovery, info, and inventory",
        "live", "",
        "Discover connected Android devices, inspect their details and "
        "browse their installed apps (refresh runs on demand; nothing "
        "probes automatically before you open it).",
    ),
    DesktopSection(
        "scan", "Scanning & findings",
        "Scan targets, live progress, findings explorer",
        "live", "",
        "Scan an explicitly selected device with the shared engine, watch "
        "real engine progress and cancellable results, and explore the "
        "typed findings it reports.",
    ),
    DesktopSection(
        "reports", "Reports & history",
        "Report export and scan history",
        "live", "",
        "Export the last completed full-device scan through the legacy "
        "report service and read the local counters-only scan history.",
    ),
    DesktopSection(
        "monitoring", "Live monitoring",
        "Sensors, and camera/mic/location usage polls",
        "live", "",
        "Host-side, read-only observation of one explicitly selected "
        "device: honest sensor rows and camera/microphone/location usage "
        "polls streamed from the monitoring service. This is NOT "
        "continuous Android background monitoring — each poll is one "
        "snapshot the user starts and stops explicitly.",
    ),
    DesktopSection(
        "forensics", "Forensics",
        "Case-first extraction and evidence review",
        "live", "",
        "Case-first evidence extraction against an explicitly selected "
        "device: app databases (byte-exact, sha256-recorded), text "
        "captures, WiFi networks (redacted by default), and report.json. "
        "Clear-text WiFi secrets require the exact typed acknowledgement "
        "and only write with the service's own confirmation gate.",
    ),
    DesktopSection(
        "mirroring", "Mirroring",
        "scrcpy screen mirroring lifecycle",
        "live", "",
        "Launch, list, and stop a validated scrcpy mirror for an "
        "explicitly selected device. Requires a VALIDATED scrcpy tool; an "
        "unvalidated tool is refused honestly. Windows display behavior "
        "of the real scrcpy window is not verified by this project.",
    ),
    DesktopSection(
        "demo", "Demo data",
        "Generated demo findings",
        "live", "",
        "Deterministic demo dataset built in memory by the demo service — "
        "no device is contacted, no real scan data is touched, every "
        "finding is labeled [DEMO].",
    ),
    DesktopSection(
        "doctor", "Doctor",
        "Read-only environment and dependency report",
        "live", "",
        "Doctor report (read-only): engine packages and runtime environment.",
    ),
    DesktopSection(
        "settings", "Settings",
        "ADB configuration",
        "dialog", "",
        "Settings opens the ADB path dialog — inline in the rail via key Ctrl+comma as well.",
    ),
    DesktopSection(
        "help", "Help & keys",
        "About, shortcuts and boundaries",
        "live", "",
        "About V-Scanner desktop, keyboard shortcuts and stage boundaries.",
    ),
)

INITIAL_SECTION_ID = "dashboard"
"""Deterministic startup section (registry head; Stage 09 mission §6.1)."""


def get_section(section_id: str) -> DesktopSection:
    """Return the registry entry for ``section_id`` (typed on unknown)."""
    for section in SECTION_REGISTRY:
        if section.section_id == section_id:
            return section
    raise UnknownSectionError(f"unknown desktop section id: {section_id!r}")


def live_sections() -> tuple[DesktopSection, ...]:
    return tuple(s for s in SECTION_REGISTRY if s.kind == "live")


def future_sections() -> tuple[DesktopSection, ...]:
    return tuple(s for s in SECTION_REGISTRY if s.kind == "future")
