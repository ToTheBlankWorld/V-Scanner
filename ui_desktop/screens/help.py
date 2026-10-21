"""Help & keys screen (Stage 09 desktop).

Documents the real desktop shortcuts (kept in sync with the shell's
``QShortcut`` definitions — the shell supplies the authoritative table this
module renders via :func:`build_help_section`) and states the product
boundaries honestly.
"""

from __future__ import annotations

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from .. import __version__
from ..widgets import MetadataRow, Panel

__all__ = ["build_help_section", "SHORTCUT_ROWS"]


SHORTCUT_ROWS: tuple[tuple[str, str], ...] = (
    ("Tab / Shift+Tab", "move keyboard focus forward / backward"),
    ("Up / Down (in the rail)", "move between sections"),
    ("Enter / Space (in the rail)", "activate the selected section"),
    ("Ctrl+,", "open Settings (ADB path)"),
    ("F1", "jump to Help & keys"),
    ("Ctrl+Q", "close the application"),
)


def build_help_section(shell_closes_note: str = "") -> QWidget:
    page = QWidget()
    outer = QVBoxLayout(page)
    outer.setContentsMargins(0, 0, 0, 0)
    outer.setSpacing(12)

    shortcuts_panel = Panel(page)
    layout = Panel.body_layout(shortcuts_panel)
    heading = QLabel("Keyboard shortcuts", shortcuts_panel)
    heading.setObjectName("panelHeading")
    layout.addWidget(heading)
    for key, action in SHORTCUT_ROWS:
        layout.addWidget(MetadataRow(key, action))
    outer.addWidget(shortcuts_panel)

    about_panel = Panel(page)
    layout = Panel.body_layout(about_panel)
    heading = QLabel("About", about_panel)
    heading.setObjectName("panelHeading")
    layout.addWidget(heading)
    layout.addWidget(MetadataRow(
        "Application", f"V-Scanner 3.0 desktop foundation — v{__version__}"))
    layout.addWidget(MetadataRow(
        "Engine", "the shared V-Scanner engine powers the CLI, the TUI and "
                  "this desktop shell; no logic is duplicated in the UI layer"))
    layout.addWidget(MetadataRow(
        "Stage scope",
        "Stages 09–12 deliver the shell, design system, device workspace, "
        "scanning/findings/reports/history, and the Stage 12 workflows "
        "(monitoring, forensics, mirroring, demo data, administration)"))
    if shell_closes_note:
        note = QLabel(shell_closes_note)
        note.setObjectName("hintText")
        note.setWordWrap(True)
        layout.addWidget(note)
    outer.addWidget(about_panel)

    boundaries_panel = Panel(page)
    layout = Panel.body_layout(boundaries_panel)
    heading = QLabel("Boundaries", boundaries_panel)
    heading.setObjectName("panelHeading")
    layout.addWidget(heading)
    text = QLabel(
        "This desktop shell never launches processes or touches devices "
        "directly — all ADB, scan, extraction and mirroring work stays in "
        "the shared engine behind its services. Results are always what "
        "the engine reported (unavailability, failures and refusals shown "
        "verbatim); nothing is faked, invented, or silently retried, and "
        "device-side side effects stay behind explicit double-gated "
        "confirmations.",
        boundaries_panel)
    text.setObjectName("secondaryText")
    text.setWordWrap(True)
    layout.addWidget(text)
    outer.addWidget(boundaries_panel)

    outer.addStretch(1)
    page.setAccessibleName("Help")
    return page
