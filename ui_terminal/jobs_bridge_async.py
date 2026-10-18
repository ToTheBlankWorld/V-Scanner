"""Async job bridge (Stage 04 stub) — Textual-side consumption seam.

ACCEPTANCE_CRITERIA Stage 04 requires a "asyncio bridge
``ui_terminal/jobs_bridge_async.py``" that is testable WITHOUT Textual being
installed — nothing here imports Textual. The real app-side pump/screens are
built in Stage 05; this adapter only defines the thread→loop marshalling.

Delivery contract (JOB_AND_EVENT_CONTRACTS §10):
* worker threads deliver :class:`JobEvent` objects synchronously via
  ``JobManager.subscribe``;
* this bridge forwards each event onto a given ``asyncio`` loop with
  ``loop.call_soon_threadsafe`` and collects them in an ``asyncio.Queue`` so
  a single consumer coroutine can iterate them on the loop's own thread;
* the bridge NEVER blocks the loop on thread joins and NEVER awaits job
  completion from the loop thread (contract §6 warns about exactly that).

Framework leakage guard: this package is not part of ``vscanner`` and the
import-lint suite additionally asserts no framework imports inside.
"""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Optional

from vscanner.core.events import JobEvent

__all__ = ["AsyncJobBridge", "Sentinel"]


class Sentinel:
    """End-of-stream marker pushed by :meth:`stop` into the queue."""

    __slots__ = ("why",)

    def __init__(self, why: str = "bridge stopped") -> None:
        self.why = why


class AsyncJobBridge:
    """Marshals ``JobEvent`` deliveries from worker threads to a loop."""

    def __init__(self, loop: Optional[asyncio.AbstractEventLoop] = None) -> None:
        self._loop = loop
        self._queue: Optional[asyncio.Queue] = None
        self._unsubscribe: Optional[Callable[[], None]] = None

    def attach(
        self,
        event_source: Any,
        queue_maxsize: int = 0,
        loop: Optional[asyncio.AbstractEventLoop] = None,
    ) -> None:
        """Subscribe to a ``JobManager``-like source (anything exposing
        ``subscribe(callback) -> unsubscribe``).

        ``queue_maxsize`` follows ``asyncio.Queue`` semantics: 0 = unbounded
        (default). Overflow/shutdown handling is the CONSUMER's documented
        concern (contract §10); the bridge only enqueues."""
        if self._unsubscribe is not None:
            raise RuntimeError("AsyncJobBridge is already attached")
        effective_loop = loop or self._loop or asyncio.get_running_loop()
        self._loop = effective_loop
        self._queue = asyncio.Queue(maxsize=queue_maxsize)
        self._unsubscribe = event_source.subscribe(self._on_event)

    def _on_event(self, event: JobEvent) -> None:
        """Runs on the emitting (worker) thread — must not block."""
        loop = self._loop
        if loop is None or self._queue is None:
            return  # detached concurrently; drop safely
        try:
            loop.call_soon_threadsafe(self._queue.put_nowait, event)
        except RuntimeError:
            # Loop closed during shutdown: the delivery is dropped, the
            # job manager's subscriber containment keeps everything else
            # intact (documented behavior; the loop's exit wins).
            pass

    def stop(self) -> None:
        """Unsubscribe and release the pump by enqueuing a sentinel."""
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None
        if self._loop is not None and self._queue is not None:
            self._loop.call_soon_threadsafe(
                self._queue.put_nowait, Sentinel("bridge stopped")
            )

    async def pump(
        self,
        sink: "Callable[[JobEvent], None] | Callable[[JobEvent], Awaitable[None]]",
    ) -> None:
        """Consume attached events forever, forwarding each to ``sink`` in
        loop-thread order (fifo defined by the enqueueing call order, which
        matches the per-job delivery order). Returns after :meth:`stop`
        releases the pump."""
        if self._queue is None:
            raise RuntimeError("AsyncJobBridge.pump before attach()")
        while True:
            item = await self._queue.get()
            if isinstance(item, Sentinel):
                self._queue.task_done()
                return
            outcome = sink(item)
            if outcome is not None and hasattr(outcome, "__await__"):
                await outcome  # type: ignore[misc]
            self._queue.task_done()

    async def drain(self, count: int, timeout: float = 5.0) -> "list[JobEvent]":
        """Test/Stage-05 convenience: await up to ``count`` real events with
        a bounded timeout (used by headless tests, never by the UI pump)."""
        if self._queue is None:
            raise RuntimeError("AsyncJobBridge.drain before attach()")
        events: "list[JobEvent]" = []
        while len(events) < count:
            item = await asyncio.wait_for(self._queue.get(), timeout=timeout)
            if isinstance(item, Sentinel):
                self._queue.task_done()
                break
            events.append(item)
            self._queue.task_done()
        return events
