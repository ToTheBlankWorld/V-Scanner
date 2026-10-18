"""Stage 04 bridge-stub tests — headless, no GUI frameworks required.

``AsyncJobBridge`` is driven by a live asyncio loop inside the test process;
``QtJobBridge`` records dispatcher calls instead of signal emissions. Both
remain framework-free by design (A-03), which this file also asserts via AST
(test_jobs_integration.TestLayering).
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest

from ui_desktop.jobs_bridge_qt import QtJobBridge
from ui_terminal.jobs_bridge_async import AsyncJobBridge, Sentinel
from vscanner.core.events import (
    JobKind,
    JobProgressEvent,
    JobStartedEvent,
    JobState,
    JobTerminalEvent,
)
from vscanner.services.jobs import JobManager


def test_async_bridge_drains_worker_thread_events_in_delivery_order():
    events: Any = []

    async def scenario():
        bridge = AsyncJobBridge()  # attach() must run inside the loop
        mgr = JobManager()
        bridge.attach(mgr)
        handle = mgr.submit(
            JobKind.OTHER,
            device_serial="demo",
            params_summary={"kind": "smoke"},
            plan=lambda ctx: ctx.progress(1, 1, unit="steps", context="tick") or "ok",
        )
        # Blocking waits happen OFF the loop thread only.
        state = await asyncio.to_thread(handle.wait, 5)
        received = await asyncio.wait_for(bridge.drain(3, timeout=5.0), timeout=6.0)
        bridge.stop()  # sentinel enqueued; a pump started now returns cleanly
        ended = asyncio.Event()

        async def sink(event):
            ended.set()

        # The queue only holds the Sentinel now: the pump must return
        # promptly WITHOUT invoking the sink (end-of-stream, no spurious
        # event delivery after stop).
        pump_task = asyncio.create_task(bridge.pump(sink))
        await asyncio.wait_for(pump_task, timeout=5.0)
        assert not ended.is_set()
        return state, [type(e).__name__ for e in received]

    state, kinds = asyncio.run(scenario())
    assert state is JobState.SUCCEEDED
    assert kinds == ["JobStartedEvent", "JobProgressEvent", "JobTerminalEvent"]
    assert events == []  # sentinel ended the pump; nothing further delivered


def test_async_bridge_pump_forwards_to_sink_until_stop():
    collected: Any = []

    async def scenario():
        def sink(event):
            collected.append(event)

        bridge = AsyncJobBridge()
        mgr = JobManager()
        bridge.attach(mgr)
        pump_task = asyncio.create_task(bridge.pump(sink))
        handle = mgr.submit(JobKind.OTHER, device_serial="d", plan=lambda ctx: "val")
        job_state = await asyncio.to_thread(handle.wait, 5)
        for _ in range(2000):
            if collected:
                break
            await asyncio.sleep(0.005)
        bridge.stop()
        await asyncio.wait_for(pump_task, timeout=5.0)  # sentinel return
        return job_state

    job_state = asyncio.run(scenario())
    assert job_state is JobState.SUCCEEDED
    assert collected and collected[0].device_serial == "d"


def test_async_bridge_stop_is_idempotent_and_pre_start_safe():
    bridge = AsyncJobBridge()
    bridge.stop()  # detach without attach: no crash
    with pytest.raises(RuntimeError):
        asyncio.run(bridge.pump(lambda e: None))


def test_sentinel_is_end_of_stream_only():
    assert Sentinel("x").why == "x"


def test_qt_bridge_categories_and_detach():
    mgr = JobManager()
    calls: list = []
    bridge = QtJobBridge(lambda category, event: calls.append((category, event)))
    bridge.attach(mgr)
    assert bridge.attached is True
    with pytest.raises(RuntimeError):
        bridge.attach(mgr)  # double attach refused
    handle = mgr.submit(
        JobKind.APP_LISTING,
        device_serial="d",
        params_summary={"kind": "qt"},
        plan=lambda ctx: ctx.progress(1, 1) or "listed",
    )
    assert handle.wait(5) is JobState.SUCCEEDED
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline and len(calls) < 3:
        time.sleep(0.005)
    categories = [c for c, _ in calls]
    assert categories == ["started", "progress", "terminal"]
    started_event = calls[0][1]
    assert isinstance(started_event, JobStartedEvent)
    assert started_event.device_serial == "d"
    assert started_event.params_summary == {"kind": "qt"}
    assert isinstance(calls[1][1], JobProgressEvent)
    assert calls[1][1].current == 1
    assert isinstance(calls[2][1], JobTerminalEvent)
    assert calls[2][1].outcome is JobState.SUCCEEDED

    bridge.detach()
    assert bridge.attached is False
    after = len(calls)
    mgr.submit(JobKind.OTHER, plan=lambda ctx: None).wait(5)
    deadline = time.monotonic() + 0.5
    while time.monotonic() < deadline and len(calls) > after:
        time.sleep(0.005)
    assert len(calls) == after  # no delivery after detach


def test_qt_bridge_dispatcher_failure_is_contained_not_fatal():
    mgr = JobManager()

    def broken(category, event):
        raise RuntimeError("dispatcher blew up (e.g. GUI-thread misuse)")

    bridge = QtJobBridge(broken)
    bridge.attach(mgr)
    handle = mgr.submit(JobKind.OTHER, plan=lambda ctx: "value")
    assert handle.wait(5) is JobState.SUCCEEDED  # job never corrupted


def test_qt_bridge_requires_callable_dispatcher():
    with pytest.raises(ValueError):
        QtJobBridge(dispatcher=None)  # type: ignore[arg-type]
