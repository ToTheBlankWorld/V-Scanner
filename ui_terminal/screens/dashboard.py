"""Dashboard — the V-Scanner TUI home screen (Stage 05).

Shows the honest initial state: it never launches device enumeration,
provisioning, or scans merely to present content (mission §6). The cards
reflect *real* config/doctor state only:

* Settings card — whether a device bridge path is actually saved.
* Doctor card — the report-only environment check, on demand.
* Future-work card — clearly labelled later-stage destinations.

Everything is driven from the shared engine (``vscanner``): the config
snapshot comes from :class:`vscanner.services.config.ConfigService`, never
from duplicated logic here.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical, VerticalGroup
from textual.widgets import Label

from ui_terminal.screens.shell import ShellScreen


_CARD_TITLES = (
    "1 · Configure the device bridge",
    "2 · Check the environment",
    "3 · Work with a device",
)


class DashboardCard(Vertical):
    """One honest panel of the start page."""

    def __init__(self, index: int, title: str) -> None:
        super().__init__(classes="card", id=f"card-{index}")
        self._title = title

    def compose(self) -> ComposeResult:
        yield Label(self._title, classes="card-title")
        yield Label("", classes="card-detail")
        yield Label("", classes="card-hint")


class DashboardScreen(ShellScreen):
    """Home: honest start state + on-ramp cards. No network, no device."""

    SECTION_ID = "dashboard"

    def inner_body(self) -> ComposeResult:
        with VerticalGroup(id="get_started"):
            for index, title in enumerate(_CARD_TITLES):
                yield DashboardCard(index, title)
        with VerticalGroup(id="brand-welcome"):
            yield Label(
                "V-Scanner audits Android devices locally. Work is evidence-based:\n"
                "every finding is tied to a probe; unavailable information is\n"
                "reported as unknown — never fabricated.",
                id="welcome-note",
            )

    # -- card content ---------------------------------------------------- #

    def _card_texts(self):
        """Compute the three honest card detail lines from real state."""
        snapshot = self.app.config_service.load()  # may raise ConfigError
        if snapshot.has_path:
            bridge = f"saved: {snapshot.adb_path}"
            bridge_status = "status-ok"
        else:
            bridge = "no path saved yet (first run) — nothing has been probed"
            bridge_status = "status-muted"

        last_doctor = getattr(self.app, "last_doctor_summary", None)
        doctor = last_doctor or "not run yet — open the doctor to check the environment (press e)"

        devices = (
            "not checked — device probing only runs when you open the "
            "device workspace (press w)"
        )
        return [
            (bridge, bridge_status, "press s · open settings"),
            (doctor, "status-muted", "press e · open doctor"),
            (devices, "status-muted", "press w · open device workspace"),
        ]

    def refresh_status(self) -> None:
        """Update cards + status line from the live config snapshot."""
        try:
            cards = self._card_texts()
        except Exception:
            # Config file unreadable: show honest failure, keep app usable.
            for card in self.query(DashboardCard):
                card.query_one(".card-detail", Label).update(
                    "config file could not be read — check Doctor"
                )
                card.query_one(".card-hint", Label).update("")
            self.query_one("#status-line", Label).update(
                "status · config file unreadable — open Settings or Doctor"
            )
            return
        for card, (detail, klass, hint) in zip(self.query(DashboardCard), cards):
            detail_label = card.query_one(".card-detail", Label)
            detail_label.update(detail)
            detail_label.set_classes(f"card-detail {klass}")
            card.query_one(".card-hint", Label).update(hint)
        self.query_one("#status-line", Label).update(self.status_hint())

    def status_hint(self) -> str:
        return "ready · device probing never runs automatically"
