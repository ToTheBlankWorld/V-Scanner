"""Reusable desktop widgets for the V-Scanner shell (Stage 09).

Small, composable Qt-Widgets components used by the shell and the Stage 09
live sections (dashboard / doctor / help). Everything visual comes from
``ui_desktop.theme`` — no widget writes colors here (AST-guarded).

Design rules (Stage 09 mission §8):

* Composition over deep inheritance; tiny, predictable APIs.
* Status is text + glyph + color (never color alone).
* No decorative components: each widget here is used by a live screen.
* No timers or cross-thread connections inside components (the only
  animation is Qt's built-in busy ``QProgressBar``, owned by Qt itself).
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from . import theme
from .sections import DesktopSection, UnknownSectionError

__all__ = [
    "Panel", "SectionHeader", "StatusChip", "MetadataRow",
    "EmptyState", "ErrorState", "LoadingState", "PlaceholderState",
    "NavRail", "button", "status_chip",
]


# ---------------------------------------------------------------------------
# Layout primitives
# ---------------------------------------------------------------------------

class Panel(QFrame):
    """Standard surface panel (``QFrame#panel`` in the theme QSS)."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("panel")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)

    @staticmethod
    def body_layout(panel: "Panel") -> QVBoxLayout:
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(theme.SPACING["l"], theme.SPACING["m"],
                                  theme.SPACING["l"], theme.SPACING["l"])
        layout.setSpacing(theme.SPACING["s"])
        return layout


class SectionHeader(QWidget):
    """Current-section title + subtitle shown by the shell header."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        self.title_label = QLabel(self)
        self.title_label.setObjectName("sectionTitle")
        self.subtitle_label = QLabel(self)
        self.subtitle_label.setObjectName("sectionSubtitle")
        self.subtitle_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.title_label)
        layout.addWidget(self.subtitle_label)
        self._configure_titles("", "")

    def configure(self, title: str, subtitle: str) -> None:
        self._configure_titles(title, subtitle)

    def _configure_titles(self, title: str, subtitle: str) -> None:
        self.title_label.setText(title)
        self.title_label.setAccessibleName(f"Section title: {title}")
        self.subtitle_label.setText(subtitle)
        self.subtitle_label.setVisible(bool(subtitle))


# ---------------------------------------------------------------------------
# Status + metadata
# ---------------------------------------------------------------------------

class StatusChip(QWidget):
    """A colored status presented with its glyph and textual label.

    ``severity`` is one of ``ok | warning | error | info | neutral`` —
    central semantics shared by every desktop section (theme tokens).
    """

    def __init__(self, severity: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("statusChip")
        self._severity: str = ""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACING["xs"])
        self.setAccessibleName("status")
        self.glyph_label = QLabel(self)
        self.glyph_label.setObjectName("chipGlyph")
        self.text_label = QLabel(self)
        self.text_label.setObjectName("chipText")
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        layout.addWidget(self.glyph_label)
        layout.addWidget(self.text_label)
        self.set_status(severity)

    def set_status(self, severity: str) -> None:
        """Update severity (unknown names raise — honesty over defaults)."""
        if severity not in theme.STATUS_COLORS:  # noqa: F841 coverage of names
            raise ValueError(f"unknown status severity: {severity!r}")
        self._severity = severity
        self.glyph_label.setText(theme.status_glyph(severity))
        self.glyph_label.setStyleSheet(theme.status_chip_qss(severity))
        label = theme.status_label(severity)
        self.text_label.setText(label)
        self.text_label.setStyleSheet(theme.status_chip_qss(severity))
        self.setAccessibleName(f"status {label}")

    @property
    def severity(self) -> str:
        return self._severity


def status_chip(severity: str, parent: Optional[QWidget] = None) -> StatusChip:
    """Convenience factory for a ``StatusChip`` (readability in screens)."""
    return StatusChip(severity, parent)


class MetadataRow(QWidget):
    """A key/value line: muted key label + primary value label."""

    def __init__(self, key: str, value: str = "",
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("metaRow")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACING["m"])
        self.key_label = QLabel(key, self)
        self.key_label.setObjectName("metaKey")
        self.key_label.setFixedWidth(180)
        self.key_label.setAccessibleName(f"{key}")
        self.value_label = QLabel(self)
        self.value_label.setObjectName("metaValue")
        self.value_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        self.value_label.setWordWrap(True)
        self.set_value(value)
        layout.addWidget(self.key_label)
        layout.addWidget(self.value_label, 1)

    def set_value(self, value: str) -> None:
        self.value_label.setText(value)
        self.value_label.setAccessibleName(f"{self.key_label.text()}: {value}")
        self.setToolTip(self.value_label.text() if value else "")


# ---------------------------------------------------------------------------
# Page states (empty / loading / error / future-stage placeholder)
# ---------------------------------------------------------------------------

def button(text: str, *, variant: str = "secondary", tooltip: str = "",
           accessible_name: str = "") -> QPushButton:
    """Create a themed action button.

    ``variant`` is ``"primary"`` or ``"secondary"`` — matched in the theme
    QSS via the Qt dynamic property; setting it before first show keeps
    styling deterministic.
    """
    if variant not in ("primary", "secondary"):
        raise ValueError(f"unknown button variant: {variant!r}")
    widget = QPushButton(text)
    widget.setProperty("variant", variant)
    # Stage 13: every button exposes an accessible name, even without a
    # tooltip — auto-derived from the label when none declared explicitly.
    widget.setAccessibleName(accessible_name or f"{text} button")
    if tooltip:
        widget.setToolTip(tooltip)
    return widget


class EmptyState(Panel):
    """Honest empty presentation: nothing exists to show, nothing was faked."""

    def __init__(self, title: str, message: str,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = Panel.body_layout(self)
        title_label = QLabel(title, self)
        title_label.setObjectName("panelHeading")
        title_label.setAccessibleName(title)
        title_label.setWordWrap(True)
        title_label.setStyleSheet(
            f"color: {theme.TEXT_SECONDARY}; background: transparent;")
        message_label = QLabel(message, self)
        message_label.setObjectName("secondaryText")
        message_label.setWordWrap(True)
        layout.addWidget(title_label)
        layout.addWidget(message_label)


class ErrorState(Panel):
    """Startup/runtime error presentation with actionable, truthful text."""

    def __init__(self, title: str, message: str,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = Panel.body_layout(self)
        title_label = QLabel(title, self)
        title_label.setObjectName("panelHeading")
        title_label.setAccessibleName(title)
        title_label.setWordWrap(True)
        title_label.setStyleSheet(
            f"color: {theme.ERROR_COLOR}; background: transparent;")
        message_label = QLabel(message, self)
        message_label.setObjectName("bodyText")
        message_label.setWordWrap(True)
        layout.addWidget(title_label)
        layout.addWidget(message_label)


class LoadingState(Panel):
    """Loading presentation with an indeterminate busy bar + text state."""

    def __init__(self, message: str = "Working…",
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = Panel.body_layout(self)
        label = QLabel(message, self)
        label.setObjectName("secondaryText")
        label.setAccessibleName(f"loading: {message}")
        bar = QProgressBar(self)
        bar.setObjectName("busyBar")
        bar.setRange(0, 0)  # indeterminate: Qt drives the animation
        bar.setTextVisible(False)
        bar.setFixedHeight(6)
        layout.addWidget(label)
        layout.addWidget(bar)


class PlaceholderState(Panel):
    """Honest future-stage placeholder: exactly what exists and what does not."""

    def __init__(self, section: DesktopSection,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = Panel.body_layout(self)
        heading = QLabel(section.title, self)
        heading.setObjectName("panelHeading")
        heading.setAccessibleName(section.title)
        stage = QLabel(f"Planned for {section.owner_stage}", self)
        stage.setObjectName("hintText")
        body = QLabel(section.description, self)
        body.setObjectName("secondaryText")
        body.setWordWrap(True)
        disclaimer = QLabel(
            "This section is not implemented in the desktop shell yet. "
            "No functionality, results, or device data is shown or faked here.",
            self)
        disclaimer.setObjectName("hintText")
        disclaimer.setWordWrap(True)
        layout.addWidget(heading)
        layout.addWidget(stage)
        layout.addWidget(body)
        layout.addWidget(disclaimer)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)


# ---------------------------------------------------------------------------
# Navigation
# ---------------------------------------------------------------------------

class NavRail(QListWidget):
    """The persistent section rail; emits ``section_activated(section_id)``.

    Built once from the registry. Keyboard operation is native QListWidget
    behavior: Tab reaches the rail, arrows move, Enter/Space activate.
    """

    section_activated = Signal(str)

    def __init__(self, sections: tuple[DesktopSection, ...], parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("navRail")
        self.setAccessibleName("Section navigation")
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self._loading_selection = False
        for section in sections:
            self._add_item(section)
        self.currentItemChanged.connect(self._on_current_changed)
        self.itemActivated.connect(self._on_current_changed)

    def _add_item(self, section: DesktopSection) -> None:
        label = section.title
        if section.kind == "future":
            label = f"{section.title} — {section.owner_stage}"
        item = QListWidgetItem(label, self)
        item.setData(Qt.ItemDataRole.UserRole, section.section_id)
        item.setToolTip(section.description)
        item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

    def _on_current_changed(self, item: QListWidgetItem) -> None:
        if item is None or self._loading_selection:
            return
        section_id = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(section_id, str):
            self.section_activated.emit(section_id)

    def select_section(self, section_id: str) -> None:
        """Mark the rail selection for ``section_id`` without re-emitting."""
        for row in range(self.count()):
            item = self.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == section_id:
                self._loading_selection = True
                self.setCurrentRow(row)
                self._loading_selection = False
                return
        raise UnknownSectionError(section_id)
