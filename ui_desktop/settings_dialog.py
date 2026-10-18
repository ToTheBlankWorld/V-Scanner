"""Settings dialog (Stage 10 desktop) — ADB path through ``ConfigService``.

Persistence goes only through :class:`vscanner.services.config.ConfigService`
— no settings file I/O is duplicated here; failures show honest inline
error text and never crash the dialog (Stage 09 behavior, kept).

Stage 10 addition (the part Stage 09 deliberately deferred): a strictly
user-initiated "Validate path now" control. It launch-probes the typed
path with the shared engine check
(``services.adb.executable.check_adb_valid`` — one ``adb version``
subprocess) inside a background worker, never on the GUI thread and never
automatically at dialog open or on Apply. The states "untested / valid /
invalid / refused (busy)" are distinct in the inline status.
"""

from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from vscanner.core.errors import ConfigError
from vscanner.services.adb.executable import check_adb_valid
from vscanner.services.config import ConfigService, ConfigSnapshot

from . import theme
from .workers import WorkerCoordinator
from .widgets import button

__all__ = ["SettingsDialog"]


class SettingsDialog(QDialog):
    """Modal settings editor backed by the ConfigService (SC-11)."""

    def __init__(self, config_service: ConfigService,
                 parent: Optional[QWidget] = None, *,
                 adb_probe: Optional[Callable[[str], bool]] = None) -> None:
        super().__init__(parent)
        self._config_service = config_service
        self._snapshot: Optional[ConfigSnapshot] = None
        self._probe: Callable[[str], bool] = adb_probe if adb_probe is not None \
            else check_adb_valid
        self._workers = WorkerCoordinator(parent=self)
        self._configure_window()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 12)
        layout.setSpacing(8)

        intro = QLabel(
            "Absolute path to the ADB executable. Leave empty to save no "
            "path. Validation below is strictly user-initiated — it runs "
            "one adb version probe in the background and never launches "
            "anything on its own.",
            self)
        intro.setObjectName("secondaryText")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        field_label = QLabel("A&DB path:", self)
        self._adb_edit = QLineEdit(self)
        self._adb_edit.setClearButtonEnabled(True)
        self._adb_edit.setPlaceholderText(
            "(not set — type or paste the path to adb.exe)")
        self._adb_edit.setToolTip(
            "Point at adb.exe (e.g. a platform-tools directory). Saved to "
            "the engine config file on Apply.")
        self._adb_edit.setAccessibleName("ADB path")
        field_label.setBuddy(self._adb_edit)
        layout.addWidget(field_label)
        layout.addWidget(self._adb_edit)

        validate_row = QHBoxLayout()
        self._validate_button = button(
            "&Validate path now", variant="secondary",
            tooltip="Launch-probe the typed path (one adb version call, "
                    "background worker; never on the GUI thread)",
            accessible_name="Validate adb path")
        self._validate_button.clicked.connect(self._validate)
        self._validate_status = QLabel("", self)
        self._validate_status.setObjectName("hintText")
        self._validate_status.setWordWrap(True)
        validate_row.addWidget(self._validate_button)
        validate_row.addWidget(self._validate_status, 1)
        layout.addLayout(validate_row)

        self._error_label = QLabel(self)
        self._error_label.setObjectName("hintText")
        self._error_label.setWordWrap(True)
        self._error_label.setStyleSheet(
            f"color: {theme.ERROR_COLOR}; background: transparent;")
        self._error_label.hide()
        layout.addWidget(self._error_label)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self._apply_button = button("&Apply", variant="primary",
                                    accessible_name="Apply settings")
        self._apply_button.setDefault(True)
        cancel_button = button("&Cancel", variant="secondary",
                               accessible_name="Cancel settings dialog")
        buttons.addWidget(self._apply_button)
        buttons.addWidget(cancel_button)
        layout.addLayout(buttons)

        self._apply_button.clicked.connect(self._apply)
        cancel_button.clicked.connect(self.reject)

        self._load()

    # -- window config ----------------------------------------------------- #

    def _configure_window(self) -> None:
        self.setWindowTitle("Settings — V-Scanner")
        self.setModal(True)
        self.setMinimumWidth(520)
        self.setAccessibleName("Settings dialog")

    # -- load / save ------------------------------------------------------- #

    def _load(self) -> None:
        """Pre-fill from the authoritative config snapshot (strict read)."""
        snapshot = self._config_service.load()
        self._snapshot = snapshot
        self._adb_edit.setText(snapshot.adb_path or "")
        self._validate_status.setText("path not validated in this session")

    def editor_adb_path(self) -> Optional[str]:
        """The pending path in the editor (tests inspect the field state)."""
        return self._adb_edit.text().strip() or None

    # -- validation (user-initiated, background worker) --------------------- #

    def _validate(self) -> None:
        """Launch-probe the currently typed path (worker, never startup)."""
        raw = self._adb_edit.text().strip()
        if not raw:
            self._validate_status.setText(
                "No path entered — nothing to validate")
            return
        if self._workers.is_pending("validate_adb"):
            self._validate_status.setText(
                "A validation probe is already running — wait for its "
                "result")
            return
        self._validate_button.setEnabled(False)
        self._validate_status.setText("validating — one adb version probe "
                                      "is running in the background…")

        def finish(valid: bool, exc: Optional[BaseException] = None) -> None:
            # re-enabled in every case; invalid is an honest result
            self._validate_button.setEnabled(True)
            self._validate_status.setText(
                "path is valid — a working adb executable"
                if valid else
                "path is NOT a launchable adb executable")

        def sink() -> bool:
            return bool(self._probe(raw))

        started = self._workers.run(
            "validate_adb", sink,
            lambda result: finish(bool(result)),
            lambda exc: finish(False, exc),
        )
        if not started:
            self._validate_button.setEnabled(True)
            self._validate_status.setText(
                "validation refused — another probe is pending")

    def _apply(self) -> None:
        """Save through the ConfigService; typed failures show inline text."""
        raw = self._adb_edit.text().strip()
        path: Optional[str] = raw or None
        try:
            self._config_service.save(path)
        except (ConfigError, OSError) as exc:
            self._error_label.setText(f"Could not save settings: {exc}")
            self._error_label.show()
            self._adb_edit.setFocus(Qt.FocusReason.OtherFocusReason)
            return
        self._error_label.hide()
        self.accept()
