"""Help & keymap screen — one source of truth: the section registry.

The rendered table is generated from :data:`ui_terminal.sections.
SECTION_REGISTRY` plus the app-level bindings, and the keymap document
(``docs/vscanner-3/TUI_KEYMAP.md``) is test-checked against the same
constants, so help text can never drift from actual bindings.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import DataTable, Label

from ui_terminal import sections as reg
from ui_terminal.screens.shell import RAIL_MIN_WIDTH, ShellScreen

__all__ = ["HelpScreen", "GLOBAL_KEYS"]

GLOBAL_KEYS: tuple = (
    ("ctrl+p", "Command palette — filter and run available actions"),
    ("ctrl+q", "Quit the application"),
    ("escape", "Return to the dashboard from any screen"),
    ("tab / shift+tab", "Move focus between controls (visible focus frame)"),
    ("enter / space", "Activate the focused control"),
)

RES_KEYS: tuple = (
    (f"width ≥ {RAIL_MIN_WIDTH} cols", "Navigation rail is shown "
     "(hidden below, so content keeps full width)"),
    ("any size", "Status line and footer stay visible; nothing overlaps"),
)


class HelpScreen(ShellScreen):
    """Keyboard reference; content is generated, never hand-maintained."""

    SECTION_ID = "help"

    def inner_body(self) -> ComposeResult:
        with Vertical(id="help-body"):
            yield Label(
                "All commands are keyboard-first. Use the same table via the "
                "command palette (ctrl+p).",
                id="help-intro",
            )
            screen_table: DataTable
            screen_table = DataTable(id="help-sections", show_cursor=False)
            screen_table.add_columns("Key", "Action")
            yield screen_table
            global_table: DataTable
            global_table = DataTable(id="help-globals", show_cursor=False)
            global_table.add_columns("Key", "Action")
            yield global_table
            yield Label(
                "Accessibility limitations: this Stage 05 interface relies on the "
                "terminal's own screen-reader accessibility; monochrome terminals "
                "degrade colors but status text is always written out in words. "
                "No dedicated screen-reader certification is claimed.",
                id="help-limitations", classes="status-muted",
            )

    def on_mount(self) -> None:
        super().on_mount()
        sections_table = self.query_one("#help-sections", DataTable)
        for section in reg.SECTION_REGISTRY:
            binding = section.binding if section.binding else "—"
            label = section.title
            if section.kind == "future":
                label += f" (placeholder · Stage {section.owner_stage})"
            sections_table.add_row(binding, label)
        global_table = self.query_one("#help-globals", DataTable)
        for key, action in GLOBAL_KEYS:
            global_table.add_row(key, action)

    def status_hint(self) -> str:
        return f"help · {len(GLOBAL_KEYS)} global keys · " \
               f"{len(reg.SECTION_REGISTRY)} destinations"
