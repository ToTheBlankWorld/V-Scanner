"""Demo data (Stage 12, SC-10 desktop parity): deterministic fixture.

The Qt counterpart of the TUI demo screen:

* The bundle comes from the shared :class:`vscanner.services.demo.
  DemoService` — a deterministic three-app fixture whose findings are
  all INFORMATIONAL severity with ``[DEMO]``-titled rows and a
  provenance note marking them demo data; the bundle's device serial is
  ``None`` and ``summary.demo`` is ``True``.
* NO device is contacted, no transport/network is ever created, and the
  demo flow NEVER touches the real device selection, the scan memory
  (``remember_scan``) or the T-08 scan history — the demo page has no
  path to those seams at all.
* Every surface is labeled DEMO unmissably (banner + button + summary
  line) so fixture rows can never be mistaken for real scan output,
  and the obvious "Back to live data" navigation is provided.

Presentation only, over in-process data: building the fixture is pure
CPU work with no subprocess/transport involvement (TUI parity), so it
stays UI-thread safe by construction.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QPersistentModelIndex,
    Qt,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ..backend import DesktopBackend
from ..widgets import Panel, StatusChip, button

__all__ = ["DemoPage"]


class DemoFindingsTableModel(QAbstractTableModel):
    """Finding rows exactly as the deterministic fixture provides them
    (severity / category / app / title) — nothing is inferred."""

    _HEADERS = ("Severity", "Category", "App", "Finding")

    def __init__(self) -> None:
        super().__init__()
        self._rows: tuple[tuple[str, str, str, str], ...] = ()
        self._note = "no demo dataset generated yet"

    def set_bundle(self, bundle: Any, note: str) -> None:
        self.beginResetModel()
        if bundle is None:
            self._rows = ()
            self._note = note
        else:
            rows: list[tuple[str, str, str, str]] = []
            for app_result in getattr(bundle, "apps", ()):
                app = getattr(app_result, "app", None)
                app_name = (getattr(app, "label", "") or
                            getattr(app, "package", "")) if app else \
                    "device-scope"
                for finding in getattr(app_result, "findings", ()):
                    rows.append((
                        str(getattr(finding, "severity", "")).replace(
                            "FindingSeverity.", ""),
                        str(getattr(finding, "kind", "")).replace(
                            "FindingCategory.", ""),
                        app_name,
                        str(getattr(finding, "title", "")),
                    ))
            self._rows = tuple(rows) or \
                (("—", "—", "—", "fixture produced no findings"),)
            self._note = "—"
        self.endResetModel()

    def rowCount(
            self, parent: QModelIndex | QPersistentModelIndex = QModelIndex(),
    ) -> int:
        if parent.isValid():
            return 0
        return len(self._rows) if self._rows else 1

    def columnCount(
            self, parent: QModelIndex | QPersistentModelIndex = QModelIndex(),
    ) -> int:
        return len(self._HEADERS)

    def headerData(self, section, orientation,
                   role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and \
                role == Qt.ItemDataRole.DisplayRole:
            return self._HEADERS[section]
        return None

    def data(self, index: QModelIndex | QPersistentModelIndex,
             role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        if not self._rows:
            if role == Qt.ItemDataRole.DisplayRole:
                return ("—", self._note, "—", "—")[index.column()]
            return None
        row = self._rows[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return row[index.column()]
        return None

    @property
    def rows(self) -> tuple[tuple[str, str, str, str], ...]:
        return self._rows


class DemoPage(QWidget):
    """One cached per-section demo page (never reconstructed)."""

    def __init__(self, backend: DesktopBackend,
                 open_live: Optional[Callable[[], None]] = None,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._backend = backend
        self._open_live = open_live
        self._state = "idle"  # idle | ready | failed
        self._error: Optional[str] = None

        self.setAccessibleName("Demo data")
        self._build_ui()

    # ------------------------------------------------------------------ #
    # construction
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(12)

        banner_panel = Panel(self)
        banner_layout = Panel.body_layout(banner_panel)
        banner_row = QHBoxLayout()
        banner_row.setContentsMargins(0, 0, 0, 0)
        banner_row.setSpacing(6)
        self._demo_chip = StatusChip("warning", banner_panel)
        banner_row.addWidget(self._demo_chip)
        demo_word = QLabel("DEMO — SIMULATED SAMPLE DATA", banner_panel)
        demo_word.setObjectName("bodyText")
        banner_row.addWidget(demo_word)
        banner_row.addStretch(1)
        banner_layout.addLayout(banner_row)
        banner = QLabel(
            "This table is a DETERMINISTIC FIXTURE built in memory. No "
            "device was contacted — no ADB, no transport, no network. "
            "Nothing here is real scan output; every row exists to "
            "rehearse the findings workflow (SC-10). Real device "
            "selection and scan history are never touched.")
        banner.setObjectName("hintText")
        banner.setWordWrap(True)
        banner_layout.addWidget(banner)
        outer.addWidget(banner_panel)

        table_panel = Panel(self)
        table_layout = Panel.body_layout(table_panel)
        self._summary_label = QLabel("no demo dataset generated yet", self)
        self._summary_label.setObjectName("secondaryText")
        self._summary_label.setWordWrap(True)
        self._summary_label.setAccessibleName("Demo dataset status")
        table_layout.addWidget(self._summary_label)

        self._model = DemoFindingsTableModel()
        self._table = QTableView(table_panel)
        self._table.setObjectName("demoFindingsTable")
        self._table.setModel(self._model)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setMinimumHeight(220)
        self._table.setAccessibleName("Demo findings")
        table_layout.addWidget(self._table, 1)
        outer.addWidget(table_panel, 1)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(6)
        self._generate_button = button(
            "Generate demo dataset", variant="secondary",
            tooltip="Rebuild the deterministic demo fixture in memory "
                    "(no device contact; identical every time)",
            accessible_name="Generate demo dataset")
        self._generate_button.clicked.connect(self.generate)
        actions.addWidget(self._generate_button)
        if self._open_live is not None:
            self._back_button = button(
                "Back to live data", variant="primary",
                tooltip="Leave the demo view and open the real device "
                        "workspace (live data is never replaced by demo "
                        "content)",
                accessible_name="Back to live data")
            self._back_button.clicked.connect(self._open_live)
            actions.addWidget(self._back_button)
        actions.addStretch(1)
        outer.addLayout(actions)

    # ------------------------------------------------------------------ #
    # lifecycle hooks the shell uses
    # ------------------------------------------------------------------ #

    def activate(self) -> None:
        """First activation builds the fixture exactly once (TUI parity:
        on-mount generation); rebuild is an explicit action."""
        if self._state == "idle":
            self.generate()

    def shutdown(self) -> None:
        """No subscriptions owned; nothing to disconnect (explicit)."""

    # ------------------------------------------------------------------ #
    # generation (in-process, deterministic; no device service access)
    # ------------------------------------------------------------------ #

    def generate(self) -> None:
        """Build the SC-10 fixture synchronously (pure in-process work;
        UI-thread safe by construction — TUI parity)."""
        try:
            bundle = self._backend.demo_bundle()
        except Exception as exc:
            self._state = "failed"
            self._error = f"{type(exc).__name__}: {getattr(exc, 'message', exc)}"
            self._render()
            return
        self._state = "ready"
        self._error = None
        self._render(bundle)

    def _render(self, bundle: Any = None) -> None:
        if self._state == "failed":
            self._summary_label.setText(
                f"fixture build failed ({self._error}) — nothing was "
                "fabricated to fill the gap")
            self._model.set_bundle(None, "fixture build failed")
            return
        summary = getattr(bundle, "summary", None)
        if summary is None:
            self._summary_label.setText("no demo dataset generated yet")
            self._model.set_bundle(None, "no demo dataset generated yet")
            return
        apps = getattr(summary, "total_apps", None)
        run = getattr(summary, "run", None)
        run_id = getattr(run, "run_id", "") if run is not None else ""
        demo_flag = getattr(summary, "demo", False)
        self._summary_label.setText(
            f"DEMO dataset: {apps} fixture app(s) · summary.demo flag: "
            f"{demo_flag} · fixture run id: {run_id} — deterministic by "
            "design; rebuilding produces the SAME rows.")
        self._model.set_bundle(bundle, "no findings in the fixture")
