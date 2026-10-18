"""Named single-flight background workers for the desktop shell (Stage 10).

The Stage 04/09 job system covers long-running, cancellable device work
(APP_LISTING jobs). Short blocking engine calls that the TUI surfaces as
deduped Textual workers (discovery ``adb devices`` probes, device-info
readouts, ADB executable validation) need the same discipline in Qt:

* They must NEVER run on the GUI thread (they launch a subprocess).
* A widget may not stack overlapping refreshes ("refresh" pressed twice
  must not build two concurrent ``adb devices`` invocations).
* Results must reach the GUI thread through Qt's queued-connection
  machinery — the same rule the Stage 09 ``JobEventSignalHub`` proved for
  JobManager deliveries: the emitting thread is the worker; the slot body
  runs on the GUI thread.

Mechanism (deliberately minimal — no second executor framework):

* :class:`WorkerCoordinator` owns ONE pending :class:`CallWorker` per
  stable slot name (``refresh_devices``, ``load_details``, ``check_adb``…).
* Spawning into a pending slot is refused (returns ``False``) — the caller
  keeps its control disabled instead of stacking work, exactly like the
  TUI's ``run_worker(..., exclusive=True)``.
* Each worker runs its callable in one daemon ``threading.Thread`` and
  delivers ``done``/``failed`` typed Qt signals; delivery handlers are
  disconnected right after their last delivery, so repeated refreshes
  cannot accumulate connections.
* :meth:`WorkerCoordinator.close` joins live threads briefly and reports
  them; the shell calls it in ``closeEvent`` (explicit ownership/shutdown,
  Stage 09 mission A10 rule).

Widgets must map ``failed`` payloads through
:func:`ui_desktop.widgets.engine_error_text` — no raw traceback, token, or
device output ever reaches the UI.
"""

from __future__ import annotations

import threading
from typing import Any, Callable, Optional

from PySide6.QtCore import QObject, Signal

__all__ = ["CallWorker", "WorkerCoordinator"]


class CallWorker(QObject):
    """One callable executed once on its own background thread.

    ``Result``/``Failure`` signals are emitted ON THE WORKER THREAD and Qt
    queues them for GUI-thread receivers (auto queued connection — the
    Stage 09 proven rule). Typos in payloads are impossible: the success
    payload is whatever ``func`` returned; the failure payload is the
    caught exception instance itself (tests assert the type).
    """

    finished = Signal(str, object)   # (slot, result)
    failed = Signal(str, object)     # (slot, exception)

    def __init__(self, slot: str, func: Callable[[], Any]) -> None:
        if not callable(func):
            raise ValueError("CallWorker requires a callable")
        super().__init__()
        self._slot = slot
        self._func = func
        self._thread: Optional[threading.Thread] = None

    @property
    def slot(self) -> str:
        return self._slot

    def start(self) -> None:
        """Begin execution (never imports/calls up into Qt widgets)."""
        if self._thread is not None:
            raise RuntimeError("CallWorker was already started")
        self._thread = threading.Thread(
            target=self._run, name=f"vscanner-desktop-{self._slot}",
            daemon=True)
        self._thread.start()

    def _run(self) -> None:
        try:
            result = self._func()
        except Exception as exc:  # delivered, never swallowed; never to GUI as raw traceback
            self.failed.emit(self._slot, exc)
        else:
            self.finished.emit(self._slot, result)


class WorkerCoordinator(QObject):
    """Registry of at most one pending background call per slot name.

    Delivery is a two-hop queue, mirroring the Stage 09 hub rule: the
    worker thread emits the worker signal, the bridge handlers re-emit on
    the coordinator's OWN signal, and Qt queues that emission to the
    coordinator's GUI-thread slot. A plain lambda connection is a DIRECT
    connection (no receiver QObject) — it would run the handler on the
    worker thread, so the hop is required, not cosmetic."""

    _result_ready = Signal(str, object)   # (slot, result)
    _failure_ready = Signal(str, object)  # (slot, exception)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._pending: dict[str, CallWorker] = {}
        self._live_threads: dict[str, threading.Thread] = {}
        self._handlers: dict[
            str, tuple[Callable[[Any], None], Callable[[Any], None]]] = {}
        self._close_started = False
        self._result_ready.connect(self._dispatch_done)
        self._failure_ready.connect(self._dispatch_fail)

    # -- inspection --------------------------------------------------------- #

    def is_pending(self, slot: str) -> bool:
        return slot in self._pending

    def pending_slots(self) -> tuple[str, ...]:
        return tuple(sorted(self._pending))

    # -- execution ---------------------------------------------------------- #

    def run(self, slot: str, func: Callable[[], Any],
            on_done: Callable[[Any], None],
            on_fail: Callable[[Exception], None]) -> bool:
        """Start ``func`` in a worker for ``slot`` (``False`` = slot busy).

        ``on_done``/``on_fail`` run on the GUI thread (queued through the
        coordinator's own signals); the worker connections are
        disconnected exactly once after their delivery so repeated
        refreshes cannot accumulate signal connections.
        """
        if self._close_started:
            raise RuntimeError("WorkerCoordinator is closed")
        if slot in self._pending:
            return False
        worker = CallWorker(slot, func)
        self._pending[slot] = worker
        self._handlers[slot] = (on_done, on_fail)
        worker.finished.connect(self._bridge_done)
        worker.failed.connect(self._bridge_fail)
        worker.start()
        if worker._thread is not None:  # set by start(), post-check for mypy
            self._live_threads[slot] = worker._thread
        return True

    # -- delivery (two-hop queue: worker thread → coordinator slot) --------- #

    def _bridge_done(self, slot: str, payload: Any) -> None:
        # Runs ON THE WORKER THREAD (direct connection); re-emitting the
        # coordinator's own signal is thread-safe and queues the delivery.
        self._result_ready.emit(slot, payload)

    def _bridge_fail(self, slot: str, exc: Any) -> None:
        self._failure_ready.emit(slot, exc)

    def _dispatch_done(self, slot: str, payload: Any) -> None:
        """GUI-thread delivery: retire first, then hand over the result."""
        done, fail = self._retire_take(slot)
        if done is not None:
            done(payload)

    def _dispatch_fail(self, slot: str, exc: Any) -> None:
        done, fail = self._retire_take(slot)
        if fail is not None:
            fail(exc)

    def _retire_take(self, slot: str) -> tuple[Optional[Callable[[Any], None]],
                                               Optional[Callable[[Any], None]]]:
        """Pop the slot's state; return its handlers (once, ever)."""
        self._pending.pop(slot, None)
        self._live_threads.pop(slot, None)
        return self._handlers.pop(slot, (None, None))

    # -- shutdown ----------------------------------------------------------- #

    def close(self, join_timeout: float = 2.0) -> tuple[str, ...]:
        """Stop accepting work; briefly join live worker threads.

        Returns the slot names whose threads were still running when the
        wait elapsed (the owning screen abandons their results — daemon
        threads cannot block process shutdown).
        """
        self._close_started = True
        abandoned: list[str] = []
        for slot, thread in list(self._live_threads.items()):
            if thread is not None and thread.is_alive():
                thread.join(join_timeout)
                if thread.is_alive():
                    abandoned.append(slot)
                    del self._live_threads[slot]
        self._pending.clear()
        self._handlers.clear()
        return tuple(abandoned)
