"""Restrained desktop motion helpers (Stage 13).

The single place where application motion policy lives:

* :func:`reduced_motion` — honors an explicit ``VSCANNER_REDUCED_MOTION``
  environment override (``1`` — reduce, ``0`` — allow; anything else falls
  through) and otherwise asks the platform through Qt's accessibility
  hints. PySide6 6.12 re-exports ``QAccessibilityHints.motionPreference``
  (Qt 6.12+), which is populated from OS accessibility settings on
  Windows, macOS and GNOME — verified against PySide6 6.12.0 at runtime
  (``QGuiApplication.styleHints().accessibility().motionPreference()``
  returns ``Qt.MotionPreference.NoPreference``/``ReducedMotion``).
  Older binding versions (no such attribute) degrade to environment-only
  detection, which is why the lookups below are defensive.
* :func:`fade_in` — exactly one short opacity fade on content that appears
  through *user navigation*. Rules (Stage 13 mission §4):

  - never fabricated progress and never the sole state signal (state keeps
    its text/glyph communication; the fade is cosmetic);
  - never blocks the GUI thread — it is a Qt-owned animation on the
    normal event loop, no timers/threads of our own;
  - skipped entirely when reduced motion is requested;
  - the graphics effect is removed as soon as the fade completes, so
    long-lived pages return to native rendering (no permanent raster
    caching and no lasting softness);
  - restart-safe: a new fade on the same widget replaces the previous
    one and the stale effect is never re-removed by the old animation.

Only widgets use motion here; the shared engine and worker threads know
nothing about this module.
"""

from __future__ import annotations

import os
from typing import Optional, cast

from PySide6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QPropertyAnimation,
    Qt,
)
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsEffect,
    QGraphicsOpacityEffect,
    QWidget,
)

__all__ = ["REDUCED_MOTION_ENV", "FADE_MS", "reduced_motion", "fade_in"]

REDUCED_MOTION_ENV = "VSCANNER_REDUCED_MOTION"
FADE_MS = 140  # short, consistency-biased; no stagger, no bounce


def reduced_motion(qapp: Optional[QApplication] = None) -> bool:
    """True when non-essential motion should be reduced.

    Resolution order (documented in Stage 13 report §Motion):
    explicit environment override first, then the OS accessibility
    ``motionPreference`` through Qt (when the runtime binding exposes
    it), then "motion allowed".
    """
    raw = os.environ.get(REDUCED_MOTION_ENV)
    if raw is not None:
        token = raw.strip().lower()
        if token in ("1", "true", "yes"):
            return True
        if token in ("0", "false", "no"):
            return False

    app = qapp if qapp is not None else QApplication.instance()
    if app is None:
        return False
    try:
        # ``QApplication.instance()`` is typed as QCoreApplication in the
        # bindings; styleHints() lives on QGuiApplication/QApplication.
        qt_app = cast("QApplication", app)
        hints = qt_app.styleHints().accessibility()
        getter = getattr(hints, "motionPreference", None)
        if getter is not None:
            return getter() == Qt.MotionPreference.ReducedMotion
    except (AttributeError, RuntimeError):  # older bindings / dead app
        pass
    return False


_FADE_PROPERTY = "_vsMotionFade"


def _clear_effect(widget: QWidget) -> None:
    """Remove a widget's graphics effect.

    Qt accepts ``None`` here (it detaches the effect); the PySide stub
    types the parameter as non-optional, so the removal is centralized in
    this typed helper.
    """
    widget.setGraphicsEffect(cast("QGraphicsEffect", None))


def fade_in(widget: Optional[QWidget], *, duration_ms: int = FADE_MS) -> bool:
    """Start a single short content fade; ``True`` if one was started.

    Returns ``False`` without touching the widget when reduced motion is
    requested or when there is nothing to animate. At most one fade runs
    per widget: a new call explicitly stops the previous animation before
    replacing its effect (restart safety), and the effect is removed on
    completion — long-lived pages return to native rendering.
    """
    if widget is None or duration_ms <= 0:
        return False
    if reduced_motion():
        return False

    try:
        previous = widget.property(_FADE_PROPERTY)
        if previous is not None:
            try:
                previous.stop()  # no further property writes, no finished
            except RuntimeError:
                pass  # C++ side already gone (widget deletion)
            widget.setProperty(_FADE_PROPERTY, None)
        if widget.graphicsEffect() is not None:
            _clear_effect(widget)
    except RuntimeError:
        return False  # widget destroyed between calls (shutdown)

    effect = QGraphicsOpacityEffect(widget)
    animation = QPropertyAnimation(effect, b"opacity", widget)
    animation.setDuration(int(duration_ms))
    animation.setStartValue(0.0001)
    animation.setEndValue(1.0)
    animation.setEasingCurve(QEasingCurve.Type.OutCubic)

    def _finish() -> None:
        """Remove the effect exactly once, only if it is still current."""
        try:
            if widget.property(_FADE_PROPERTY) is animation:
                widget.setProperty(_FADE_PROPERTY, None)
            if widget.graphicsEffect() is effect:
                _clear_effect(widget)
            animation.stop()
            animation.deleteLater()
        except RuntimeError:  # widget destroyed mid-animation (shutdown)
            pass

    animation.finished.connect(_finish)
    widget.setProperty(_FADE_PROPERTY, animation)
    widget.setGraphicsEffect(effect)
    animation.start(QAbstractAnimation.DeletionPolicy.KeepWhenStopped)
    return True
