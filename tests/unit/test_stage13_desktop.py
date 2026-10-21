"""Stage 13 desktop polish — motion, accessibility, theme, dialog Escape.

Covers the small, coherent improvement set delivered for Stage 13:

* theme: ``feedback_qss`` (single color source for inline feedback),
  extended QSS (combos, multi-line text views, default buttons,
  horizontal scrollbars), palette placeholder color, unchanged window
  minimums.
* :mod:`ui_desktop.motion`: reduced-motion detection (environment override
  wins over the OS preference), one-shot ``fade_in`` (effect removed on
  completion, restart-safe, no-op under reduced motion).
* Shell: navigation fade only on user navigation (never the initial
  switch, never a same-section re-selection, never under reduced motion);
  dashboard rebuild intact; initial keyboard focus reaches the nav rail;
  tables keep StrongFocus.
* Accessibility: every ``widgets.button`` exposes an accessible name;
  dynamic state banners on dashboard/demo/mirroring/monitoring/reports
  and the settings validation row are named; destructive-dialog buttons
  carry explicit, honest accessible names.
* Dialog Escape semantics on the REAL dialogs: Escape rejects and must
  never accept, and Settings Escape never saves.

No screenshot tests, no sleeps: driven by ``pump_until`` predicates only.
"""

from __future__ import annotations

from typing import Iterator, List, Optional, cast

import pytest

from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QGraphicsOpacityEffect,
    QWidget,
)

from test_stage10_desktop import pump_until  # noqa: E402
from test_stage12_desktop import (  # noqa: E402
    BackendFactory12,
    Stage12Transport,
)

import ui_desktop.backend as backend_module  # noqa: E402  (history seam)
from ui_desktop import motion, theme  # noqa: E402
from ui_desktop.app import create_application  # noqa: E402
from ui_desktop.jobs_bridge_qt import QtJobEventBridge  # noqa: E402
from ui_desktop.main_window import MainWindow  # noqa: E402
from ui_desktop.screens.demo import DemoPage  # noqa: E402
from ui_desktop.screens.devices import (  # noqa: E402
    AdminConfirmDialog,
    DeviceWorkspacePage,
)
from ui_desktop.screens.forensics import (  # noqa: E402
    ACK_PHRASE,
    CleartextConfirmDialog,
)
from ui_desktop.screens.mirroring import MirroringPage  # noqa: E402
from ui_desktop.screens.monitoring import MonitoringPage  # noqa: E402
from ui_desktop.screens.scan import ScanWorkspacePage  # noqa: E402
from ui_desktop.settings_dialog import SettingsDialog  # noqa: E402
from ui_desktop.widgets import button  # noqa: E402
from vscanner.services.config import ConfigService  # noqa: E402


# ===========================================================================
# fixtures — same deterministic wiring as Stage 12
# ===========================================================================


@pytest.fixture(scope="session")
def qapp() -> Iterator[QApplication]:
    app = cast(Optional[QApplication], QApplication.instance())
    if app is None:
        app = create_application([])
    assert app is not None
    yield app  # type: ignore[misc]
    # Deterministic teardown, same contract as Stage 12.
    app.processEvents()
    for widget in list(app.topLevelWidgets()):
        widget.deleteLater()
    app.processEvents()


@pytest.fixture()
def config_service(tmp_path) -> ConfigService:
    service = ConfigService(tmp_path / "config.json")
    service.save(r"C:\tools\fake-adb.exe")
    return service


@pytest.fixture()
def backend_factory(qapp, monkeypatch: pytest.MonkeyPatch):
    factory = BackendFactory12(monkeypatch)
    yield factory
    factory.teardown()


def _bridge(backend) -> QtJobEventBridge:
    bridge = QtJobEventBridge()
    bridge.attach(backend.manager())
    return bridge


def _shutdown(page) -> None:
    """Explicit owner-close for every page (Stage-11 Windows learning)."""
    shutdown = getattr(page, "shutdown", None)
    if callable(shutdown):
        try:
            shutdown()
        except RuntimeError:
            pass  # Qt object already gone


# ===========================================================================
# theme
# ===========================================================================


def _relative_luminance(hex_color: str) -> float:
    """WCAG 2.x relative luminance of ``#RRGGBB``."""
    red, green, blue = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))

    def channel(value: int) -> float:
        normalized = value / 255.0
        if normalized <= 0.04045:
            return normalized / 12.92
        return ((normalized + 0.055) / 1.055) ** 2.4

    return (0.2126 * channel(red) + 0.7152 * channel(green)
            + 0.0722 * channel(blue))


def _contrast_ratio(first: str, second: str) -> float:
    lighter = max(_relative_luminance(first), _relative_luminance(second))
    darker = min(_relative_luminance(first), _relative_luminance(second))
    return (lighter + 0.05) / (darker + 0.05)


class TestStage13Contrast:
    """Automatable WCAG-AA text-contrast matrix over the theme tokens.

    Stage 13 contrast audit outcome: TEXT_MUTED and the primary-button
    fill were the two AA failures and were retuned WITHOUT changing the
    accent hue or the dark identity; these assertions lock the fix.
    """

    AA_TEXT = 4.5

    def test_primary_text_passes_everywhere(self) -> None:
        for surface in (theme.WINDOW_BG, theme.SIDEBAR_BG,
                        theme.SURFACE_BG, theme.ELEVATED_BG,
                        theme.SELECTION_BG):
            assert _contrast_ratio(theme.TEXT_PRIMARY, surface) >= self.AA_TEXT

    def test_secondary_text_passes_on_surfaces(self) -> None:
        for surface in (theme.SURFACE_BG, theme.ELEVATED_BG,
                        theme.WINDOW_BG):
            assert _contrast_ratio(
                theme.TEXT_SECONDARY, surface) >= self.AA_TEXT

    def test_muted_text_passes_after_retune(self) -> None:
        for surface in (theme.SURFACE_BG, theme.ELEVATED_BG,
                        theme.WINDOW_BG):
            assert _contrast_ratio(theme.TEXT_MUTED, surface) >= \
                self.AA_TEXT

    def test_muted_stays_below_secondary(self) -> None:
        # readability hierarchy: hints remain behind secondary copy
        on_surface_secondary = _contrast_ratio(
            theme.TEXT_SECONDARY, theme.SURFACE_BG)
        on_surface_muted = _contrast_ratio(theme.TEXT_MUTED, theme.SURFACE_BG)
        assert on_surface_muted < on_surface_secondary

    def test_white_label_on_primary_button_states(self) -> None:
        for fill in (theme.ACCENT_CONTROL, theme.ACCENT_CONTROL_HOVER,
                     theme.ACCENT_CONTROL_PRESSED):
            assert _contrast_ratio(
                theme.TEXT_ON_ACCENT, fill) >= self.AA_TEXT

    def test_status_colors_read_as_text_on_surfaces(self) -> None:
        for color in (theme.SUCCESS_COLOR, theme.WARNING_COLOR,
                      theme.ERROR_COLOR, theme.INFO_COLOR):
            assert _contrast_ratio(color, theme.SURFACE_BG) >= self.AA_TEXT

    def test_brand_mark_and_intensity_positions(self) -> None:
        # decorative accent roles stay independently AA-checked
        assert _contrast_ratio(theme.ACCENT, theme.SIDEBAR_BG) >= self.AA_TEXT
        assert _contrast_ratio(theme.ACCENT, theme.SURFACE_BG) >= self.AA_TEXT


class TestStage13Theme:
    def test_feedback_qss_kinds(self) -> None:
        expected = {
            "success": theme.SUCCESS_COLOR,
            "warning": theme.WARNING_COLOR,
            "error": theme.ERROR_COLOR,
            "info": theme.INFO_COLOR,
        }
        for kind, color in expected.items():
            assert theme.feedback_qss(kind) == \
                f"color: {color}; background: transparent;"

    def test_feedback_qss_unknown_kind_raises(self) -> None:
        with pytest.raises(ValueError):
            theme.feedback_qss("banana")
        assert theme.FEEDBACK_KINDS == ("success", "warning", "error", "info")

    def test_stylesheet_covers_stage13_control_classes(self) -> None:
        qss = theme.build_app_stylesheet()
        # combo boxes (findings/report filters) — the box is styled while
        # native arrow / checkbox indicator rendering is kept intact
        assert "QComboBox {" in qss
        assert (f"QComboBox:focus {{ border: 1px solid "
                f"{theme.FOCUS_RING}; }}") in qss
        assert "QComboBox QAbstractItemView {" in qss
        assert "QComboBox::down-arrow" not in qss
        assert "QCheckBox::indicator" not in qss
        # multi-line text views (evidence/logs)
        assert "QPlainTextEdit, QTextEdit {" in qss
        assert "QPlainTextEdit:focus" in qss
        # dialog default buttons get the accent outline
        assert "QPushButton:default {" in qss
        # horizontal scrollbars mirror the vertical rules
        assert "QScrollBar:horizontal {" in qss
        assert "QScrollBar::handle:horizontal {" in qss

    def test_placeholder_palette_role(self, qapp) -> None:
        color = qapp.palette().color(QPalette.ColorRole.PlaceholderText)
        assert color.name().lower() == theme.TEXT_MUTED.lower()

    def test_window_minimums_unchanged(self) -> None:
        assert theme.MIN_WINDOW_WIDTH == 960
        assert theme.MIN_WINDOW_HEIGHT == 640

    def test_inline_feedback_routes_through_the_helper(self) -> None:
        import ui_desktop.screens.dashboard as dashboard
        import ui_desktop.screens.reports as reports
        import ui_desktop.settings_dialog as settings

        modules = (dashboard, reports, settings)
        for module in modules:
            assert module.__file__ is not None
            with open(module.__file__, encoding="utf-8") as handle:
                source = handle.read()
            assert "theme.feedback_qss(" in source, module.__name__


# ===========================================================================
# motion
# ===========================================================================


class TestStage13Motion:
    def test_fade_duration_is_short(self) -> None:
        assert 1 <= motion.FADE_MS <= 250

    def test_reduced_motion_env_beats_the_platform(
            self, qapp, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(motion.REDUCED_MOTION_ENV, "1")
        assert motion.reduced_motion(qapp=qapp) is True
        monkeypatch.setenv(motion.REDUCED_MOTION_ENV, "0")
        assert motion.reduced_motion(qapp=qapp) is False
        # unknown value falls through to OS detection (NoPreference offscreen)
        monkeypatch.setenv(motion.REDUCED_MOTION_ENV, "sometimes")
        assert motion.reduced_motion(qapp=qapp) is False
        monkeypatch.delenv(motion.REDUCED_MOTION_ENV, raising=False)
        assert motion.reduced_motion(qapp=qapp) is False

    def test_fade_in_sets_then_removes_its_effect(self, qapp) -> None:
        widget = QWidget()
        assert motion.fade_in(widget) is True
        effect = widget.graphicsEffect()
        assert effect is not None and isinstance(
            effect, QGraphicsOpacityEffect)
        # the running-animation bookkeeping sits on the widget itself
        assert widget.property("_vsMotionFade") is not None
        # completes and cleans up — pump only, no sleeps
        assert pump_until(qapp, lambda: widget.graphicsEffect() is None,
                          timeout_s=5)
        assert widget.property("_vsMotionFade") is None

    def test_fade_in_refuses_under_reduced_motion(
            self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(motion.REDUCED_MOTION_ENV, "1")
        widget = QWidget()
        assert motion.fade_in(widget) is False
        assert widget.graphicsEffect() is None
        assert widget.property("_vsMotionFade") is None

    def test_fade_in_guards(self) -> None:
        assert motion.fade_in(None) is False
        widget = QWidget()
        assert motion.fade_in(widget, duration_ms=0) is False
        assert widget.graphicsEffect() is None

    def test_restart_safety_replaces_the_running_fade(self, qapp) -> None:
        widget = QWidget()
        assert motion.fade_in(widget) is True
        assert motion.fade_in(widget) is True
        assert widget.graphicsEffect() is not None
        # both animations settle without error; final state fully healed
        assert pump_until(qapp, lambda: widget.graphicsEffect() is None,
                          timeout_s=5)


# ===========================================================================
# shell (navigation fade, focus, rebuild)
# ===========================================================================


class TestStage13Shell:
    @pytest.fixture()
    def window(self, qapp, config_service, backend_factory, tmp_path,
               monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(backend_module, "history_dir",
                            (lambda: tmp_path / "history"), raising=True)
        transport = Stage12Transport(devices_lines=("S1 device",))
        backend = backend_factory(config_service, transport)
        window = MainWindow(config_service, backend=backend)
        try:
            yield window
        finally:
            window.close()
            window.deleteLater()
            backend.shutdown_jobs()

    def test_initial_switch_does_not_fade(self, window) -> None:
        dashboard = window.content_widget("dashboard")
        assert dashboard.graphicsEffect() is None

    def test_user_navigation_fades_once_then_cleans_up(
            self, qapp, window) -> None:
        window.switch_to("devices")
        page = window.content_widget("devices")
        assert isinstance(page, DeviceWorkspacePage)
        assert page.graphicsEffect() is not None
        assert pump_until(qapp, lambda: page.graphicsEffect() is None,
                          timeout_s=5)

    def test_same_section_reselect_does_not_refade(self, window) -> None:
        dashboard = window.content_widget("dashboard")
        window.switch_to("dashboard")
        assert dashboard.graphicsEffect() is None

    def test_navigation_under_reduced_motion_never_fades(
            self, window, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(motion.REDUCED_MOTION_ENV, "1")
        window.switch_to("devices")
        page = window.content_widget("devices")
        assert page.graphicsEffect() is None

    def test_dashboard_rebuild_still_works(self, window) -> None:
        window.switch_to("dashboard")
        window._invalidate_dashboard()
        assert window.content_widget("dashboard") is not None
        assert window._current_id == "dashboard"

    def test_initial_keyboard_focus_reaches_the_nav_rail(
            self, qapp, window) -> None:
        window.show()
        qapp.processEvents()
        nav = window._nav
        focus = window.focusWidget()
        assert focus in (nav, nav.viewport())
        assert nav.focusPolicy() == Qt.FocusPolicy.StrongFocus

    def test_tables_keep_strong_focus(self, window) -> None:
        window.switch_to("scan")
        scan_page = window.content_widget("scan")
        assert isinstance(scan_page, ScanWorkspacePage)
        assert scan_page._devices_table.focusPolicy() == \
            Qt.FocusPolicy.StrongFocus
        assert scan_page._findings_table.focusPolicy() == \
            Qt.FocusPolicy.StrongFocus


# ===========================================================================
# accessibility
# ===========================================================================


class TestStage13Accessibility:
    def test_button_always_has_an_accessible_name(self) -> None:
        plain = button("Retry")
        assert plain.accessibleName() == "Retry button"
        named = button("Retry", accessible_name="Retry device probe")
        assert named.accessibleName() == "Retry device probe"
        with pytest.raises(ValueError):
            button("Bogus", variant="danger")

    def test_admin_dialog_input_is_named(self) -> None:
        dialog = AdminConfirmDialog("uninstall", "com.example.app", "S1")
        try:
            asserted = dialog._input.accessibleName()
            assert asserted == "Exact package name confirmation"
        finally:
            dialog.close()
            dialog.deleteLater()

    def test_dynamic_banners_on_live_pages_are_named(
            self, qapp, config_service, backend_factory, tmp_path,
            monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(backend_module, "history_dir",
                            (lambda: tmp_path / "history"), raising=True)
        transport = Stage12Transport(devices_lines=("S1 device",),
                                     third_party=("com.demo.app",))
        backend = backend_factory(config_service, transport)
        bridge = _bridge(backend)
        monitoring = MonitoringPage(backend, bridge.hub)
        mirroring = MirroringPage(backend, bridge.hub)
        demo = DemoPage(backend, open_live=None)
        try:
            assert monitoring._devices_banner.accessibleName() == \
                "Device discovery status"
            assert monitoring._scope_banner.accessibleName() == \
                "Monitoring scope"
            assert mirroring._devices_banner.accessibleName() == \
                "Device discovery status"
            assert mirroring._target_banner.accessibleName() == \
                "Mirroring target status"
            assert mirroring._tool_banner.accessibleName() == \
                "Mirror tool status"
            assert mirroring._lifecycle_banner.accessibleName() == \
                "Mirroring process status"
            assert demo._summary_label.accessibleName() == \
                "Demo dataset status"
            assert demo.accessibleName() == "Demo data"
        finally:
            for page in (demo, mirroring, monitoring):
                _shutdown(page)

    def test_settings_validation_row_is_named(self, config_service) -> None:
        dialog = SettingsDialog(config_service, adb_probe=lambda _p: True)
        try:
            assert dialog._validate_status.accessibleName() == \
                "ADB path validation result"
            assert dialog._error_label.accessibleName() == "Settings error"
        finally:
            dialog.close()
            dialog.deleteLater()

    def test_min_dialogs_fit_the_minimal_window(self) -> None:
        # the fixed-width confirm dialogs must fit the 960×640 minimum
        dialog = AdminConfirmDialog("uninstall", "com.example.app", "S1")
        try:
            assert dialog.width() == 520 <= theme.MIN_WINDOW_WIDTH
        finally:
            dialog.close()
            dialog.deleteLater()

    def test_destructive_dialog_buttons_carry_honest_names(self) -> None:
        dialog = AdminConfirmDialog("clear-data", "com.example.app", "S1")
        try:
            box = dialog.findChild(QDialogButtonBox)
            assert box is not None
            ok = box.button(QDialogButtonBox.StandardButton.Ok)
            cancel = box.button(QDialogButtonBox.StandardButton.Cancel)
            assert ok.text() == "Proceed"
            assert ok.accessibleName() == "clear-data com.example.app proceed"
            assert cancel.accessibleName() == "Cancel — dispatches nothing"
        finally:
            dialog.close()
            dialog.deleteLater()

    def test_cleartext_dialog_buttons_carry_honest_names(self) -> None:
        dialog = CleartextConfirmDialog("case-a11y")
        try:
            box = dialog.findChild(QDialogButtonBox)
            assert box is not None
            ok = box.button(QDialogButtonBox.StandardButton.Ok)
            cancel = box.button(QDialogButtonBox.StandardButton.Cancel)
            assert ok.accessibleName() == "Write clear-text PSKs proceed"
            assert cancel.accessibleName() == "Cancel — writes nothing"
        finally:
            dialog.close()
            dialog.deleteLater()


# ===========================================================================
# dialog Escape semantics (REAL dialogs, key events through QTest)
# ===========================================================================


class TestStage13DialogEscape:
    def test_admin_confirm_escape_accepts_nothing(self) -> None:
        accepted: List[bool] = []
        dialog = AdminConfirmDialog("uninstall", "com.example.app", "S1")
        dialog.accepted.connect(lambda: accepted.append(True))
        try:
            # typing the package arms Proceed, but Escape still cancels
            dialog._input.setText("com.example.app")
            assert dialog._proceed.isEnabled()
            QTest.keyClick(dialog, Qt.Key.Key_Escape)
            assert dialog.result() != QDialog.DialogCode.Accepted
            assert accepted == []
            assert dialog.typed_package() == "com.example.app"
        finally:
            dialog.close()
            dialog.deleteLater()

    def test_admin_confirm_escape_rejects(self) -> None:
        dialog = AdminConfirmDialog("clear-data", "com.example.app", "S1")
        try:
            QTest.keyClick(dialog, Qt.Key.Key_Escape)
            assert dialog.result() == QDialog.DialogCode.Rejected
            assert not dialog._proceed.isEnabled()
        finally:
            dialog.close()
            dialog.deleteLater()

    def test_cleartext_confirm_escape_writes_nothing(self) -> None:
        dialog = CleartextConfirmDialog("case-esc")
        dialog._input.setText(ACK_PHRASE)
        try:
            QTest.keyClick(dialog, Qt.Key.Key_Escape)
            assert dialog.result() == QDialog.DialogCode.Rejected
            # the input remains, but rejection is the only outcome: no
            # accept, no token, nothing written (page dispatches only on
            # an Accepted result)
        finally:
            dialog.close()
            dialog.deleteLater()

    def test_settings_escape_never_saves(self, tmp_path) -> None:
        service = ConfigService(tmp_path / "escape-config.json")
        service.save(r"C:\tools\fake-adb.exe")
        path = tmp_path / "escape-config.json"
        before = path.read_text(encoding="utf-8")
        dialog = SettingsDialog(service, adb_probe=lambda _p: True)
        try:
            dialog._adb_edit.setText(r"C:\changed\adb.exe")
            QTest.keyClick(dialog, Qt.Key.Key_Escape)
            assert dialog.result() == QDialog.DialogCode.Rejected
            assert path.read_text(encoding="utf-8") == before
        finally:
            dialog.close()
            dialog.deleteLater()
