"""Settings dialog (Stage 09 desktop) — ADB path through ``ConfigService``.

The only settings surface the Stage 09 scope requires (ROADMAP Stage 09:
"settings dialog"). All persistence goes through
:class:`vscanner.services.config.ConfigService` — no settings file I/O is
duplicated here, and validation errors never crash the dialog (honest
inline error text; AC evidence "settings persistence through ConfigService").

Deliberately out of scope (documented, not faked): live ADB path validation
launches a process — that arrives with device management (Stage 10).
"""

from __future__ import annotations

from typing import Optional

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
from vscanner.services.config import ConfigService, ConfigSnapshot

from . import theme
from .widgets import button

__all__ = ["SettingsDialog"]


class SettingsDialog(QDialog):
    """Modal settings editor backed by the ConfigService (SC-11)."""

    def __init__(self, config_service: ConfigService,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._config_service = config_service
        self._snapshot: Optional[ConfigSnapshot] = None
        self._configure_window()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 12)
        layout.setSpacing(8)

        intro = QLabel(
            "Absolute path to the ADB executable. Leave empty to save no "
            "path. The desktop shell does not validate the path in this "
            "stage — validation lands with device management (Stage 10).",
            self)
        intro.setObjectName("secondaryText")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        field_label = QLabel("A&DB path:", self)
        self._adb_edit = QLineEdit(self)
        self._adb_edit.setClearButtonEnabled(True)
        self._adb_edit.setPlaceholderText("(not set — browse manually in a later stage)")
        self._adb_edit.setToolTip(
            "Point at adb.exe (e.g. a platform-tools directory). Saved to "
            "the engine config file on Apply.")
        self._adb_edit.setAccessibleName("ADB path")
        field_label.setBuddy(self._adb_edit)
        layout.addWidget(field_label)
        layout.addWidget(self._adb_edit)

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
        self.setMinimumWidth(480)
        self.setAccessibleName("Settings dialog")

    # -- load / save ------------------------------------------------------- #

    def _load(self) -> None:
        """Pre-fill from the authoritative config snapshot (strict read)."""
        snapshot = self._config_service.load()
        self._snapshot = snapshot
        self._adb_edit.setText(snapshot.adb_path or "")

    def editor_adb_path(self) -> Optional[str]:
        """The pending path in the editor (tests inspect the field state)."""
        return self._adb_edit.text().strip() or None

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
