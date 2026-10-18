"""Qt job bridge (Stage 04 stub) — PySide6-desktop consumption seam.

ACCEPTANCE_CRITERIA Stage 04 requires a "Qt-bridge prototype module
``ui_desktop/jobs_bridge_qt.py`` stub (non-UI-binding testable)" — nothing
here imports PySide6 (it may not even be installed; ARCHITECTURE_DECISIONS
A-03 keeps GUI frameworks out of the shared engine). The real ``QObject``
subclass with typed signals and the ``QMetaObject.invokeMethod(...,
Qt.QueuedConnection)`` GUI-thread marshalling is built in Stage 09 on top of
this module.

Stage 04 contract (JOB_AND_EVENT_CONTRACTS §10): both bridges convert
identical ``JobEvent`` objects; no event type is UI-only. The dispatcher
injection point is where the Stage 09 implementation will attach its signal
emissions, so the marshalling logic (event → category → payload) is already
testable without Qt.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from vscanner.core.events import JobEvent, event_category

__all__ = ["QtJobBridge", "SignalDispatcher"]

# A dispatcher receives (category, event) pairs — Stage 09 wires this onto
# typed QObject signals, e.g.:
#   dispatcher = lambda category, event: (
#       self.progress_signal.emit(event) if category == "progress" else ...)
SignalDispatcher = Callable[[str, JobEvent], None]


class QtJobBridge:
    """Forwards ``JobEvent`` deliveries to an injected signal dispatcher.

    Thread note for Stage 09: ``JobManager`` delivers events on its worker
    threads; the Qt layer MUST marshal onto the GUI thread (queued
    connection) inside its dispatcher — this stub documents and preserves
    that rule without importing Qt.
    """

    def __init__(self, dispatcher: SignalDispatcher) -> None:
        if not callable(dispatcher):
            raise ValueError("QtJobBridge requires a callable dispatcher")
        self._dispatcher = dispatcher
        self._unsubscribe: Optional[Callable[[], None]] = None
        self._attached = False

    @property
    def attached(self) -> bool:
        return self._attached

    def attach(self, event_source: Any) -> None:
        """Subscribe to a ``JobManager``-like ``subscribe`` source."""
        if self._attached:
            raise RuntimeError("QtJobBridge is already attached")
        self._unsubscribe = event_source.subscribe(self._on_event)
        self._attached = True

    def detach(self) -> None:
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None
        self._attached = False

    def _on_event(self, event: JobEvent) -> None:
        """Runs on the emitting (worker) thread. Exceptions propagate to the
        manager's subscriber containment (one broken UI subscriber never
        corrupts job state — contract §5 delivery requirements)."""
        self._dispatcher(event_category(event), event)
