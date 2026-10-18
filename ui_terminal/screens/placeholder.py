"""Placeholder screens for later-stage workflows (Stage 05 navigation).

These screens exist so the navigation contract is complete and honest: a
later-stage destination is reachable, clearly labelled with its owning
roadmap stage, and makes absolutely no claim that scanning, device
operations, mirroring, or forensics are available yet. No fake data, no
distracting progress theatre, no pretend buttons.
"""

from __future__ import annotations

from dataclasses import dataclass

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Label

from ui_terminal.screens.shell import ShellScreen

__all__ = ["PlaceholderFutureScreen", "SectionRef"]


@dataclass(frozen=True, slots=True)
class SectionRef:
    """Registry info a placeholder screen needs (breaks the import cycle)."""

    section_id: str
    title: str
    owner_stage: str


class PlaceholderFutureScreen(ShellScreen):
    """Honest "built in Stage N" screen for a future-stage workflow."""

    def __init__(self, section: SectionRef) -> None:
        super().__init__()
        self._section = section
        # plain instance attribute (mypy-safe override of the class field):
        # drives rail highlight + brand section from the registry.
        self.SECTION_ID = section.section_id

    def inner_body(self) -> ComposeResult:
        with Vertical():
            yield Label(
                f"{self._section.title} · not implemented yet "
                f"(owned by Stage {self._section.owner_stage} of the roadmap)",
                classes="vs-placeholder-banner",
            )
            yield Label(
                "This screen is a navigation placeholder. It deliberately shows "
                "no data, no fake device state, and no pretend controls: the "
                "workflow lands in a later stage, and the shell will host it "
                "here without replacing the architecture.",
                classes="vs-placeholder-note status-muted",
            )
            yield Label(
                "Press escape to return to the dashboard.",
                classes="status-muted",
            )

    def status_hint(self) -> str:
        return (
            f"{self._section.title} · not built yet "
            f"(Stage {self._section.owner_stage})"
        )
