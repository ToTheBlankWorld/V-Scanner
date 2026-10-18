"""TUI application shell tests (Stage 05).

Deterministic headless tests via Textual's ``run_test`` harness: startup,
navigation contract (no duplicate screens — ``switch_screen`` from a
per-section cache), honest placeholder screens, focus, responsive resize,
command palette, and exit behavior. No device, network, subprocess, or
provisioning operation happens in any test here.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from textual.widgets import Button, Label
from textual.widgets import Footer

from ui_terminal import sections as reg
from ui_terminal.app import VScannerApp, VScannerCommands
from vscanner.services.config import ConfigService


def _visible_text(node) -> str:
    """Concatenated plain text of a node's Label widgets (no markup)."""
    return "\n".join(str(w.render().plain) for w in node.query(Label))


@pytest.fixture
def config_service(tmp_path: Path) -> ConfigService:
    """Isolated config: the developer's real config file is never touched."""
    return ConfigService(tmp_path / "config.json")


@pytest.fixture
def make_app(config_service: ConfigService):
    return lambda: VScannerApp(config_service=config_service)


class TestStartup:
    async def test_app_initializes_with_registered_theme(self, make_app) -> None:
        app = make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.current_theme.name == "vscanner-dark"
            assert app.NAME == "V-Scanner"
            assert app.title == "V-Scanner 3.0"

    async def test_initial_screen_is_dashboard(self, make_app) -> None:
        app = make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            assert type(app.screen).__name__ == "DashboardScreen"
            # internal default + dashboard: the stack never grows beyond two
            assert len(app.screen_stack) == 2

    async def test_footer_and_status_line_are_present(self, make_app) -> None:
        app = make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.screen.query(Footer)
            assert app.screen.query("#status-line")
            assert "V-Scanner" in _visible_text(app.screen.query_one("#brand-bar"))

    async def test_dashboard_is_honest_on_first_run(self, make_app) -> None:
        app = make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            text = _visible_text(app.screen)
            assert "no path saved yet" in text
            assert "probing never runs automatically" in text
            # The dashboard never shows a fake device count or result.
            assert "device workspace arrives in stage 06" not in text.lower()


class TestNavigation:
    async def test_binding_keys_reach_registered_screens(self, make_app) -> None:
        app = make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("e")
            await pilot.pause()
            assert type(app.screen).__name__ == "DoctorScreen"
            await pilot.press("s")
            await pilot.pause()
            assert type(app.screen).__name__ == "SettingsScreen"
            await pilot.press("f1")
            await pilot.pause()
            assert type(app.screen).__name__ == "HelpScreen"
            await pilot.press("d")
            await pilot.pause()
            assert type(app.screen).__name__ == "DashboardScreen"

    async def test_escape_returns_to_dashboard(self, make_app) -> None:
        app = make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("e")
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
            assert type(app.screen).__name__ == "DashboardScreen"
            assert len(app.screen_stack) == 2

    async def test_repeated_navigation_caches_one_instance_per_section(
        self, make_app
    ) -> None:
        app = make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            for _ in range(3):
                await pilot.press("e")
                await pilot.pause()
                await pilot.press("d")
                await pilot.pause()
            assert type(app.screen).__name__ == "DashboardScreen"
            assert len(app.screen_stack) == 2
            # the doctor screen is cached once: the identity stays stable
            doctor_id = id(app._screen_cache["doctor"])
            await pilot.press("e")
            await pilot.pause()
            assert id(app.screen) == doctor_id

    async def test_unknown_section_is_feedback_not_crash(self, make_app) -> None:
        app = make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            calls: list = []
            app.notify = lambda *a, **k: calls.append(a[0] if a else "")  # type: ignore[method-assign]
            app.switch_to_section("definitely-not-a-section")
            await pilot.pause()
            assert calls, "unknown navigation must give explicit feedback"
            assert type(app.screen).__name__ == "DashboardScreen"

    async def test_navigation_to_every_future_section_is_honest(
        self, make_app
    ) -> None:
        app = make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            for section in reg.future_sections():
                app.switch_to_section(section.section_id)
                await pilot.pause()
                assert type(app.screen).__name__ == "PlaceholderFutureScreen"
                text = _visible_text(app.screen)
                assert "not implemented yet" in text
                assert f"Stage {section.owner_stage}" in text
                await pilot.press("escape")
                await pilot.pause()
                assert type(app.screen).__name__ == "DashboardScreen"


class TestHonesty:
    async def test_future_sections_are_all_delivered_now(self, make_app) -> None:
        """Stage 08: the roadmap's TUI parity stages are delivered — the
        registry has no placeholder destinations left, and the monitoring
        screen (a former Stage 08 placeholder) is a real live screen with
        honest wording and no fake device state."""
        from ui_terminal import sections as reg

        app = make_app()
        async with app.run_test() as pilot:
            assert reg.future_sections() == (), \
                "Stage 08 delivered every planned TUI section"
            await pilot.pause()
            app.switch_to_section("monitoring")
            await pilot.pause()
            body = app.screen.query_one("#vs-body")
            buttons = [b.id for b in body.query(Button) if b.id]
            offending = [
                b for b in buttons
                if any(w in b for w in ("scan", "connect", "run"))
            ]
            assert offending == [], "sections must not pretend to act"
            text = _visible_text(app.screen)
            assert "no snapshot yet" in text or "target" in text

    async def test_doctor_screen_is_report_only(self, make_app) -> None:
        app = make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("e")
            await pilot.pause()
            text = _visible_text(app.screen)
            assert "report-only" in text
            # the doctor produced a real summary the dashboard may quote
            assert app.last_doctor_summary is not None
            assert "report-ready" in app.last_doctor_summary


class TestFocusAndLayout:
    async def test_tab_moves_focus_between_controls(self, make_app) -> None:
        app = make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            first = app.screen.focused
            await pilot.press("tab")
            await pilot.pause()
            second = app.screen.focused
            assert first is not None and second is not None
            assert first is not second

    async def test_rail_collapses_on_narrow_terminal(self, make_app) -> None:
        app = make_app()
        async with app.run_test(size=(110, 30)) as pilot:
            await pilot.pause()
            rail = app.screen.query_one("#nav-rail")
            assert rail.display
            await pilot.resize_terminal(60, 20)
            await pilot.pause()
            assert rail.display is False
            # secondary chrome collapses; primary chrome remains reachable
            assert app.screen.query("#status-line")
            assert app.screen.query(Footer)
            await pilot.resize_terminal(110, 30)
            await pilot.pause()
            assert rail.display is True

    async def test_tagline_hidden_on_medium_widths(self, make_app) -> None:
        app = make_app()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            tagline = app.screen.query_one("#brand-tagline")
            assert tagline.display is False
            assert app.screen.query_one("#brand-name").display is True


class TestPaletteAndExit:
    async def test_command_palette_source_lists_registry_commands(
        self, make_app
    ) -> None:
        app = make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            provider = VScannerCommands(app.screen)
            hits = [hit async for hit in provider.search("sett")]
            assert any("goto settings" in (hit.text or "") for hit in hits)
            empty = [hit async for hit in provider.search("")]
            assert len(empty) >= len(reg.SECTION_REGISTRY)

    async def test_palette_execution_navigates(self, make_app) -> None:
        app = make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("ctrl+p")
            await pilot.pause()
            await pilot.press("d", "o", "c")
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            assert type(app.screen).__name__ == "DoctorScreen"

    async def test_ctrl_q_quits_cleanly(self, make_app) -> None:
        app = make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("ctrl+q")
        assert app.return_code == 0


class TestRegistryContract:
    def test_live_section_bindings_are_unique(self) -> None:
        bindings = [s.binding for s in reg.live_sections()]
        assert len(set(bindings)) == len(bindings)

    def test_every_future_section_has_an_owner_stage(self) -> None:
        assert all(
            s.owner_stage.isdigit() and s.factory is not None
            for s in reg.future_sections()
        )
        ids = {s.section_id for s in reg.SECTION_REGISTRY}
        assert {"dashboard", "doctor", "settings", "help", "devices"} <= ids
