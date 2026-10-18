"""Navigation shell pieces shared by every screen (Stage 05).

``ShellScreen`` gives every screen the same persistent chrome:

* a compact one-row brand bar (name · tagline · current section),
* a left navigation rail built from the section registry (hidden on narrow
  terminals by :meth:`ShellScreen.on_resize` — responsive, not broken),
* a body region each subclass fills via :meth:`ShellScreen.inner_body`,
* an honest one-row status line (:meth:`ShellScreen.status_hint`), and
* Textual's standard ``Footer`` showing real bindings.

Raw colors never appear here; everything references the theme variables
defined in ``ui_terminal.theme`` (single source of design truth).
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.events import Resize
from textual.screen import Screen
from textual.widgets import Button, Footer, Label

from ui_terminal import sections as reg
from ui_terminal.theme import APP_TITLE, BRAND_TAGLINE

__all__ = ["ShellScreen", "BrandBar", "NavRail"]

RAIL_MIN_WIDTH = 72
"""Below this many columns the rail and tagline collapse (responsive)."""

TAGLINE_MIN_WIDTH = 96


class BrandBar(Horizontal):
    """Compact one-row brand area: name, tagline, current section."""

    def __init__(self, current_title: str) -> None:
        super().__init__(id="brand-bar")
        self._current_title = current_title

    def compose(self) -> ComposeResult:
        yield Label(APP_TITLE, id="brand-name")
        yield Label(BRAND_TAGLINE, id="brand-tagline")
        yield Label(f"· {self._current_title}", id="brand-section")


class NavRail(Vertical):
    """Left navigation rail built from the section registry."""

    def __init__(self, current: str) -> None:
        super().__init__(id="nav-rail")
        self._current = current

    def compose(self) -> ComposeResult:
        future_shown = False
        for section in reg.SECTION_REGISTRY:
            if section.kind == "future" and not future_shown:
                yield Label("later stages", classes="nav-section-caption")
                future_shown = True
            key_hint = f" · {section.binding}" if section.binding else ""
            nav_label = f"{section.title}{key_hint}"
            row = Button(
                nav_label,
                classes="nav-item nav-current"
                if section.section_id == self._current
                else "nav-item",
                id=f"nav-{section.section_id}",
                flat=True,
                compact=True,
            )
            yield row


class ShellScreen(Screen):
    """Base class wiring the persistent chrome around :meth:`inner_body`."""

    SECTION_ID: str = ""
    """Registry key of this screen; drives rail highlight + brand section."""

    def inner_body(self) -> ComposeResult:
        raise NotImplementedError(
            f"{type(self).__name__} must implement inner_body()"
        )

    def status_hint(self) -> str:
        """One-row honest status line content (plain str)."""
        return ""

    def compose(self) -> ComposeResult:
        yield BrandBar(reg.get_section(self.SECTION_ID).title)
        with Horizontal(id="shell-main"):
            yield NavRail(self.SECTION_ID)
            with Vertical(id="vs-body"):
                yield from self.inner_body()
        yield Label("", id="status-line")
        yield Footer()

    # -- status line ---------------------------------------------------- #

    def refresh_status(self) -> None:
        self.query_one("#status-line", Label).update(self.status_hint())

    def on_screen_resume(self) -> None:
        """Status line reflects the current honest state on every resume."""
        self.refresh_status()

    # -- responsive behavior -------------------------------------------- #

    def on_resize(self, event: Resize) -> None:
        self.apply_responsive_rules(event.size.width)

    def on_mount(self) -> None:
        self.apply_responsive_rules(self.size.width)
        self.refresh_status()

    def apply_responsive_rules(self, width: int) -> None:
        """Collapse secondary chrome instead of letting content break."""
        try:
            rail = self.query_one("#nav-rail")
            tagline = self.query_one("#brand-tagline")
        except Exception:
            return  # compose not finished yet; on_mount retries later
        rail.display = width >= RAIL_MIN_WIDTH
        tagline.display = width >= TAGLINE_MIN_WIDTH
