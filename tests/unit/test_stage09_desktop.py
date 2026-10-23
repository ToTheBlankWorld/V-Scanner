"""Stage 09 desktop foundation tests — offscreen Qt harness (§13/§15).

Requires the ``desktop`` extra (PySide6); skipped with a documented reason
otherwise (engine-only environments keep the suite green).

Platform: Qt runs on the ``offscreen`` platform unless the environment
already chose one; tests need no display server, no ADB, no device, no
network. Screenshots are deliberately NOT asserted (no repo screenshot
convention).

Covers: startup/lifecycle, navigation (all sections, honesty of
placeholders, dedup, invalid ids, keyboard), design system (token
centralization, textual statuses, accessible names, sizing), settings
persistence through ConfigService, the Qt job bridge GUI-thread rule, and
architecture boundaries (no subprocess in the desktop layer, no
ui_terminal⇄ui_desktop imports, PySide6 confined to ui_desktop).
"""

from __future__ import annotations

import ast
import os
import re
import threading
from pathlib import Path
from typing import Any, List, Optional, cast
from collections.abc import Iterator

import pytest

# Deterministic offscreen rendering unless the caller already chose a
# platform; must happen before PySide6 is imported.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip(
    "PySide6",
    reason="desktop extra not installed (pip install -e '.[desktop]') — "
           "Stage 09 tests are desktop-specific and the engine suite does "
           "not depend on them")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from ui_desktop import APP_NAME, APP_VERSION, __version__ as package_version  # noqa: E402
from ui_desktop import sections as reg  # noqa: E402
from ui_desktop import theme  # noqa: E402
from ui_desktop.jobs_bridge_qt import (  # noqa: E402
    QT_AVAILABLE,
    JobEventSignalHub,
    QtJobEventBridge,
)
from ui_desktop.main_window import MainWindow  # noqa: E402
from vscanner.core.events import JobKind  # noqa: E402
from vscanner.services.config import ConfigService  # noqa: E402
from vscanner.services.jobs import JobManager  # noqa: E402

UI_DESKTOP_ROOT = Path(__file__).resolve().parents[2] / "ui_desktop"
UI_TERMINAL_ROOT = Path(__file__).resolve().parents[2] / "ui_terminal"
ENGINE_ROOT = Path(__file__).resolve().parents[2] / "vscanner"


def _all_label_texts(widget) -> List[str]:
    """Every QLabel text in a widget tree, including hidden parents."""
    found = []
    for label in widget.findChildren(QLabel):
        text = label.text()
        if text:
            found.append(text)
    return found


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def qapp() -> Iterator[QApplication]:
    """One QApplication for the whole desktop test session (offscreen)."""
    app = cast(Optional[QApplication], QApplication.instance())
    if app is None:
        from ui_desktop.app import create_application
        app = create_application([])
    assert app is not None
    yield app
    # Deterministic teardown BEFORE interpreter shutdown: PySide6's static
    # Qt cleanup aborts nondeterministically when leftover top-level
    # QObjects are destroyed during finalization (Stage 10 harness found
    # and fixed this; same hygiene here keeps the shared session clean).
    app.processEvents()
    for widget in list(app.topLevelWidgets()):
        widget.deleteLater()
    app.processEvents()


@pytest.fixture()
def config_service(tmp_path) -> ConfigService:
    return ConfigService(tmp_path / "config.json")


@pytest.fixture()
def shell(qapp, config_service) -> Iterator[MainWindow]:
    window = MainWindow(config_service)
    yield window
    window.close()


# ---------------------------------------------------------------------------
# startup and lifecycle (§13.1)
# ---------------------------------------------------------------------------

class TestStartupAndLifecycle:
    def test_main_window_initializes_with_deterministic_start_section(self, shell):
        assert shell.current_section_id == reg.INITIAL_SECTION_ID == "dashboard"
        assert APP_NAME in shell.windowTitle()
        assert shell.minimumSize().width() >= theme.MIN_WINDOW_WIDTH
        assert shell.minimumSize().height() >= theme.MIN_WINDOW_HEIGHT

    def test_initial_section_renders_readiness(self, shell):
        texts = _all_label_texts(shell.content_widget("dashboard"))
        assert any("Desktop shell ready" in text for text in texts)
        # Honest first-run state: no device discovery, no fabricated state.
        assert any("not configured yet" in text for text in texts)
        assert any("not checked" in text for text in texts)

    def test_missing_configuration_does_not_crash_startup(self, shell, config_service):
        assert not config_service.path.exists()
        assert shell.current_section_id == "dashboard"

    def test_startup_does_not_require_adb_or_a_device(self, qapp, config_service):
        """Producing a shell performs no device work (no backend, no probe)."""
        window = MainWindow(config_service)
        try:
            assert window.current_section_id == "dashboard"
        finally:
            window.close()

    def test_invalid_configuration_shows_truthful_error_state(self, qapp, tmp_path):
        bad = tmp_path / "config.json"
        bad.write_text("{ not json", encoding="utf-8")
        window = MainWindow(ConfigService(bad))
        try:
            texts = _all_label_texts(window.content_widget("dashboard"))
            assert any("Configuration could not be read" in text
                       for text in texts)
        finally:
            window.close()

    def test_second_qapplication_is_refused(self, qapp):
        from ui_desktop.app import create_application
        with pytest.raises(RuntimeError, match="already exists"):
            create_application([])

    def test_version_metadata_stays_in_lockstep(self):
        assert package_version == "3.0.0a0"
        assert APP_VERSION == "3.0.0a0"

    def test_close_is_clean_and_repeatable(self, qapp, config_service):
        window = MainWindow(config_service)
        window.show()
        window.close()
        window.close()  # double close must not crash
        assert window.current_section_id == "dashboard"


# ---------------------------------------------------------------------------
# navigation (§13.2)
# ---------------------------------------------------------------------------

class TestNavigation:
    def test_all_registered_sections_are_reachable(self, shell):
        for section in reg.SECTION_REGISTRY:
            if section.kind == "dialog":
                # Settings is a modal dialog; covered by the settings tests.
                continue
            shell.switch_to(section.section_id)
            assert shell.current_section_id == section.section_id
            assert shell.windowTitle()

    def test_header_title_and_subtitle_follow_the_section(self, shell):
        shell.switch_to("doctor")
        title_label = shell._header.title_label
        subtitle_label = shell._header.subtitle_label
        assert title_label.text() == "Doctor"
        assert subtitle_label.text() == reg.get_section("doctor").subtitle

    def test_future_placeholders_are_honest(self, shell):
        for section in reg.future_sections():
            shell.switch_to(section.section_id)
            texts = _all_label_texts(shell.content_widget(section.section_id))
            joined = " ".join(texts)
            assert f"Planned for {section.owner_stage}" in joined
            assert "not implemented" in joined
            assert "No functionality" in joined
            assert section.title in joined

    def test_invalid_section_id_is_refused_without_state_change(self, shell):
        before_section = shell.current_section_id
        before_status = shell.statusBar().currentMessage()
        with pytest.raises(reg.UnknownSectionError):
            shell.switch_to("not-a-section")
        assert shell.current_section_id == before_section
        assert shell.statusBar().currentMessage() == before_status

    def test_repeated_navigation_creates_no_duplicate_widgets(self, shell):
        shell.switch_to("doctor")
        first_view = shell.content_widget("doctor")
        for _ in range(3):
            shell.switch_to("dashboard")
            shell.switch_to("doctor")
        assert shell.content_widget("doctor") is first_view
        # exactly one stacked widget per opened section (init + doctor)
        assert shell._content_stack.count() == 2
        assert shell._nav.count() == len(reg.SECTION_REGISTRY)

    def test_section_changed_signal_fires_once_per_real_change(self, shell):
        seen: List[str] = []
        shell.section_changed.connect(seen.append)
        shell.switch_to("doctor")
        shell.switch_to("doctor")  # no change → no duplicate emission
        shell.switch_to("dashboard")
        # dashboard is emitted because the initial render happened before
        # the connection was made (first switch away = 'doctor').
        assert seen == ["doctor", "dashboard"]

    def test_keyboard_navigation_moves_sections(self, shell, qapp):
        from PySide6.QtTest import QTest

        shell.show()
        shell.activateWindow()
        shell.raise_()
        shell._nav.setFocus()
        qapp.processEvents()
        assert shell._nav.hasFocus()
        start = shell.current_section_id
        QTest.keyClick(shell._nav, Qt.Key.Key_Down)
        moved = shell.current_section_id
        assert moved != start
        assert moved == reg.SECTION_REGISTRY[shell._nav.currentRow()].section_id

    def test_focus_and_named_actions_in_the_sidebar(self, shell):
        from PySide6.QtWidgets import QPushButton

        assert shell._nav.focusPolicy() != Qt.FocusPolicy.NoFocus
        sidebar = shell._nav.parentWidget()
        side_buttons = sidebar.findChildren(QPushButton)
        assert side_buttons, "sidebar must host the Settings action"
        named = [b.accessibleName() for b in side_buttons]
        assert all(named)

    def test_dialog_sections_keep_the_displayed_section(self, shell, monkeypatch):
        opened = []
        monkeypatch.setattr(shell, "open_settings", lambda: opened.append(True))
        shell.switch_to("settings")
        assert opened == [True]
        assert shell.current_section_id == "dashboard"
        # rail selection stays on the displayed section, not on Settings
        row = shell._nav.currentRow()
        assert shell._nav.item(row).data(Qt.ItemDataRole.UserRole) == "dashboard"


# ---------------------------------------------------------------------------
# design system (§13.3)
# ---------------------------------------------------------------------------

HEX_COLOR = re.compile(r"#[0-9A-Fa-f]{6}\b")


class TestDesignSystem:
    def test_theme_tokens_are_centralized_in_theme_py(self):
        """No hex color literal outside ``ui_desktop/theme.py``."""
        offenders = []
        for path in sorted(UI_DESKTOP_ROOT.rglob("*.py")):
            if path.name == "theme.py":
                continue
            text = path.read_text(encoding="utf-8")
            hits = HEX_COLOR.findall(text)
            if hits:
                offenders.append((path.name, hits))
        assert not offenders

    def test_required_statuses_have_textual_semantics(self):
        labels = set()
        for severity, color in theme.STATUS_COLORS.items():
            label = theme.status_label(severity)
            glyph = theme.status_glyph(severity)
            assert color and label and glyph
            assert severity != color
            labels.add(label)
        assert len(labels) == len(theme.STATUS_COLORS)

    def test_unknown_status_severity_is_refused(self, qapp):
        from ui_desktop.widgets import StatusChip
        chip = StatusChip("ok")
        with pytest.raises(ValueError, match="unknown status severity"):
            chip.set_status("purple")

    def test_important_widgets_have_accessible_names(self, shell):
        assert shell._nav.accessibleName() == "Section navigation"
        header_title = shell._header.title_label.accessibleName()
        assert header_title.startswith("Section title:")
        # every status is also readable as prose (chips carry text labels)
        texts = _all_label_texts(shell.content_widget("dashboard"))
        assert any("OK" in text for text in texts)

    def test_minimum_window_size_is_enforced(self, shell):
        shell.resize(200, 150)  # Qt clamps to the widget's minimum size
        assert shell.width() >= theme.MIN_WINDOW_WIDTH
        assert shell.height() >= theme.MIN_WINDOW_HEIGHT

    def test_status_version_label_present(self, shell):
        texts = [w.text() for w in shell.statusBar().findChildren(QLabel)]
        assert any(f"v{package_version}" in text for text in texts)

    def test_stylesheet_is_generated_from_tokens(self):
        qss = theme.build_app_stylesheet()
        assert f"background: {theme.WINDOW_BG};" in qss
        assert f'QPushButton[variant="primary"]' in qss
        assert theme.FONT_FAMILY[0] == '"'  # a quoted system-first family

    def test_button_variants_are_validated(self, qapp):
        from ui_desktop.widgets import button
        with pytest.raises(ValueError, match="unknown button variant"):
            button("X", variant="neon")


# ---------------------------------------------------------------------------
# settings persistence (AC: settings persistence through ConfigService)
# ---------------------------------------------------------------------------

class TestSettingsPersistence:
    def _open_dialog(self, shell):
        from ui_desktop.settings_dialog import SettingsDialog
        return SettingsDialog(shell._config_service, shell)

    def test_dialog_saves_adb_path_through_config_service(self, shell, config_service):
        dialog = self._open_dialog(shell)
        dialog._adb_edit.setText(str(config_service.path.parent / "adb.exe"))
        dialog._apply()
        assert dialog.result() == int(dialog.DialogCode.Accepted)
        assert config_service.load().adb_path is not None

    def test_dialog_empty_value_clears_saved_path(self, shell, config_service):
        config_service.save(r"C:\tools\platform-tools\adb.exe")
        dialog = self._open_dialog(shell)
        dialog._adb_edit.setText("")
        dialog._apply()
        snapshot = config_service.load()
        assert snapshot.adb_path is None

    def test_save_failure_keeps_the_dialog_open_with_truthful_error(
            self, shell, config_service, monkeypatch):
        dialog = self._open_dialog(shell)
        dialog._adb_edit.setText(r"C:\path\adb.exe")

        from vscanner.core.errors import ConfigError

        def failing_save(path, **kwargs):
            raise ConfigError("disk on fire (simulated)", {"phase": "test"})

        monkeypatch.setattr(dialog._config_service, "save", failing_save)
        dialog._apply()  # must not raise; dialog stays open
        assert dialog.result() != int(dialog.DialogCode.Accepted)
        assert "disk on fire (simulated)" in dialog._error_label.text()

    def test_dialog_prefills_from_existing_config(self, shell, config_service):
        config_service.save(r"C:\tools\adb.exe")
        dialog = self._open_dialog(shell)
        assert dialog.editor_adb_path() == r"C:\tools\adb.exe"

    def test_shell_without_config_service_reports_settings_unavailable(
            self, qapp, config_service):
        window = MainWindow(None)  # no service wired: honest status, no crash
        try:
            window.open_settings()
            assert "Settings unavailable" in window.statusBar().currentMessage()
        finally:
            window.close()


# ---------------------------------------------------------------------------
# Qt job bridge — GUI-thread delivery rule (AC: Qt bridge integration [T])
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not QT_AVAILABLE, reason="PySide6 not installed")
class TestDoctorFrozenHonesty:
    """F-1: the packaged (frozen) Doctor must not report a
    source-environment failure (absent CLI packages, ``pip`` remediation)
    that does not apply to the packaged executable; required packages
    missing from the build must remain an honest actionable error."""

    @staticmethod
    def _frozen_report(jinja2_present: bool = True):
        from vscanner.services.doctor import (
            DependencyReport, PackageStatus,
        )
        return DependencyReport(
            python_version="3.12.10",
            packages=(
                PackageStatus(name="rich", installed=False),
                PackageStatus(name="click", installed=False),
                PackageStatus(name="jinja2", installed=jinja2_present),
            ),
            notes=(),
        )

    # -- source mode semantics preserved ----------------------------------- #

    def test_source_doctor_all_present_is_ok_without_pip_hint(self, qapp):
        from ui_desktop.screens.doctor import build_doctor
        page = build_doctor()
        texts = " ".join(_all_label_texts(page))
        assert "3 of 3 packages present" in texts
        assert "pip install -e" not in texts

    def test_source_doctor_missing_package_keeps_reinstall_hint(
            self, qapp, monkeypatch):
        from ui_desktop.screens.doctor import build_doctor
        from vscanner.services.doctor import DependencyReport, PackageStatus
        import ui_desktop.screens.doctor as screen_mod

        def report():
            return DependencyReport(
                python_version="3.12.10",
                packages=(PackageStatus(name="jinja2", installed=False),),
                notes=(),
            )

        monkeypatch.setattr(screen_mod, "collect_dependency_report", report)
        page = build_doctor()
        texts = " ".join(_all_label_texts(page))
        assert "pip install -e" in texts  # source user CAN reinstall

    # -- frozen (packaged) mode speaks the frozen truth -------------------- #

    def test_frozen_doctor_is_not_a_failure_when_cli_packages_absent(
            self, qapp, monkeypatch):
        from ui_desktop.screens.doctor import build_doctor
        import ui_desktop.screens.doctor as screen_mod

        monkeypatch.setattr(
            screen_mod, "collect_dependency_report",
            lambda: self._frozen_report())
        monkeypatch.setattr(screen_mod, "is_frozen", lambda: True)
        page = build_doctor()
        texts = " ".join(_all_label_texts(page))
        # frozen state made explicit; per-row truth replaces the verdict
        # (rich/click absent by design; jinja2 compiled in -> 1 of 3)
        assert "packaged build - 1 of 3 compiled in" in texts
        assert "not part of this packaged build" in texts
        assert "NOT INSTALLED" not in texts
        assert "pip install -e" not in texts

    def test_frozen_doctor_required_package_missing_is_actionable(
            self, qapp, monkeypatch):
        from ui_desktop.screens.doctor import build_doctor
        import ui_desktop.screens.doctor as screen_mod

        monkeypatch.setattr(
            screen_mod, "collect_dependency_report",
            lambda: self._frozen_report(jinja2_present=False))
        monkeypatch.setattr(screen_mod, "is_frozen", lambda: True)
        page = build_doctor()
        texts = " ".join(_all_label_texts(page))
        assert "Broken build" in texts
        assert "rebuild" in texts

    def test_frozen_dashboard_panel_reports_frozen_truth(
            self, qapp, config_service, monkeypatch):
        import ui_desktop.screens.dashboard as dash_mod
        from ui_desktop.screens.dashboard import build_dashboard

        monkeypatch.setattr(
            dash_mod, "collect_dependency_report",
            lambda: self._frozen_report())
        monkeypatch.setattr(dash_mod, "is_frozen", lambda: True)
        page = build_dashboard(config_service, adb_probe=lambda p: True)
        texts = " ".join(_all_label_texts(page))
        assert "packaged build - 1 of 3 compiled in" in texts
        assert "reinstall the engine environment" not in texts
        assert "not part of this packaged build" in texts

    def test_frozen_dashboard_required_missing_stays_honest(
            self, qapp, config_service, monkeypatch):
        import ui_desktop.screens.dashboard as dash_mod
        from ui_desktop.screens.dashboard import build_dashboard

        monkeypatch.setattr(
            dash_mod, "collect_dependency_report",
            lambda: self._frozen_report(jinja2_present=False))
        monkeypatch.setattr(dash_mod, "is_frozen", lambda: True)
        page = build_dashboard(config_service, adb_probe=lambda p: True)
        texts = " ".join(_all_label_texts(page))
        assert "Broken build" in texts


class TestQtJobBridge:
    def test_bridge_delivers_events_on_the_gui_thread(self, qapp):
        bridge = QtJobEventBridge()
        manager = JobManager(max_workers=2)
        delivered: List[Any] = []
        slot_thread_ids: List[int] = []
        bridge.hub.any_event.connect(
            lambda event: (delivered.append(event),
                           slot_thread_ids.append(threading.get_ident())))
        try:
            bridge.attach(manager)
            main_tid = threading.get_ident()
            assert bridge.attached

            def plan(ctx):
                ctx.progress(1, 2, unit="steps", context="half")
                ctx.progress(2, 2, unit="steps", context="done")
                return "ok"

            handle = manager.submit(JobKind.OTHER, device_serial=None,
                                    params_summary={"kind": "bridge-smoke"},
                                    plan=plan)
            handle.wait(10)
            # started + 2×progress + terminal = 4 emissions → 4 slot calls
            deadline = 0
            while len(delivered) < 4 and deadline < 500:
                qapp.processEvents()
                deadline += 1
            assert len(delivered) == 4, (
                f"all job events must reach the GUI-thread slot ({len(delivered)}/4)")

            # Every slot ran on the GUI thread (queued connections).
            assert all(tid == main_tid for tid in slot_thread_ids)
            # ...while the bridge traced deliveries from worker threads.
            producer_tids = {tid for _, tid in bridge.trace()}
            assert main_tid not in producer_tids

            categories = [category for category, _ in bridge.trace()]
            assert categories[0] == "started"
            assert categories[-1] == "terminal"
            assert categories.count("progress") == 2
        finally:
            bridge.detach()
            manager.shutdown()

    def test_detach_stops_delivery(self, qapp):
        bridge = QtJobEventBridge()
        manager = JobManager(max_workers=2)
        delivered: List[Any] = []
        bridge.hub.any_event.connect(delivered.append)
        try:
            bridge.attach(manager)
            assert bridge.attached
            bridge.detach()
            assert not bridge.attached
            handle = manager.submit(JobKind.OTHER, device_serial=None,
                                    params_summary={"kind": "post-detach"},
                                    plan=lambda ctx: "ok")
            handle.wait(10)
            qapp.processEvents()
            assert delivered == [], "a detached bridge must stay silent"
        finally:
            manager.shutdown()

    def test_unknown_category_is_rejected(self, qapp):
        with pytest.raises(ValueError, match="unknown job event category"):
            JobEventSignalHub().deliver("vibes", None)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# architecture boundaries (§13.4)
# ---------------------------------------------------------------------------

def _import_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    return names


class TestArchitecture:
    FORBIDDEN_PROCESS_IMPORTS = {"subprocess", "adb"}

    def test_desktop_layer_never_launches_processes(self):
        offenders = []
        for path in sorted(UI_DESKTOP_ROOT.rglob("*.py")):
            if _import_names(path) & self.FORBIDDEN_PROCESS_IMPORTS:
                offenders.append(path.name)
            source = path.read_text(encoding="utf-8")
            assert "os.system" not in source, f"{path.name} calls os.system"
        assert not offenders

    def test_desktop_never_imports_the_tui(self):
        for path in sorted(UI_DESKTOP_ROOT.rglob("*.py")):
            names = _import_names(path)
            assert "ui_terminal" not in names and "textual" not in names, \
                f"{path.name} imports the TUI stack"

    def test_tui_never_imports_the_desktop(self):
        for path in sorted(UI_TERMINAL_ROOT.rglob("*.py")):
            names = _import_names(path)
            assert "ui_desktop" not in names, \
                f"{path.name} imports the desktop layer"

    def test_engine_never_imports_ui_desktop_or_qt(self):
        for path in sorted(ENGINE_ROOT.rglob("*.py")):
            names = _import_names(path)
            assert "PySide6" not in names and "ui_desktop" not in names, \
                f"{path.relative_to(ENGINE_ROOT)} leaks UI into the engine"

    def test_qt_imports_live_only_in_ui_desktop(self):
        offenders = []
        for root in (UI_TERMINAL_ROOT, ENGINE_ROOT):
            for path in sorted(root.rglob("*.py")):
                if "PySide6" in _import_names(path):
                    offenders.append(str(path.relative_to(root.parents[1])))
        assert not offenders
