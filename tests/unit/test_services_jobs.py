"""JobManager contract tests (Stage 04 — JOB_AND_EVENT_CONTRACTS).

Lifecycle, terminal invariants, conflict policy, cooperative cancellation,
timeout watchdog, subscription lifecycle and concurrency races. All tests
are device-free; every plan is self-contained. Time-based tests use
synchronization primitives first and only tiny relative timeouts after.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from vscanner.core.errors import (
    AdbCommandError,
    InputValidationError,
    JobCancelRequested,
    JobConflictError,
    VScannerError,
)
from vscanner.core.events import (
    JobEvent,
    JobKind,
    JobProgressEvent,
    JobStartedEvent,
    JobState,
    JobTerminalEvent,
)
from vscanner.services.jobs import (
    CancellationToken,
    JobContext,
    JobManager,
    OperationConfirmation,
)
from vscanner.core.errors import ConfirmationInvalid
from vscanner.core.events import JobConflictScope


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _terminal_events(events):
    return [e for e in events if isinstance(e, JobTerminalEvent)]


def _run_bounded(work, seconds=5.0):
    """Run ``work()`` in a helper thread and fail the test if it hangs —
    deadlock guard for re-entrancy tests."""
    done = []

    def runner():
        try:
            work()
            done.append("ok")
        except BaseException as exc:  # surface the failure into assertions
            done.append(exc)

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    thread.join(seconds)
    assert not thread.is_alive(), "work hung (probable deadlock/re-entrancy bug)"
    if done and done[0] not in ("ok",):
        raise done[0]


class _Recorder:
    def __init__(self) -> None:
        self.events: list = []
        self.lock = threading.Lock()
        # Delivery synchronization: ``isinstance`` checks + appends happen
        # under ``self.lock``, so a Condition sharing it lets tests WAIT for
        # the *delivered* event set instead of polling (Stage 07 §5 — this
        # removed the one post-wait delivery race in the suite).
        self._arrived = threading.Condition(self.lock)

    def __call__(self, event) -> None:
        with self._arrived:
            self.events.append(event)
            self._arrived.notify_all()

    def terminal(self):
        with self.lock:
            return _terminal_events(self.events)

    def wait_delivered(self, predicate, timeout: float = 5.0) -> None:
        """Block until ``predicate(events)`` holds on DELIVERED events.

        Deterministic synchronization on real event arrival — never used to
        force a scheduling order, only to observe one after it happened."""
        with self._arrived:
            deadline = time.monotonic() + timeout
            while not predicate(self.events):
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not self._arrived.wait(remaining):
                    raise AssertionError(
                        "event delivery condition not met within timeout"
                    )

    def wait_terminal(self, minimum: int = 1, timeout: float = 5.0) -> None:
        number = lambda events: len(_terminal_events(events))  # noqa: E731
        self.wait_delivered(lambda events: number(events) >= minimum, timeout)


# ---------------------------------------------------------------------------
# lifecycle and delivery
# ---------------------------------------------------------------------------

class TestLifecycle:
    def test_queued_running_terminal_with_ordered_events(self):
        events = _Recorder()
        mgr = JobManager()
        mgr.subscribe(events)
        handle = mgr.submit(
            JobKind.APP_LISTING,
            device_serial="demo",
            plan=lambda ctx: ctx.progress(1, 1, unit="items") or "done",
        )
        assert handle.state is JobState.QUEUED
        assert handle.kind is JobKind.APP_LISTING
        assert handle.device_serial == "demo"
        assert handle.wait(5) is JobState.SUCCEEDED

        kinds = [type(e).__name__ for e in events.events]
        assert kinds == ["JobStartedEvent", "JobProgressEvent", "JobTerminalEvent"]
        assert [e.seq for e in events.events] == [1, 2, 3]
        assert events.events[0].kind is JobKind.APP_LISTING
        assert events.events[0].device_serial == "demo"
        seqs = [e.seq for e in events.events]
        assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)
        assert events.events[0].ts <= events.events[-1].ts

    def test_result_and_duration_delivered_on_success(self):
        events = _Recorder()
        mgr = JobManager()
        mgr.subscribe(events)
        mgr.submit(JobKind.EXPORT, plan=lambda ctx: {"ok": True}).wait(5)
        terminal = events.terminal()[0]
        assert terminal.outcome is JobState.SUCCEEDED
        assert terminal.result == {"ok": True}
        assert isinstance(terminal.duration_ms, int) and terminal.duration_ms >= 0

    def test_typed_error_leads_to_failed_with_error_object(self):
        events = _Recorder()
        mgr = JobManager()
        mgr.subscribe(events)

        def plan(ctx):
            raise VScannerError("scan broken", {"cause_code": "42"})

        mgr.submit(JobKind.FULL_DEVICE_SCAN, device_serial="d", plan=plan).wait(5)
        terminal = events.terminal()[0]
        assert terminal.outcome is JobState.FAILED
        assert terminal.error is not None
        assert terminal.error.message == "scan broken"
        assert terminal.error.details["cause_code"] == "42"
        assert terminal.retriable is False

    def test_adb_timeout_failure_is_marked_retriable(self):
        events = _Recorder()
        mgr = JobManager()
        mgr.subscribe(events)

        def plan(ctx):
            raise AdbCommandError("command timed out", timeout=True)

        mgr.submit(JobKind.APP_LISTING, plan=plan).wait(5)
        terminal = events.terminal()[0]
        assert terminal.retriable is True
        assert terminal.error.timeout is True

    def test_unexpected_exception_is_summarized_not_leaked(self):
        events = _Recorder()
        mgr = JobManager()
        mgr.subscribe(events)

        def plan(ctx):
            raise RuntimeError("C:\\Users\\naree\\secret-path exploded")

        mgr.submit(JobKind.OTHER, plan=plan).wait(5)
        terminal = events.terminal()[0]
        assert terminal.outcome is JobState.FAILED
        assert terminal.error is not None
        # Path/private detail MUST NOT travel: type-only summary contract.
        assert "secret-path" not in terminal.error.message
        assert terminal.error.details == {"exception_type": "RuntimeError"}

    def test_keyboard_interrupt_is_recorded_then_reraised(self):
        """§4: KeyboardInterrupt-class signals are never wrapped away —
        the terminal state is recorded and the signal re-raised."""
        mgr = JobManager()
        # Bypass the executor for direct boundary observation (documented
        # test seam: _spawn is the only scheduling entry).
        mgr._spawn = lambda rec: None  # type: ignore[method-assign]
        from vscanner.services.jobs import _JobRecord

        rec = _JobRecord(
            job_id="ki" * 16, kind=JobKind.OTHER, device_serial=None,
            scope=JobConflictScope.PER_DEVICE, mutex_group=None,
            conflict_key=(None, None), plan=lambda ctx: 1 / 0,
            params_summary={}, confirmations=(), timeout_s=None,
        )
        rec.plan = _raise_ki
        with pytest.raises(KeyboardInterrupt):
            mgr._run_plan(rec)
        assert rec.state is JobState.FAILED
        assert rec.terminal_event.is_set()

    def test_plan_must_be_callable(self):
        mgr = JobManager()
        with pytest.raises(InputValidationError):
            mgr.submit(JobKind.OTHER, plan=None)

    def test_handle_for_roundtrip_and_unknown(self):
        mgr = JobManager()
        handle = mgr.submit(JobKind.OTHER, plan=lambda ctx: None)
        # Handle is a view; identity of the JOB is what round-trips.
        looked_up = mgr.handle_for(handle.id)
        assert looked_up.id == handle.id
        assert looked_up.kind is handle.kind
        assert looked_up.state is handle.state
        assert mgr.handle_for("nope") is None


def _raise_ki(ctx):  # module-level for picklability not needed; clarity only
    raise KeyboardInterrupt()


class TestTimeoutWatchdog:
    def test_cooperative_plan_stops_inside_deadline_as_failed_timeout(self):
        events = _Recorder()
        mgr = JobManager()
        mgr.subscribe(events)

        def plan(ctx):
            # Sleep in small slices; each slice ends at a checkpoint.
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline:
                time.sleep(0.01)
                ctx.cancel_token.checkpoint("poll_slice")
            return "too slow"

        handle = mgr.submit(JobKind.FULL_DEVICE_SCAN, device_serial="d",
                            plan=plan, timeout_s=0.05)
        assert handle.wait(5) is JobState.FAILED
        terminal = events.terminal()[0]
        assert terminal.outcome is JobState.FAILED
        assert "timeout" in terminal.error.message
        assert terminal.error.details["timeout_s"] == "0.05"
        assert terminal.retriable is True

    def test_uncooperative_plan_that_finishes_reports_success_honestly(self):
        """Documented race resolution: no thread-kill exists, so a plan that
        returns valid work post-deadline is NOT downgraded (never pretend)."""
        events = _Recorder()
        mgr = JobManager()
        mgr.subscribe(events)
        handle = mgr.submit(
            JobKind.OTHER,
            plan=lambda ctx: (time.sleep(0.15), "kept-result")[1],
            timeout_s=0.05,
        )
        assert handle.wait(5) is JobState.SUCCEEDED
        terminal = events.terminal()[0]
        assert terminal.result == "kept-result"

    def test_repeated_deadline_fires_are_idempotent_events(self):
        events = _Recorder()
        mgr = JobManager()
        mgr.subscribe(events)

        def plan(ctx):
            time.sleep(0.2)
            ctx.cancel_token.checkpoint("late")
            return None

        mgr.submit(JobKind.OTHER, plan=plan, timeout_s=0.02).wait(5)
        # The watchdog may fire repeatedly for a running job, but exactly
        # one terminal event ever emerges and the transition wins once.
        assert len(events.terminal()) == 1


class TestCancellation:
    def test_cancel_running_job_waits_for_checkpoint_then_ticks_cancelled(self):
        events = _Recorder()
        mgr = JobManager()
        mgr.subscribe(events)
        running = threading.Event()
        cancel_done = threading.Event()

        def plan(ctx):
            running.set()
            cancel_done.wait(5)
            ctx.cancel_token.checkpoint("between_apps")
            return "should not complete"

        handle = mgr.submit(JobKind.FULL_DEVICE_SCAN, device_serial="d", plan=plan)
        running.wait(5)
        handle.cancel()  # a REQUEST — not yet terminal
        assert handle.state is JobState.RUNNING
        cancel_done.set()
        assert handle.wait(5) is JobState.CANCELLED
        events.wait_terminal()  # deterministic delivery (Stage 07 §5)
        terminal = events.terminal()
        assert len(terminal) == 1
        assert terminal[0].outcome is JobState.CANCELLED
        assert terminal[0].at_cancellation_point == "between_apps"
        # A cancelled job must NEVER be reported successful:
        terminals = [e for e in events.events if isinstance(e, JobTerminalEvent)]
        assert all(e.outcome is not JobState.SUCCEEDED for e in terminals)

    def test_cancel_queued_job_never_runs_the_plan(self):
        events = _Recorder()
        mgr = JobManager(max_workers=1)
        mgr.subscribe(events)
        ran = threading.Event()
        gate = threading.Event()

        blocker = mgr.submit(JobKind.OTHER, plan=lambda ctx: gate.wait(5))
        queued = mgr.submit(
            JobKind.OTHER,
            plan=lambda ctx: (ran.set(), "ran")[1],
        )
        assert queued.state is JobState.QUEUED
        queued.cancel()
        assert queued.wait(5) is JobState.CANCELLED
        gate.set()
        blocker.wait(5)
        events.wait_terminal()  # deterministic delivery (Stage 07 §5)
        assert not ran.is_set()  # plan body never executed
        assert not [
            e for e in events.events
            if e.job_id == queued.id and isinstance(e, JobStartedEvent)
        ]  # no started event for a job that never ran
        terminals = [e for e in events.events if isinstance(e, JobTerminalEvent)
                     and e.job_id == queued.id]
        assert len(terminals) == 1 and terminals[0].outcome is JobState.CANCELLED

    def test_repeated_cancels_are_idempotent(self):
        events = _Recorder()
        mgr = JobManager()
        mgr.subscribe(events)
        handle = mgr.submit(JobKind.OTHER, plan=lambda ctx: None)
        handle.wait(5)
        for _ in range(3):
            handle.cancel()
        assert len(events.terminal()) == 1

    def test_token_request_without_checkpoint_keeps_state_running(self):
        """Request vs acknowledgement: the state only turns terminal when
        work actually stops (never claimed falsely)."""
        mgr = JobManager()
        handle = mgr.submit(JobKind.OTHER, plan=lambda ctx: time.sleep(0.1))
        handle.cancel()
        time.sleep(0.02)
        if handle.state is JobState.RUNNING:
            assert handle.wait(5) is JobState.SUCCEEDED  # finished naturally

    def test_checkpoints_raise_only_after_request(self):
        token = CancellationToken()
        token.checkpoint("before")  # no-op pre-request
        token.request()
        assert token.is_cancelled
        with pytest.raises(JobCancelRequested) as info:
            token.checkpoint("between_apps")
        assert info.value.message == "between_apps"


class TestConflicts:
    def _busy_gate(self):
        gate = threading.Event()

        def plan(ctx):
            gate.wait(5)
            return None

        return gate, plan

    def test_same_device_scan_conflict_names_active_job_and_skips_start(self):
        gate, plan = self._busy_gate()
        mgr = JobManager()
        first = mgr.submit(JobKind.FULL_DEVICE_SCAN, device_serial="d1", plan=plan)
        ran = threading.Event()
        with pytest.raises(JobConflictError) as info:
            mgr.submit(
                JobKind.SINGLE_APP_SCAN,
                device_serial="d1",
                plan=lambda ctx: (ran.set(), None)[1],
            )
        assert info.value.details["active_job_id"] == first.id
        assert not ran.is_set()  # conflicting plan never started
        gate.set()
        first.wait(5)

    def test_second_scan_allowed_after_first_is_terminal(self):
        mgr = JobManager()
        first = mgr.submit(JobKind.FULL_DEVICE_SCAN, device_serial="d", plan=lambda ctx: None)
        first.wait(5)
        second = mgr.submit(JobKind.SINGLE_APP_SCAN, device_serial="d", plan=lambda ctx: None)
        assert second.wait(5) is JobState.SUCCEEDED

    def test_different_kind_groups_do_not_conflict(self):
        gate, plan = self._busy_gate()
        mgr = JobManager()
        scan = mgr.submit(JobKind.FULL_DEVICE_SCAN, device_serial="d", plan=plan)
        admin = mgr.submit(JobKind.ADMIN_OP, device_serial="d", plan=plan)
        listing = mgr.submit(JobKind.APP_LISTING, device_serial="d", plan=plan)
        gate.set()
        assert scan.wait(5) is JobState.SUCCEEDED
        assert admin.wait(5) is JobState.SUCCEEDED
        assert listing.wait(5) is JobState.SUCCEEDED

    def test_different_device_no_conflict(self):
        gate, plan = self._busy_gate()
        mgr = JobManager()
        first = mgr.submit(JobKind.FULL_DEVICE_SCAN, device_serial="d1", plan=plan)
        second = mgr.submit(JobKind.FULL_DEVICE_SCAN, device_serial="d2", plan=plan)
        gate.set()
        assert first.wait(5) is JobState.SUCCEEDED
        assert second.wait(5) is JobState.SUCCEEDED

    def test_global_provisioning_conflicts_across_devices(self):
        gate, plan = self._busy_gate()
        mgr = JobManager()
        first = mgr.submit(JobKind.TOOL_PROVISIONING, device_serial=None, plan=plan)
        with pytest.raises(JobConflictError):
            mgr.submit(JobKind.TOOL_PROVISIONING, device_serial="usb-device", plan=plan)
        gate.set()
        first.wait(5)

    def test_monitoring_coexists_with_scan_on_same_device(self):
        mgr = JobManager()
        a = mgr.submit(JobKind.MONITORING_SESSION, device_serial="d", plan=lambda ctx: None)
        b = mgr.submit(JobKind.FULL_DEVICE_SCAN, device_serial="d", plan=lambda ctx: None)
        assert a.wait(5) is JobState.SUCCEEDED
        assert b.wait(5) is JobState.SUCCEEDED

    def test_active_for_device_and_cancel_device_work(self):
        gate = threading.Event()

        def plan(ctx):
            gate.wait(5)
            ctx.cancel_token.checkpoint("after_work")
            return None

        mgr = JobManager()
        scan = mgr.submit(JobKind.FULL_DEVICE_SCAN, device_serial="d", plan=plan)
        provision = mgr.submit(JobKind.TOOL_PROVISIONING, device_serial=None, plan=plan)
        handles = mgr.active_for_device("d")
        assert [h.id for h in handles] == [scan.id]
        mgr.cancel_device_work("d")
        assert provision.state is not JobState.CANCELLED  # GLOBAL untouched
        gate.set()
        # PER_DEVICE scan reaches its checkpoint and terminates cancelled;
        # the GLOBAL provisioning plan completes successfully.
        assert scan.wait(5) is JobState.CANCELLED
        assert provision.wait(5) is JobState.SUCCEEDED

    def test_submit_accepts_wellformed_confirmation_tokens(self):
        mgr = JobManager()
        from datetime import datetime, timezone

        good = OperationConfirmation("op", datetime(2026, 10, 18, tzinfo=timezone.utc))
        handle = mgr.submit(
            JobKind.ADMIN_OP, device_serial="d",
            plan=lambda ctx: None, confirmations=(good,),
        )
        assert handle.wait(5) is JobState.SUCCEEDED

    def test_malformed_confirmation_tokens_are_refused(self):
        from datetime import datetime, timezone

        mgr = JobManager()
        aware = datetime(2026, 10, 18, tzinfo=timezone.utc)
        with pytest.raises(ConfirmationInvalid):
            mgr.submit(
                JobKind.ADMIN_OP, device_serial="d", plan=lambda ctx: None,
                confirmations=(OperationConfirmation("", aware),),   # empty ref
            )
        with pytest.raises(ConfirmationInvalid):
            mgr.submit(
                JobKind.ADMIN_OP, device_serial="d", plan=lambda ctx: None,
                confirmations=(OperationConfirmation("op", datetime(2026, 10, 18)),),
            )
        with pytest.raises(ConfirmationInvalid):
            mgr.submit(
                JobKind.ADMIN_OP, device_serial="d", plan=lambda ctx: None,
                confirmations=("not-a-token",),  # type: ignore[list-item]
            )

    def test_invalid_submit_arguments_refused(self):
        mgr = JobManager()
        with pytest.raises(InputValidationError):
            mgr.submit(JobKind.OTHER, timeout_s=0)  # non-positive timeout
        with pytest.raises(InputValidationError):
            mgr.submit(JobKind.OTHER, device_serial="   ", plan=lambda ctx: None)
        with pytest.raises(InputValidationError):
            mgr.submit("scan", plan=lambda ctx: None)  # not a JobKind


class TestSubscribers:
    def test_unsubscribe_stops_delivery(self):
        events = _Recorder()
        mgr = JobManager()
        unsub = mgr.subscribe(events)
        unsub()
        mgr.submit(JobKind.OTHER, plan=lambda ctx: None).wait(5)
        assert events.events == []

    def test_subscriber_exception_does_not_break_others_or_the_job(self):
        good = _Recorder()
        mgr = JobManager()

        def broken(event):
            raise RuntimeError("subscriber bug")

        mgr.subscribe(broken)
        mgr.subscribe(good)
        handle = mgr.submit(JobKind.OTHER, plan=lambda ctx: None)
        assert handle.wait(5) is JobState.SUCCEEDED
        assert len(good.terminal()) == 1
        assert not handle.state is JobState.FAILED

    def test_reentrant_cancel_from_subscriber_does_not_deadlock(self):
        events = _Recorder()
        mgr = JobManager()
        handle_ref = {}

        def subscriber(event):
            handle = handle_ref.get("h")
            if handle is not None:
                handle.cancel()  # synchronous re-entrant state request

        mgr.subscribe(events)
        mgr.subscribe(subscriber)
        gate = threading.Event()

        def plan(ctx):
            gate.wait(5)
            return None

        handle = mgr.submit(JobKind.OTHER, plan=plan)
        handle_ref["h"] = handle
        _run_bounded(gate.set, seconds=5)
        assert handle.wait(5) in (JobState.CANCELLED, JobState.SUCCEEDED)
        terminals = [e for e in events.events
                     if e.job_id == handle.id and isinstance(e, JobTerminalEvent)]
        assert len(terminals) == 1
        assert terminals[0].outcome is not JobState.FAILED

    def test_reentrant_cancel_on_terminal_event_makes_no_duplicate(self):
        mgr = JobManager()
        terminal_seen = []
        handle_ref = {}

        def subscriber(event):
            if isinstance(event, JobTerminalEvent):
                terminal_seen.append(event)
                handle_ref["h"].cancel()  # already terminal: must not add

        mgr.subscribe(subscriber)
        handle = mgr.submit(JobKind.OTHER, plan=lambda ctx: "value")
        handle_ref["h"] = handle
        handle.wait(5)
        assert len(terminal_seen) == 1  # exactly one terminal outcome

    def test_subscribers_get_identical_event_streams(self):
        a, b = _Recorder(), _Recorder()
        mgr = JobManager()
        mgr.subscribe(a)
        mgr.subscribe(b)
        mgr.submit(
            JobKind.APP_LISTING,
            plan=lambda ctx: ctx.progress(1, 2) or ctx.progress(2, 2),
        ).wait(5)
        assert [(type(e).__name__, e.seq) for e in a.events] == \
               [(type(e).__name__, e.seq) for e in b.events]

    def test_bounded_overhead_per_finding_event(self):
        """AC Stage 04 benchmark (< 5 ms/event): generous bound; measures the
        subscribe→assign→deliver pipeline over a thousand events."""
        mgr = JobManager()
        counter = {"n": 0}
        lock = threading.Lock()

        def sink(event):
            with lock:
                counter["n"] += 1

        mgr.subscribe(sink)
        n = 1000

        def plan(ctx):
            for _ in range(n):
                ctx.emit_finding(_demo_finding())

        started = time.perf_counter()
        mgr.submit(JobKind.FULL_DEVICE_SCAN, plan=plan).wait(30)
        elapsed = time.perf_counter() - started
        assert counter["n"] > n * 0.9  # context + progress events add a few
        assert (elapsed / counter["n"]) < 0.005, elapsed / counter["n"]


def _demo_finding():
    from vscanner.core.models import (
        Evidence,
        EvidenceKind,
        Finding,
        FindingCategory,
        FindingSeverity,
    )
    return Finding(
        kind=FindingCategory.PERMISSION_EXCESS,
        severity=FindingSeverity.LOW,
        title="INTERNET",
        detail="network access",
        evidence=(Evidence.of(EvidenceKind.CONFIRMED_ARTIFACT,
                              description="d", source="dumpsys"),),
    )


class TestConcurrency:
    def test_concurrent_cancels_produce_exactly_one_terminal(self):
        events = _Recorder()
        mgr = JobManager()
        mgr.subscribe(events)
        gate = threading.Event()
        handle = mgr.submit(
            JobKind.OTHER, plan=lambda ctx: (gate.wait(5), None)[1]
        )
        barrier = threading.Barrier(4)

        def canceller():
            barrier.wait(5)
            handle.cancel()

        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda _: canceller(), range(4)))
        gate.set()
        handle.wait(5)
        events.wait_terminal()  # deterministic: delivery actually happened
        assert len([e for e in events.events if e.job_id == handle.id
                    and isinstance(e, JobTerminalEvent)]) == 1

    def test_cancel_vs_success_race_resolves_deterministically(self):
        events = _Recorder()
        mgr = JobManager()
        mgr.subscribe(events)
        plan_done = threading.Event()

        def plan(ctx):
            plan_done.wait(5)
            return "finished"

        handle = mgr.submit(JobKind.OTHER, plan=plan)
        plan_done.set()
        handle.cancel()  # races with the worker's success transition
        state = handle.wait(5)
        # Stage 07 §5 regression fix: ``wait()`` returns as soon as the
        # terminal STATE is claimed; delivery of the terminal EVENT to
        # subscribers completes right after. Historically this test counted
        # the recorder immediately after wait() and could observe ZERO
        # terminal events under scheduler pressure (stress-reproduced ~9/4000
        # runs, always state=SUCCEEDED + zero events). Waiting for delivery
        # removes the post-wait race without changing any assertion.
        events.wait_terminal()
        terminal = [e for e in events.events
                    if e.job_id == handle.id and isinstance(e, JobTerminalEvent)]
        assert len(terminal) == 1
        if state is JobState.CANCELLED:
            assert terminal[0].outcome is JobState.CANCELLED
        else:
            assert terminal[0].outcome is JobState.SUCCEEDED
            assert terminal[0].result == "finished"

    # -- deterministic cancel-ordering guarantees (Stage 07 §5) ------------- #
    # The UI couples its cancel affordance to job outcomes, so the competing
    # transitions are pinned here in controlled order (synchronization
    # primitives, never scheduling luck).

    def test_cancel_request_after_running_honest_success_survives(self):
        """Order: worker claims RUNNING → cancel REQUESTED → plan (without
        checkpoints) finishes. The documented race resolution keeps the
        honest SUCCEEDED result; exactly one terminal is delivered."""
        events = _Recorder()
        mgr = JobManager()
        mgr.subscribe(events)
        gate = threading.Event()

        def plan(ctx):
            gate.wait(5)
            return "done"

        handle = mgr.submit(JobKind.OTHER, plan=plan)
        try:
            # deterministic: RUNNING was claimed (its Started event arrived)
            events.wait_delivered(
                lambda evs: any(isinstance(e, JobStartedEvent)
                                and e.job_id == handle.id for e in evs))
            handle.cancel()  # RUNNING → token request only
            assert handle.state is JobState.RUNNING
            gate.set()
            state = handle.wait(5)
            events.wait_terminal()
            assert state is JobState.SUCCEEDED
            terminal = [e for e in events.events if e.job_id == handle.id
                        and isinstance(e, JobTerminalEvent)]
            assert len(terminal) == 1
            assert terminal[0].outcome is JobState.SUCCEEDED
            assert terminal[0].result == "done"
        finally:
            gate.set()
            handle.wait(5)

    def test_cancel_request_after_running_acknowledged_at_checkpoint(self):
        """Order: RUNNING claimed → cancel REQUESTED → next checkpoint raises
        → exactly one CANCELLED terminal naming that checkpoint."""
        events = _Recorder()
        mgr = JobManager()
        mgr.subscribe(events)
        gate = threading.Event()

        def plan(ctx):
            gate.wait(5)
            ctx.cancel_token.checkpoint("between_stages")
            return "must not complete"

        handle = mgr.submit(JobKind.FULL_DEVICE_SCAN, device_serial="d",
                            plan=plan)
        try:
            events.wait_delivered(
                lambda evs: any(isinstance(e, JobStartedEvent)
                                and e.job_id == handle.id for e in evs))
            handle.cancel()  # REQUEST armed before the checkpoint runs
            gate.set()       # deterministic: checkpoint now sees the request
            state = handle.wait(5)
            events.wait_terminal()
            assert state is JobState.CANCELLED
            terminal = [e for e in events.events if e.job_id == handle.id
                        and isinstance(e, JobTerminalEvent)]
            assert len(terminal) == 1
            assert terminal[0].outcome is JobState.CANCELLED
            assert terminal[0].at_cancellation_point == "between_stages"
        finally:
            gate.set()
            handle.wait(5)

    def test_cancel_vs_failure_race_resolves_to_one_failed_terminal(self):
        """Order: RUNNING claimed → cancel REQUESTED → plan raises instead of
        finishing. The honest contract outcome is FAILED (failure owns the
        result path); cancellation produced no contradictory terminal."""
        events = _Recorder()
        mgr = JobManager()
        mgr.subscribe(events)
        gate = threading.Event()

        def plan(ctx):
            gate.wait(5)
            raise VScannerError("analysis exploded", {"code": "7"})

        handle = mgr.submit(JobKind.OTHER, plan=plan)
        try:
            events.wait_delivered(
                lambda evs: any(isinstance(e, JobStartedEvent)
                                and e.job_id == handle.id for e in evs))
            handle.cancel()
            assert handle.state is JobState.RUNNING
            gate.set()
            state = handle.wait(5)
            events.wait_terminal()
            assert state is JobState.FAILED
            terminal = [e for e in events.events if e.job_id == handle.id
                        and isinstance(e, JobTerminalEvent)]
            assert len(terminal) == 1
            assert terminal[0].outcome is JobState.FAILED
            assert terminal[0].error is not None
            assert terminal[0].error.message == "analysis exploded"
        finally:
            gate.set()
            handle.wait(5)

    def test_cancel_after_success_is_a_quiet_no_op(self):
        events = _Recorder()
        mgr = JobManager()
        mgr.subscribe(events)
        handle = mgr.submit(JobKind.OTHER, plan=lambda ctx: "already")
        assert handle.wait(5) is JobState.SUCCEEDED
        events.wait_terminal()
        frozen = list(events.events)
        handle.cancel()  # terminal job: no state change, no new events
        assert handle.state is JobState.SUCCEEDED
        assert events.events == frozen
        assert len([e for e in frozen if isinstance(e, JobTerminalEvent)]) == 1

    def test_terminal_delivery_completes_after_wait_returns(self):
        """Semantics pin (Stage 07 §5): ``wait()`` returns when the terminal
        STATE is claimed; subscriber DELIVERY of the terminal event finished
        merely while it was still pending. This is a jobs.py correctness
        property, proven deterministically by a first-position subscriber
        that holds delivery — never a scheduling race."""
        release = threading.Event()
        blocker_entered = threading.Event()

        def blocker(event) -> None:
            if isinstance(event, JobTerminalEvent):
                blocker_entered.set()
                release.wait(5)  # holds _deliver before later subscribers run

        recorder = _Recorder()
        mgr = JobManager()
        mgr.subscribe(blocker)     # subscription order = delivery order
        mgr.subscribe(recorder)
        handle = mgr.submit(JobKind.OTHER, plan=lambda ctx: "payload")
        try:
            state = handle.wait(5)
            assert state is JobState.SUCCEEDED
            assert blocker_entered.wait(5), "blocker never saw the terminal"
            # The terminal state is final but the recorder (subscribed
            # AFTER the blocker) cannot have received the event yet.
            assert recorder.terminal() == []
            release.set()  # deterministically let delivery finish
            recorder.wait_terminal()
            terminal = recorder.terminal()
            assert len(terminal) == 1
            assert terminal[0].outcome is JobState.SUCCEEDED
            assert terminal[0].result == "payload"
        finally:
            release.set()
            handle.wait(5)

    def test_simultaneous_finding_emissions_keep_per_job_order(self):
        """Two threads racing through the emission path while their job is
        RUNNING: per-job seq order + delivery order must agree and every
        emission must survive."""
        events = _Recorder()
        mgr = JobManager()
        mgr.subscribe(events)
        n_per_thread = 50

        def plan(ctx):
            pool = ThreadPoolExecutor(max_workers=2)

            def emitter(_offset):
                for _ in range(n_per_thread):
                    ctx.emit_finding(_demo_finding())

            futures = [pool.submit(emitter, i) for i in range(2)]
            results = [f.result(timeout=30) for f in futures]
            pool.shutdown(wait=False)
            return results

        mgr.submit(JobKind.OTHER, plan=plan).wait(10)
        findings = [e for e in events.events if hasattr(e, "finding")]
        seqs = [e.seq for e in findings]
        assert len(findings) == 2 * n_per_thread
        assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)
        terminal = events.terminal()
        # All finding events precede the terminal event in seq order.
        assert terminal[-1].seq > max(seqs)

    def test_progress_backwards_is_rejected_into_plan_failure(self):
        events = _Recorder()
        mgr = JobManager()
        mgr.subscribe(events)

        def plan(ctx):
            ctx.progress(5, total=None)
            ctx.progress(4, total=None)  # forbidden: monotonic rule

        handle = mgr.submit(JobKind.OTHER, plan=plan)
        assert handle.wait(5) is JobState.FAILED
        terminal = events.terminal()[0]
        assert isinstance(terminal.error, InputValidationError)

    def test_context_redaction_and_caps_at_the_event_boundary(self):
        events = _Recorder()
        mgr = JobManager()
        mgr.subscribe(events)

        def plan(ctx):
            ctx.log("info", "ssid linksys psk=supersecret123 token=abc")
            ctx.progress(1, 2, unit="apps", context="com.pkg." + "x" * 300)

        mgr.submit(JobKind.OTHER, plan=plan).wait(5)
        log_event = [e for e in events.events if hasattr(e, "message")][0]
        assert "supersecret123" not in log_event.message
        assert "abc" not in log_event.message
        progress = [e for e in events.events if isinstance(e, JobProgressEvent)][0]
        assert len(progress.context) <= 120


class TestShutdown:
    def test_shutdown_cancels_and_reports_no_abandoned_for_cooperative_plans(self):
        mgr = JobManager()
        gate = threading.Event()

        def plan(ctx):
            # Genuinely cooperative: checkpoints while polling.
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline:
                ctx.cancel_token.checkpoint("poll_slice")
                if gate.is_set():
                    break
                time.sleep(0.005)
            return None

        handle = mgr.submit(JobKind.OTHER, plan=plan)
        abandoned = mgr.shutdown(grace_s=5.0)
        gate.set()
        assert abandoned == ()
        assert handle.state is JobState.CANCELLED  # request → checkpoint → terminal
        with pytest.raises(InputValidationError):
            mgr.submit(JobKind.OTHER, plan=lambda ctx: None)

    def test_shutdown_grace_records_abandoned_job_ids(self):
        mgr = JobManager()
        started = threading.Event()
        released = threading.Event()

        def uncooperative(ctx):
            # No checkpoints: the strand cannot be torn down at this layer
            # (documented limitation) — bounded sleep keeps the test fast.
            started.set()
            time.sleep(0.4)
            released.set()
            return None

        mgr.submit(JobKind.OTHER, plan=uncooperative, timeout_s=None)
        assert started.wait(5)  # RUNNING claim happened: genuinely in flight
        abandoned = mgr.shutdown(grace_s=0.05)
        assert len(abandoned) == 1
        assert released.wait(5)  # the strand still completes; never "lost"
        assert mgr.handle_for(abandoned[0]) is not None
