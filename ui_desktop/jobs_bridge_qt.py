"""Qt job bridge — PySide6-desktop consumption seam (Stage 04 → Stage 09).

Two layers in one module:

1. **Stage 04 stub contract (framework-free).** ``QtJobBridge`` converts
   ``JobEvent`` deliveries into ``(category, event)`` dispatcher calls. The
   conversion logic — and nothing else — is testable without Qt installed
   (JOB_AND_EVENT_CONTRACTS A10: both frontends' bridges convert identical
   ``JobEvent`` objects; no event type is UI-only).

2. **Stage 09 signal layer (Qt, when available).** ``JobEventSignalHub``
   exposes one typed ``Signal`` per ``event_category()`` value, and
   ``QtJobEventBridge`` attaches the stub to a ``JobManager``-like source so
   engine events reach GUI-thread slots through Qt's auto queued connection.

Thread rule (ACCEPTANCE_CRITERIA Stage 09): ``JobManager`` delivers events
on its worker threads. Consumers must connect receivers that live on the
GUI thread — a signal emitted from a worker thread into a GUI-thread
receiver is then queued by Qt, so the slot body runs on the GUI thread
(asserted by the Stage 09 integration test). Widgets must never be touched
directly from a worker thread. This bridge is delivery-only: it creates no
worker threads, no timers, and no new job manager — real device jobs are
submitted by later stages through the existing Stage 04 system.

Ownership/shutdown: the bridge must be detached by its owner (the shell
detaches it in ``closeEvent``); nothing outlives the object holding it.
"""

from __future__ import annotations

import threading
from typing import Any, Callable, Optional

from vscanner.core.events import JobEvent, event_category

__all__ = ["QtJobBridge", "SignalDispatcher", "QT_AVAILABLE",
           "JobEventSignalHub", "QtJobEventBridge"]

# A dispatcher receives (category, event) pairs. Stage 09 registers
# ``JobEventSignalHub.deliver`` as the dispatcher (see ``QtJobEventBridge``).
SignalDispatcher = Callable[[str, JobEvent], None]


class QtJobBridge:
    """Forwards ``JobEvent`` deliveries to an injected signal dispatcher.

    Thread note: ``JobManager`` delivers events on its worker threads; the
    Qt layer marshals onto the GUI thread *inside the Qt objects* (queued
    signal emission). This class itself performs no cross-thread plumbing.
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


# ---------------------------------------------------------------------------
# Stage 09 Qt layer (built when the desktop dependency is installed)
# ---------------------------------------------------------------------------

try:
    from PySide6.QtCore import QObject, Signal

    QT_AVAILABLE = True
except ImportError:  # engine-only install: the stub layer stays usable
    QT_AVAILABLE = False


if QT_AVAILABLE:  # pragma: no branch (each variant is exercised per env)

    class JobEventSignalHub(QObject):
        """Typed Qt signals for every ``event_category()`` value (A10).

        Categories: ``started | progress | log | finding | snapshot |
        terminal`` — plus an ``any_event`` catch-all. Signals carry the
        frozen ``JobEvent`` object itself; nothing is re-invented at this
        boundary, so no event type can drift out of the shared contract.
        """

        started = Signal(object)
        progress = Signal(object)
        log = Signal(object)
        finding = Signal(object)
        snapshot = Signal(object)
        terminal = Signal(object)
        any_event = Signal(object)

        _CATEGORIES = ("started", "progress", "log", "finding",
                       "snapshot", "terminal")

        def signal_for(self, category: str) -> Optional[Signal]:
            """The typed signal for a category (``None`` when unknown)."""
            return getattr(self, category) if category in self._CATEGORIES \
                else None

        def deliver(self, category: str, event: JobEvent) -> None:
            """Emit on the typed signal (unknown category → catch-all only,
            never silently swallowed, never re-marshalled to a fake type)."""
            if category not in self._CATEGORIES:
                raise ValueError(f"unknown job event category: {category!r}")
            signal = getattr(self, category)
            signal.emit(event)
            self.any_event.emit(event)

    class QtJobEventBridge:
        """Attachable facade: JobManager events → GUI-thread Qt slots.

        - ``attach(manager)`` subscribes (Stage 04 stub does the plumbing).
        - Every delivery is traced ``(category, producing-thread-id)`` so
          tests can verify the marshal rule without screenshots.
        - ``detach()`` unsubscribes exactly once; the owner calls it on
          window close.
        """

        def __init__(self) -> None:
            if not QT_AVAILABLE:
                raise RuntimeError(
                    "PySide6 is not installed — install the 'desktop' extra "
                    "(pip install -e .[desktop])")
            self.hub = JobEventSignalHub()
            self._trace: list[tuple[str, int]] = []
            self._trace_lock = threading.Lock()
            self._core = QtJobBridge(self._dispatch)

        @property
        def attached(self) -> bool:
            return self._core.attached

        def attach(self, event_source: Any) -> None:
            self._core.attach(event_source)

        def detach(self) -> None:
            self._core.detach()

        def trace(self) -> list[tuple[str, int]]:
            """Snapshot of ``(category, producing thread id)`` deliveries."""
            with self._trace_lock:
                return list(self._trace)

        def clear_trace(self) -> None:
            with self._trace_lock:
                self._trace.clear()

        # -- dispatch (worker thread) ------------------------------------ #

        def _dispatch(self, category: str, event: JobEvent) -> None:
            with self._trace_lock:
                self._trace.append((category, threading.get_ident()))
            self.hub.deliver(category, event)
