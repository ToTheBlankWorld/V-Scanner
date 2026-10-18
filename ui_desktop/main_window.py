"""V-Scanner desktop application shell (Stage 09 main window).

The single ``QMainWindow`` driving the whole desktop application:

* Persistent navigation rail (built once from ``ui_desktop.sections``),
  a section header block, the content ``QStackedWidget``, and a status bar.
* Navigation never creates duplicate widgets, connections, timers or
  workers: exactly one content widget exists per section, built lazily on
  first activation and reused (stack-index switching, like the TUI's
  per-section cache).
* Future-stage sections render honest placeholders
  (``screens.placeholder.build_placeholder``) — no faked content anywhere.
* Closing the window detaches any attached Qt job bridge (explicit
  ownership/shutdown, mission §10) and accepts the close event.

Keyboard surface: the rail is a plain ``QListWidget`` (Tab focus, arrows to
move, Enter/Space activate — Qt native); ``Ctrl+,`` opens Settings, ``F1``
jumps to Help & keys, ``Ctrl+Q`` closes. The authoritative table renders
in the help screen (``screens.help.SHORTCUT_ROWS``).
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QSizePolicy,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from vscanner.services.config import ConfigService

from . import __version__, APP_NAME, APP_SUBTITLE
from . import theme
from .backend import DesktopBackend
from .jobs_bridge_qt import QT_AVAILABLE, QtJobEventBridge
from .screens import (
    build_dashboard,
    build_doctor,
    build_help_section,
    build_placeholder,
)
from .screens.devices import DeviceWorkspacePage
from .screens.reports import ReportsPage
from .screens.scan import ScanWorkspacePage
from .sections import (
    INITIAL_SECTION_ID,
    SECTION_REGISTRY,
    DesktopSection,
    UnknownSectionError,
    get_section,
)
from .settings_dialog import SettingsDialog
from .widgets import ErrorState, NavRail, SectionHeader, button

__all__ = ["MainWindow"]


class MainWindow(QMainWindow):
    """The desktop application shell (exactly one per application run)."""

    section_changed = Signal(str)
    """Emitted when the visible section actually changes (id)."""

    def __init__(
        self,
        config_service: Optional[ConfigService] = None,
        *,
        backend: Optional[DesktopBackend] = None,
        config_error: Optional[str] = None,
        host_details: bool = True,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._config_service = config_service
        self._config_error = config_error
        self._host_details = host_details
        self._current_id: str = ""
        self._backend: Optional[DesktopBackend] = backend
        self._job_bridge: Optional[Any] = None  # QtJobEventBridge (Stage 10)

        self.setWindowTitle(f"{APP_NAME} — {APP_SUBTITLE}")
        self.setMinimumSize(theme.MIN_WINDOW_WIDTH, theme.MIN_WINDOW_HEIGHT)
        self.resize(1120, 720)
        self.setObjectName("mainWindow")

        self._section_root: dict[str, QWidget] = {}
        self._section_index: dict[str, int] = {}

        self._build_shell()
        self._install_shortcuts()
        if backend is not None:
            # One shared delivery bridge for the whole session: the shell
            # owns it (delivery-only; detached in closeEvent).
            self._job_bridge = QtJobEventBridge()
            self._job_bridge.attach(backend.manager())
        self.switch_to(INITIAL_SECTION_ID)

    # ------------------------------------------------------------------ #
    # construction
    # ------------------------------------------------------------------ #

    def _build_shell(self) -> None:
        central = QWidget(self)
        central.setObjectName("centralArea")
        shell = QHBoxLayout(central)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)

        shell.addWidget(self._build_sidebar())

        content_column = QWidget(central)
        content_column.setObjectName("contentColumn")
        column = QVBoxLayout(content_column)
        column.setContentsMargins(16, 14, 16, 10)
        column.setSpacing(10)

        self._header = SectionHeader(content_column)
        column.addWidget(self._header)

        self._content_stack = QStackedWidget(content_column)
        self._content_stack.setObjectName("contentStack")
        column.addWidget(self._content_stack, 1)
        shell.addWidget(content_column, 1)

        self.setCentralWidget(central)

        status = QStatusBar(self)
        status.setObjectName("statusBar")
        version_label = QLabel(
            f"v{__version__} — Stage 09 shell + Stage 10 device workspace "
            "+ Stage 11 scanning, findings, reports & history",
            status)
        version_label.setObjectName("statusVersion")
        status.addPermanentWidget(version_label)
        self.setStatusBar(status)

    def _build_sidebar(self) -> QFrame:
        sidebar = QFrame(self)
        sidebar.setObjectName("sidePanel")
        sidebar.setFixedWidth(theme.NAV_WIDTH)
        sidebar.setSizePolicy(QSizePolicy.Policy.Fixed,
                              QSizePolicy.Policy.Expanding)

        column = QVBoxLayout(sidebar)
        column.setContentsMargins(12, 14, 12, 12)
        column.setSpacing(10)

        # Compact, intentional brand block (no decorative logos).
        brand_row = QHBoxLayout()
        brand_row.setContentsMargins(6, 0, 0, 0)
        brand_row.setSpacing(6)
        mark = QLabel("V", sidebar)
        mark.setObjectName("brandMark")
        mark.setFixedSize(24, 24)
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        brand_name = QLabel(APP_NAME, sidebar)
        brand_name.setObjectName("brandName")
        brand_version = QLabel(f"v{__version__}", sidebar)
        brand_version.setObjectName("brandVersion")
        brand_column = QVBoxLayout()
        brand_column.setContentsMargins(0, 0, 0, 0)
        brand_column.setSpacing(0)
        brand_column.addWidget(brand_name)
        brand_column.addWidget(brand_version)
        brand_row.addWidget(mark)
        brand_row.addLayout(brand_column, 1)
        column.addLayout(brand_row)

        self._nav = NavRail(SECTION_REGISTRY, sidebar)
        self._nav.section_activated.connect(self.switch_to)
        column.addWidget(self._nav)
        column.addStretch(1)

        actions = QVBoxLayout()
        actions.setContentsMargins(6, 0, 0, 0)
        actions.setSpacing(6)
        settings = button(
            "Settings", variant="secondary",
            tooltip="Open the ADB path settings (Ctrl+,)",
            accessible_name="Open settings")
        settings.clicked.connect(self.open_settings)
        actions.addWidget(settings)
        column.addLayout(actions)
        return sidebar

    def _install_shortcuts(self) -> None:
        self._shortcut_settings = QShortcut(QKeySequence("Ctrl+,"), self)
        self._shortcut_settings.activated.connect(self.open_settings)
        self._shortcut_help = QShortcut(QKeySequence("F1"), self)
        self._shortcut_help.activated.connect(lambda: self.switch_to("help"))
        self._shortcut_quit = QShortcut(QKeySequence("Ctrl+Q"), self)
        self._shortcut_quit.activated.connect(self.close)

    # ------------------------------------------------------------------ #
    # navigation
    # ------------------------------------------------------------------ #

    @property
    def current_section_id(self) -> str:
        """The stable id of the currently displayed section."""
        return self._current_id

    def switch_to(self, section_id: str, *,
                  record_status: bool = True) -> None:
        """Switch to a registered section (invalid ids raise — typed).

        ``"dialog"`` sections (Settings) open the dialog and keep the
        current selection instead of leaving the displayed section.
        """
        section = get_section(section_id)

        if section.kind == "dialog":
            self.open_settings()
            if self._current_id:
                self._nav.select_section(self._current_id)
            return

        widget = self._content_root(section)
        index = self._index_for(section_id, widget)
        self._content_stack.setCurrentIndex(index)
        previous = self._current_id
        self._current_id = section_id
        self._nav.select_section(section_id)
        activate = getattr(widget, "activate", None)
        if callable(activate):
            activate()  # per-section on-activation hook (e.g. one auto-discovery)
        self._header.configure(
            section.title,
            section.subtitle + (
                f" — planned for {section.owner_stage}"
                if section.kind == "future" else ""))
        if record_status:
            message = f"Section: {section.title}"
            if section.kind == "future":
                message += f" (planned for {section.owner_stage} — placeholder)"
            self.statusBar().showMessage(message)
        if previous != section_id:
            self.section_changed.emit(section_id)

    def _content_root(self, section: DesktopSection) -> QWidget:
        cached = self._section_root.get(section.section_id)
        if cached is not None:
            return cached
        builder = self._builder_for(section)
        widget = builder(self)
        self._section_root[section.section_id] = widget
        return widget

    def _builder_for(
            self, section: DesktopSection) -> Callable[[QWidget], QWidget]:
        if section.kind == "future":
            def build_future(_parent: QWidget) -> QWidget:
                return build_placeholder(section)
            return build_future
        if section.section_id == "dashboard":
            def build_dashboard_view(_parent: QWidget) -> QWidget:
                return build_dashboard(
                    self._config_service,
                    open_devices=(
                        (lambda: self.switch_to("devices"))
                        if self._backend is not None else None),
                    config_error=self._config_error,
                    host_details=self._host_details)
            return build_dashboard_view
        if section.section_id == "devices":
            def build_devices_view(_parent: QWidget) -> QWidget:
                if self._backend is None or self._job_bridge is None:
                    return ErrorState(
                        "Device workspace unavailable",
                        "No engine configuration is wired in this launch, "
                        "so device discovery cannot run. Fix the "
                        "configuration and restart the desktop shell.")
                return DeviceWorkspacePage(
                    self._backend, self._job_bridge.hub, _parent)
            return build_devices_view
        if section.section_id == "scan":
            def build_scan_view(_parent: QWidget) -> QWidget:
                if self._backend is None or self._job_bridge is None:
                    return ErrorState(
                        "Scanning workspace unavailable",
                        "No engine configuration is wired in this launch, "
                        "so scans cannot run. Fix the configuration and "
                        "restart the desktop shell.")
                return ScanWorkspacePage(
                    self._backend, self._job_bridge.hub, _parent)
            return build_scan_view
        if section.section_id == "reports":
            def build_reports_view(_parent: QWidget) -> QWidget:
                if self._backend is None or self._job_bridge is None:
                    return ErrorState(
                        "Reports workspace unavailable",
                        "No engine configuration is wired in this launch, "
                        "so report export and history cannot run. Fix the "
                        "configuration and restart the desktop shell.")
                return ReportsPage(
                    self._backend, self._job_bridge.hub, _parent)
            return build_reports_view
        if section.section_id == "doctor":
            def build_doctor_view(_parent: QWidget) -> QWidget:
                return build_doctor(host_details=self._host_details)
            return build_doctor_view
        if section.section_id == "help":
            def build_help_view(_parent: QWidget) -> QWidget:
                return build_help_section(
                    "Tip: the navigation rail keeps focus after a switch — "
                    "arrow keys move, Enter activates. Tab moves into the page.")
            return build_help_view
        raise UnknownSectionError(section.section_id)

    def _index_for(self, section_id: str, widget: QWidget) -> int:
        known = self._section_index.get(section_id)
        if known is not None:
            return known
        index = self._content_stack.addWidget(widget)
        self._section_index[section_id] = index
        return index

    def content_widget(self, section_id: str) -> QWidget:
        """Test accessor: the cached content root for a section."""
        try:
            return self._section_root[section_id]
        except KeyError as exc:
            raise UnknownSectionError(section_id) from exc

    # ------------------------------------------------------------------ #
    # settings
    # ------------------------------------------------------------------ #

    def open_settings(self) -> None:
        """Open the config-backed settings dialog (honest no-op reporting
        when no configuration service is wired — never silent)."""
        if self._config_service is None:
            self.statusBar().showMessage(
                "Settings unavailable: no configuration service is wired "
                "in this launch.")
            return
        dialog = SettingsDialog(self._config_service, self)
        result = dialog.exec()
        if result == int(dialog.DialogCode.Accepted):
            self.statusBar().showMessage("Settings saved.")
            self._invalidate_dashboard()

    def _invalidate_dashboard(self) -> None:
        """Rebuild the dashboard after config changes (no widget leak)."""
        if "dashboard" not in self._section_root:
            return
        old = self._section_root.pop("dashboard")
        index = self._section_index.pop("dashboard")
        widget = self._content_root(get_section("dashboard"))
        self._content_stack.insertWidget(index, widget)
        self._content_stack.removeWidget(old)
        self._section_index["dashboard"] = index
        self._content_stack.setCurrentIndex(
            self._section_index[self._current_id])
        old.deleteLater()

    # ------------------------------------------------------------------ #
    # job bridge wiring seam (Stage 10 fills it; Stage 09 proves the rule)
    # ------------------------------------------------------------------ #

    def attach_job_bridge(self, bridge: Any, event_source: Any) -> None:
        """Attach a ``QtJobEventBridge`` to a JobManager-like source.

        Ownership: the shell never owns subscriptions the caller didn't
        declare — the bridge is detached in :meth:`closeEvent`, and it
        creates no worker threads (delivery-only).
        """
        self._job_bridge = bridge
        bridge.attach(event_source)

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt caller convention)
        """Detach owned subscriptions, stop section-owned background work,
        shut the job manager down with its grace period, then accept."""
        bridge = self._job_bridge
        if bridge is not None and bridge.attached:
            bridge.detach()
        self._job_bridge = None
        for widget in list(self._section_root.values()):
            shutdown = getattr(widget, "shutdown", None)
            if callable(shutdown):
                shutdown()
        if self._backend is not None:
            self._backend.shutdown_jobs()
        super().closeEvent(event)
