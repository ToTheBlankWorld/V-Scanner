"""Settings + doctor screens over the engine services (Stage 05).

The screens own zero persistence logic; these tests prove the round-trip
goes through ``ConfigService`` only, that an honest failure state is shown
for unreadable config files, and that the doctor screen renders the engine
report without any side effect. The developer's real profile directories
are never touched (each test injects ``tmp_path``-based services).
"""

from __future__ import annotations

import json
from pathlib import Path

from textual.widgets import Button, Input, Label

from ui_terminal.screens.doctor import DoctorScreen
from ui_terminal.screens.settings import SettingsScreen
from vscanner.services.config import ConfigSnapshot, ConfigService
from vscanner.services.doctor import collect_dependency_report


def _visible_text(node) -> str:
    """Labels plus DataTable cell text (data lives in tables, e.g. doctor)."""
    parts = [str(w.render().plain) for w in node.query(Label)]
    from textual.widgets import DataTable

    for table in node.query(DataTable):
        for row_key in table.rows:
            cells = table.get_row(row_key)
            parts.append("\t".join(str(cell) for cell in cells))
    return "\n".join(parts)


def _settings_of(app_or_screen) -> SettingsScreen:
    """Type-narrow a runtime screen to its expected class."""
    screen = getattr(app_or_screen, "screen", app_or_screen)
    assert isinstance(screen, SettingsScreen)
    from typing import cast

    return cast(SettingsScreen, screen)


class TestSettingsScreen:
    async def test_config_round_trip_through_the_engine(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.json"
        app_config = ConfigService(config_file)
        from ui_terminal.app import VScannerApp

        app = VScannerApp(config_service=app_config)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.switch_to_section("settings")
            await pilot.pause()
            screen = _settings_of(app)
            assert "no bridge path saved (first run)" in screen.status_hint()

            path_input = screen.query_one("#adb-path-input", Input)
            path_input.value = str(tmp_path / "adb.exe")
            screen.query_one("#save-config", Button).press()
            await pilot.pause()

            written = json.loads(config_file.read_text(encoding="utf-8"))
            assert written == {
                "schema_version": 1,
                "adb_path": str(tmp_path / "adb.exe"),
            }
            assert "bridge path saved" in screen.status_hint()

    async def test_saved_state_survives_navigation_round_trip(
        self, tmp_path: Path
    ) -> None:
        config_file = tmp_path / "config.json"
        from ui_terminal.app import VScannerApp

        app = VScannerApp(config_service=ConfigService(config_file))
        async with app.run_test() as pilot:
            await pilot.pause()
            app.switch_to_section("settings")
            await pilot.pause()
            screen = _settings_of(app)
            screen.query_one("#adb-path-input", Input).value = "X:/tools/adb.exe"
            screen.query_one("#save-config", Button).press()
            await pilot.pause()
            app.switch_to_section("dashboard")
            await pilot.pause()
            app.switch_to_section("settings")
            await pilot.pause()
            again = _settings_of(app)
            assert again.query_one("#adb-path-input", Input).value == "X:/tools/adb.exe"
            assert "bridge path saved" in again.status_hint()

    async def test_unreadable_config_shows_honest_error(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.json"
        config_file.write_bytes(b"{ this is: not json", )
        from ui_terminal.app import VScannerApp

        app = VScannerApp(config_service=ConfigService(config_file))
        async with app.run_test() as pilot:
            await pilot.pause()
            app.switch_to_section("settings")
            await pilot.pause()
            text = _visible_text(app.screen)
            assert "existing config is unreadable" in text

    async def test_legacy_import_reported_honestly_in_repo_local_mode(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        from ui_terminal.app import VScannerApp

        monkeypatch.setenv("VSCANNER_LOCAL", "1")
        attempts: list = []

        def fake_import(self: ConfigService):
            attempts.append(1)
            return ConfigSnapshot(adb_path="C:/legacy/adb.exe")

        monkeypatch.setattr(ConfigService, "import_repo_legacy_config", fake_import)
        app = VScannerApp(config_service=ConfigService(tmp_path / "config.json"))
        async with app.run_test() as pilot:
            await pilot.pause()
            app.switch_to_section("settings")
            await pilot.pause()
            screen = _settings_of(app)
            assert attempts, "first run in repo-local mode attempts the import"
            text = _visible_text(screen)
            assert "imported legacy config" in text
            assert screen.query_one("#adb-path-input", Input).value == "C:/legacy/adb.exe"

    async def test_legacy_import_reports_absence_honestly(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        from ui_terminal.app import VScannerApp

        monkeypatch.setenv("VSCANNER_LOCAL", "1")
        attempts: list = []

        def fake_import(self: ConfigService):
            attempts.append(1)
            return None

        monkeypatch.setattr(ConfigService, "import_repo_legacy_config", fake_import)
        app = VScannerApp(config_service=ConfigService(tmp_path / "config.json"))
        async with app.run_test() as pilot:
            await pilot.pause()
            app.switch_to_section("settings")
            await pilot.pause()
            screen = _settings_of(app)
            assert attempts
            text = _visible_text(screen)
            assert "no legacy config found" in text

    async def test_legacy_import_never_runs_outside_repo_local_mode(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        from ui_terminal.app import VScannerApp

        monkeypatch.delenv("VSCANNER_LOCAL", raising=False)
        attempts: list = []

        def spy_import(self: ConfigService):  # pragma: no cover - spy
            attempts.append(1)
            return None

        monkeypatch.setattr(ConfigService, "import_repo_legacy_config", spy_import)
        app = VScannerApp(config_service=ConfigService(tmp_path / "config.json"))
        async with app.run_test() as pilot:
            await pilot.pause()
            app.switch_to_section("settings")
            await pilot.pause()
            assert attempts == [], "user-profile mode must never auto-import"

    async def test_validate_button_only_after_explicit_user_action(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """The adb probe is a subprocess: it must be reachable ONLY through
        the explicit button, never at startup (mission §9)."""
        calls: list = []
        import ui_terminal.screens.settings as settings_mod

        def fake_check(path: str) -> bool:
            calls.append(path)
            return True

        monkeypatch.setattr(settings_mod, "check_adb_valid", fake_check)
        from ui_terminal.app import VScannerApp

        app = VScannerApp(config_service=ConfigService(tmp_path / "config.json"))
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("s")
            await pilot.pause()
            assert calls == [], "startup must not probe executables"
            screen: SettingsScreen = app.screen  # type: ignore[assignment]
            screen.query_one("#adb-path-input", Input).value = "X:/tools/adb.exe"
            await pilot.press("tab")
            screen._validate()
            await pilot.pause()
            await pilot.pause()
            assert calls == ["X:/tools/adb.exe"]


class TestDoctorScreen:
    async def test_doctor_renders_engine_report_without_side_effects(
        self, tmp_path: Path
    ) -> None:
        from ui_terminal.app import VScannerApp

        app = VScannerApp(config_service=ConfigService(tmp_path / "config.json"))
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("e")
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, DoctorScreen)
            text = _visible_text(screen)
            # Report data comes from SC-11's engine report:
            report = collect_dependency_report(tools_service=None)
            assert f"Python: {report.python_version}" in text
            for package in report.packages:
                assert f"package {package.name}" in text
            assert "report-only" in text

    async def test_doctor_honest_when_report_is_impossible(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        import ui_terminal.screens.doctor as doctor_mod

        def explode(tools_service=None, extra_notes=()):
            raise RuntimeError("boom")

        monkeypatch.setattr(
            doctor_mod, "collect_dependency_report", explode
        )
        from ui_terminal.app import VScannerApp

        app = VScannerApp(config_service=ConfigService(tmp_path / "config.json"))
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("e")
            await pilot.pause()
            text = _visible_text(app.screen)
            assert "environment report failed: RuntimeError" in text
            assert "unavailable" in text  # honest absence, no crash
