"""Job system (Stage 04) — JOB_AND_EVENT_CONTRACTS implementation.

Owns: ``JobId``, ``OperationConfirmation`` consumption, ``CancellationToken``,
``JobContext``, ``JobHandle``, ``JobManager`` and the duplicate-operation
conflict policy (§7). The shared enums and frozen event dataclasses live one
layer down in ``vscanner.core.events`` so core/services stay framework-free;
this module re-exports them for ergonomic imports.

Delivery model (documented implementation decision):
* Events are delivered **synchronously to subscriber callbacks in the
  emit-call thread**. There is no internal bus or bounded queue — consumers
  that need marshalling (Textual/Qt bridges, contract §10) install their own
  pump over ``subscribe``; queue overflow/shutdown behavior is therefore a
  consumer-side concern. Per-job emission is serialized by a per-job
  re-entrant lock, so per-job ``seq`` order == delivery order for one job.
* Subscriber callbacks are NEVER invoked while the manager's state lock is
  held; they receive fully-assigned frozen events and cannot mutate job
  state through them.

Threading model: ``submit`` never runs user code inline (§1). Plans execute
on the manager's ``ThreadPoolExecutor``; state/seq critical sections are
small. Cooperative cancellation only — Python threads cannot be force-killed,
so a plan that never reaches a ``checkpoint`` cannot be torn down mid-flight
(documented limitation; per-command subprocess timeouts are enforced inside
the ADB client per contract §6). First transition wins: cancel/timeout/success
races resolve to exactly one terminal outcome and one terminal event.
"""

from __future__ import annotations

import dataclasses
import logging
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any, Callable, Mapping, Optional, Tuple

from vscanner.core.errors import (
    AdbCommandError,
    ConfirmationInvalid,
    InputValidationError,
    JobCancelRequested,
    JobConflictError,
    VScannerError,
)
from vscanner.core.events import (
    JobConflictScope,
    JobEvent,
    JobFindingEvent,
    JobKind,
    JobLogChunkEvent,
    JobProgressEvent,
    JobSnapshotStreamEvent,
    JobStartedEvent,
    JobState,
    JobTerminalEvent,
    OperationConfirmation,
    is_terminal_job_state,
)
from vscanner.core.models import Finding
from vscanner.core.redact import REDACTED_MARKER, redact_text

__all__ = [
    "JobId",
    "JobManager",
    "JobHandle",
    "JobContext",
    "CancellationToken",
    "OperationConfirmation",
    "JobState",
    "JobKind",
    "JobConflictScope",
    "DEFAULT_GRACE_S",
    "CONTEXT_MAX_CHARS",
]

JobId = str

DEFAULT_GRACE_S = 10.0    # contract §8 UI-shutdown grace
CONTEXT_MAX_CHARS = 120   # cancellation point / progress context cap (§2)
LOG_MESSAGE_MAX_CHARS = 2000
PARAMS_KEY_MAX_CHARS = 60
PARAMS_VALUE_MAX_CHARS = 120
DEFAULT_RETAINED_TERMINAL = 256

_MUTEX_GROUPS: Mapping[JobKind, str] = {
    JobKind.FULL_DEVICE_SCAN: "scan",
    JobKind.SINGLE_APP_SCAN: "scan",
    JobKind.ADMIN_OP: "admin_op",
    JobKind.MIRRORING: "mirroring",
    JobKind.FORENSICS_OP: "forensics_write",
    JobKind.TOOL_PROVISIONING: "tool_provisioning",
}

_KIND_DEFAULT_SCOPE: Mapping[JobKind, JobConflictScope] = {
    JobKind.TOOL_PROVISIONING: JobConflictScope.GLOBAL,
}


def _mutex_group(kind: JobKind) -> Optional[str]:
    return _MUTEX_GROUPS.get(kind)


def _kind_default_scope(kind: JobKind) -> JobConflictScope:
    return _KIND_DEFAULT_SCOPE.get(kind, JobConflictScope.PER_DEVICE)


def _sanitize_point(label: str) -> str:
    """Cancellation-point / progress-context text: capped and redacted."""
    return redact_text((label or "")[:CONTEXT_MAX_CHARS])


_SENSITIVE_PARAM_KEY = re.compile(
    r"(?i)^(.*(psk|preshared|password|passwd|secret|token|authorization|api[_-]?key).*)$"
)


def _redact_params(values: Optional[Mapping[str, str]]) -> dict:
    """Small, redacted params summary (R-12 boundary; contract §2).

    A value whose KEY names sensitive material is masked entirely (a bare
    ``"hunter2"`` carries no ``key=value`` shape that ``redact_text`` could
    recognize); every other value goes through the redaction filter so
    identifier- and credential-shaped text never leaves the boundary."""
    if not values:
        return {}
    out = {}
    for key, value in values.items():
        text = str(value)
        if _SENSITIVE_PARAM_KEY.match(str(key)):
            text = REDACTED_MARKER  # sensitive key: mask the whole value
        else:
            text = redact_text(text)
        out[str(key)[:PARAMS_KEY_MAX_CHARS]] = text[:PARAMS_VALUE_MAX_CHARS]
    return out


def _retriable_of(error: VScannerError) -> bool:
    """Transient-failure classification (documented policy): only ADB
    command timeouts are marked retriable today."""
    return isinstance(error, AdbCommandError) and error.timeout


def _validate_confirmation(token: OperationConfirmation) -> OperationConfirmation:
    """Shape-level validation (consume-at-atomicity is the SC-5 service's
    job at its Stage 08 port; the manager refuses malformed tokens early)."""
    if not isinstance(token, OperationConfirmation):
        raise ConfirmationInvalid(
            "confirmation must be an OperationConfirmation token"
        )
    if not token.reference.strip():
        raise ConfirmationInvalid("confirmation reference must be non-empty")
    if not isinstance(token.confirmed_at, datetime):
        raise ConfirmationInvalid("confirmation timestamp missing or invalid")
    if token.confirmed_at.tzinfo is None:
        raise ConfirmationInvalid(
            "confirmation timestamp must be timezone-aware (UTC)"
        )
    return token


class CancellationToken:
    """Contract §5 token: request() / is_cancelled / checkpoint(label)."""

    __slots__ = ("_event",)

    def __init__(self) -> None:
        self._event = threading.Event()

    def request(self) -> None:
        self._event.set()

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def checkpoint(self, label: str = "") -> None:
        """No-op while running; the first call after ``request()`` raises
        :class:`JobCancelRequested` with ``message`` = the (sanitized) label,
        which later becomes the terminal event's cancellation point."""
        if self._event.is_set():
            raise JobCancelRequested(_sanitize_point(label))


class JobContext:
    """The barrier object services receive (contract §2): cancel token +
    event emission + log-lane proxy. Constructed only by the manager.
    Redaction, bounds and progress monotonicity are enforced here/manager
    side — never trusted from callers."""
    __slots__ = ("_manager", "_job_id", "_kind", "cancel_token")

    def __init__(self, manager: "JobManager", job_id: str,
                 kind: JobKind, cancel_token: CancellationToken) -> None:
        self._manager = manager
        self._job_id = job_id
        self._kind = kind
        self.cancel_token = cancel_token

    @property
    def job_id(self) -> JobId:
        return self._job_id

    @property
    def kind(self) -> JobKind:
        return self._kind

    def emit(self, event: JobEvent) -> bool:
        """Advanced emission (snapshot streams, custom events). The manager
        FORCIBLY assigns identity (job_id/kind/seq/ts); caller values for
        those fields are ignored on purpose."""
        if not isinstance(event, JobEvent):
            raise InputValidationError(
                "JobContext.emit requires a JobEvent", {"field": "event"}
            )
        return self._manager._emit(self._job_id, event)

    def emit_finding(self, finding: Finding) -> bool:
        if not isinstance(finding, Finding):
            raise InputValidationError(
                "JobContext.emit_finding requires a Finding", {"field": "finding"}
            )
        return self._manager._emit(self._job_id, JobFindingEvent(finding=finding))

    def progress(self, current: int, total: Optional[int] = None,
                 unit: str = "steps", context: str = "") -> bool:
        return self._manager._emit(self._job_id, JobProgressEvent(
            current=current,
            total=total,
            unit=unit,
            context=_sanitize_point(context),
        ))

    def log(self, level: str, message: str) -> bool:
        return self._manager._emit(self._job_id, JobLogChunkEvent(
            level=level,
            message=redact_text((message or "")[:LOG_MESSAGE_MAX_CHARS]),
        ))

    def emit_snapshot(self, payload: object) -> bool:
        """Monitor-lane payload emission (SC-6 Stage 08).

        Accepts only the honest monitor models — a poll never smuggles
        free-text "status" into the stream (typed payloads keep the
        snapshot channel renderable and honest).
        """
        from vscanner.core.models import HardwareUsageSnapshot, SensorReading

        if not isinstance(payload, (HardwareUsageSnapshot, SensorReading)):
            raise InputValidationError(
                "JobContext.emit_snapshot requires a HardwareUsageSnapshot "
                "or SensorReading payload", {"field": "payload"},
            )
        return self._manager._emit(
            self._job_id, JobSnapshotStreamEvent(payload=payload))


class _JobRecord:
    """Per-job mutable bookkeeping; never escapes the manager."""

    __slots__ = (
        "job_id", "kind", "device_serial", "scope", "mutex_group", "conflict_key",
        "plan", "params_summary", "confirmations", "timeout_s",
        "state", "cancel_token", "terminal_event", "deadline_exceeded",
        "started_at", "finished_at", "last_progress", "terminal_emitted",
        "exception", "timer", "emit_lock", "post_terminal_drops",
    )

    def __init__(
        self,
        job_id: str,
        kind: JobKind,
        device_serial: Optional[str],
        scope: JobConflictScope,
        mutex_group: Optional[str],
        conflict_key: Tuple[Optional[str], Optional[str]],
        plan: Callable[[JobContext], Any],
        params_summary: Mapping[str, str],
        confirmations: Tuple[OperationConfirmation, ...],
        timeout_s: Optional[float],
    ) -> None:
        self.job_id = job_id
        self.kind = kind
        self.device_serial = device_serial
        self.scope = scope
        self.mutex_group = mutex_group
        self.conflict_key = conflict_key
        self.plan = plan
        self.params_summary = dict(params_summary)
        self.confirmations = tuple(confirmations)
        self.timeout_s = timeout_s
        self.state = JobState.QUEUED
        self.cancel_token = CancellationToken()
        self.terminal_event = threading.Event()
        self.deadline_exceeded = False
        self.started_at: Optional[float] = None
        self.finished_at: Optional[float] = None
        self.last_progress = -1
        self.terminal_emitted = False
        self.exception: Optional[BaseException] = None
        self.timer: Optional[threading.Timer] = None
        self.emit_lock = threading.RLock()
        self.post_terminal_drops = 0


class JobHandle:
    """Public per-job face (contract §1): id/kind/device_serial/state are
    read-only properties, ``cancel()`` is idempotent, ``wait`` resolves."""

    __slots__ = ("_manager", "_rec")

    def __init__(self, manager: "JobManager", rec: _JobRecord) -> None:
        self._manager = manager
        self._rec = rec

    @property
    def id(self) -> JobId:
        return self._rec.job_id

    @property
    def kind(self) -> JobKind:
        return self._rec.kind

    @property
    def device_serial(self) -> Optional[str]:
        return self._rec.device_serial

    @property
    def state(self) -> JobState:
        return self._rec.state

    def cancel(self) -> None:
        """Request cancellation. Safe to call any number of times, from any
        thread, on any job state. This REQUESTS — completion is confirmed by
        the terminal event (request vs. acknowledgement, contract §1/§5)."""
        self._manager._request_cancel(self._rec)

    def wait(self, timeout: Optional[float] = None) -> JobState:
        """Block until terminal; on timeout returns the current state.
        Never call from an event-loop thread (contract §6) — subscriber
        callbacks must not block either."""
        if timeout is not None and timeout < 0:
            raise InputValidationError(
                "wait timeout must be >= 0 or None", {"field": "timeout"}
            )
        self._rec.terminal_event.wait(timeout)
        return self._rec.state


class JobManager:
    """Submit / observe / cancel / shut down (contract §1 + §8)."""

    def __init__(self, max_workers: int = 4,
                 retained_terminal: int = DEFAULT_RETAINED_TERMINAL) -> None:
        if max_workers < 1:
            raise InputValidationError(
                "max_workers must be >= 1", {"field": "max_workers"}
            )
        if retained_terminal < 1:
            raise InputValidationError(
                "retained_terminal must be >= 1", {"field": "retained_terminal"}
            )
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="vscanner-jobs"
        )
        self._lock = threading.RLock()
        self._records: "dict[str, _JobRecord]" = {}
        self._seqs: "dict[str, int]" = {}
        self._retained_terminal = retained_terminal
        self._subscribers: "tuple[Callable[[JobEvent], None], ...]" = ()
        self._subscriber_lock = threading.Lock()
        self._logger = logging.getLogger("vscanner.jobs")
        self._shutting_down = False

    # ------------------------------------------------------------------ #
    # subscriptions (contract §2)
    # ------------------------------------------------------------------ #

    def subscribe(self, callback: Callable[[JobEvent], None]) -> Callable[[], None]:
        """Register a synchronous subscriber; returns its unsubscribe fn.

        Subscriber exceptions are contained (logged with exception type
        only — no raw repr) and never stop delivery to other subscribers
        nor corrupt job state. Subscribe/unsubscribe is thread-safe."""
        if not callable(callback):
            raise InputValidationError(
                "subscriber must be callable", {"field": "callback"}
            )
        with self._subscriber_lock:
            self._subscribers = self._subscribers + (callback,)

        def unsubscribe() -> None:
            with self._subscriber_lock:
                self._subscribers = tuple(
                    cb for cb in self._subscribers if cb is not callback
                )

        return unsubscribe

    # ------------------------------------------------------------------ #
    # submission (contract §1)
    # ------------------------------------------------------------------ #

    def submit(
        self,
        kind: JobKind,
        device_serial: Optional[str] = None,
        plan: Optional[Callable[[JobContext], Any]] = None,
        scope: Optional[JobConflictScope] = None,
        timeout_s: Optional[float] = None,
        confirmations: Tuple[OperationConfirmation, ...] = (),
        params_summary: Optional[Mapping[str, str]] = None,
    ) -> JobHandle:
        """Validate → conflict-check → queue. NEVER runs ``plan`` inline.

        Raises ``JobConflictError`` naming the active job id when a
        mutually-exclusive operation of the same identity is still active —
        nothing is started in that case."""
        if self._shutting_down:
            raise InputValidationError(
                "job manager is shutting down", {"field": "manager"}
            )
        if not isinstance(kind, JobKind):
            raise InputValidationError("kind must be a JobKind", {"field": "kind"})
        if not callable(plan):
            raise InputValidationError("plan must be callable", {"field": "plan"})
        if device_serial is not None and not str(device_serial).strip():
            raise InputValidationError(
                "device_serial must be None or a non-empty string",
                {"field": "device_serial"},
            )
        if timeout_s is not None and timeout_s <= 0:
            raise InputValidationError(
                "timeout_s must be positive or None", {"field": "timeout_s"}
            )
        serial = None if device_serial is None else str(device_serial).strip()
        effective_scope = scope if scope is not None else _kind_default_scope(kind)
        group = _mutex_group(kind)
        # Conflict identity (§1): GLOBAL jobs key (None, group) regardless of
        # device; PER_DEVICE key (device_serial, group). A PER_DEVICE job
        # with serial None intentionally collides with a GLOBAL job of the
        # same group — conservative by design.
        identity: Tuple[Optional[str], Optional[str]] = (
            (None, group) if (effective_scope is JobConflictScope.GLOBAL and group)
            else (serial, group)
        )
        summary = _redact_params(params_summary)
        confirmations = tuple(_validate_confirmation(tok) for tok in confirmations)

        with self._lock:
            if self._shutting_down:  # atomicity re-check under the lock
                raise InputValidationError(
                    "job manager is shutting down", {"field": "manager"}
                )
            if group is not None:
                for rec in self._records.values():
                    if (rec.conflict_key == identity
                            and not is_terminal_job_state(rec.state)):
                        raise JobConflictError(
                            "a conflicting job is already active for this target",
                            {"active_job_id": rec.job_id, "group": group},
                        )
            rec = _JobRecord(
                job_id=uuid.uuid4().hex,
                kind=kind,
                device_serial=serial,
                scope=effective_scope,
                mutex_group=group,
                conflict_key=identity,
                plan=plan,
                params_summary=summary,
                confirmations=confirmations,
                timeout_s=timeout_s,
            )
            self._records[rec.job_id] = rec
            self._spawn(rec)
            self._prune_locked()
        return JobHandle(self, rec)

    def _spawn(self, rec: _JobRecord) -> None:
        """Single scheduling entry point (submit never runs user code
        inline); tests may monkeypatch this to observe the plan boundary
        directly, which keeps submit's inline-execution guarantee
        verifiable."""
        self._executor.submit(self._run_plan, rec)

    def _prune_locked(self) -> None:
        """Retention bound (mission §8): keep at most N terminal records
        (oldest pruned first) so completed-job bookkeeping cannot grow
        unboundedly; ``handle_for`` keeps working for recent jobs."""
        terminal = [
            (rec.finished_at or 0.0, rec.job_id)
            for rec in self._records.values() if is_terminal_job_state(rec.state)
        ]
        if len(terminal) <= self._retained_terminal:
            return
        terminal.sort()
        excess = len(terminal) - self._retained_terminal
        for _, job_id in terminal[:excess]:
            self._records.pop(job_id, None)
            self._seqs.pop(job_id, None)

    # ------------------------------------------------------------------ #
    # queries (contract §1)
    # ------------------------------------------------------------------ #

    def handle_for(self, job_id: str) -> Optional[JobHandle]:
        with self._lock:
            rec = self._records.get(job_id)
        return JobHandle(self, rec) if rec is not None else None

    def active_for_device(self, serial: str) -> Tuple[JobHandle, ...]:
        """Non-terminal handles bound to ``serial`` — the UI "busy" surface."""
        with self._lock:
            recs = tuple(
                rec for rec in self._records.values()
                if rec.device_serial == serial
                and not is_terminal_job_state(rec.state)
            )
        return tuple(JobHandle(self, rec) for rec in recs)

    # ------------------------------------------------------------------ #
    # cancellation (contract §5 + §8)
    # ------------------------------------------------------------------ #

    def _request_cancel(self, rec: _JobRecord) -> None:
        """Idempotent REQUEST; the terminal event is the acknowledgement.

        QUEUED → terminal CANCELLED now (the plan never runs, no
        JobStartedEvent). RUNNING → only the token is set; the terminal
        transition happens when the plan reaches its next ``checkpoint``
        (or, on a timeout, when the deadline path applies) — never claimed
        falsely while the work may still be in flight. Terminal → no-op."""
        rec.cancel_token.request()
        with self._lock:
            was_queued = rec.state is JobState.QUEUED
        if was_queued:
            # Try to claim QUEUED→CANCELLED; if the worker claimed RUNNING
            # first, this degrades to the token-only request path.
            self._emit_terminal(rec, JobState.CANCELLED, at_point=None,
                                expected_state=JobState.QUEUED)
        elif rec.state is JobState.RUNNING:
            self._job_logger(rec).info(
                "cancellation requested (job still running; the terminal event "
                "follows at the next checkpoint)"
            )

    def cancel_device_work(self, serial: str) -> None:
        """Device-switch/app-shutdown entry (contract §8): cancels PER_DEVICE
        work bound to ``serial``; GLOBAL jobs (TOOL_PROVISIONING) are not
        touched here — call ``cancel_all()`` for the full shutdown path."""
        with self._lock:
            targets = tuple(
                rec for rec in self._records.values()
                if rec.device_serial == serial
                and rec.scope is JobConflictScope.PER_DEVICE
                and not is_terminal_job_state(rec.state)
            )
        for rec in targets:
            self._request_cancel(rec)

    def cancel_all(self) -> None:
        with self._lock:
            targets = tuple(
                rec for rec in self._records.values()
                if not is_terminal_job_state(rec.state)
            )
        for rec in targets:
            self._request_cancel(rec)

    # ------------------------------------------------------------------ #
    # shutdown (contract §8)
    # ------------------------------------------------------------------ #

    def shutdown(self, grace_s: float = DEFAULT_GRACE_S) -> Tuple[JobId, ...]:
        """Cancel everything, wait up to ``grace_s`` for terminal states,
        record ``JOB_ABANDONED`` for stragglers, then detach the executor.

        Returns the abandoned job ids. A worker stuck inside a
        non-cooperative OS call cannot be force-killed at this layer
        (documented §8 limitation; the process exit constrains it)."""
        if grace_s < 0:
            raise InputValidationError("grace must be >= 0", {"field": "grace"})
        self._shutting_down = True  # refuse new submissions from here on
        self.cancel_all()
        deadline = time.monotonic() + grace_s
        abandoned: "list[_JobRecord]" = []
        with self._lock:
            pending = tuple(
                rec for rec in self._records.values()
                if not is_terminal_job_state(rec.state)
            )
        for rec in pending:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not rec.terminal_event.wait(remaining):
                abandoned.append(rec)
        for rec in abandoned:
            self._job_logger(rec).warning(
                "JOB_ABANDONED: did not reach a terminal state within the "
                "%.1fs shutdown grace; running detached",
                grace_s,
            )
        self._executor.shutdown(wait=False)
        return tuple(rec.job_id for rec in abandoned)

    # ------------------------------------------------------------------ #
    # emission pipeline (contract §2)
    # ------------------------------------------------------------------ #

    def _record(self, job_id: str) -> Optional[_JobRecord]:
        with self._lock:
            return self._records.get(job_id)

    def _job_logger(self, rec: _JobRecord) -> logging.Logger:
        return logging.getLogger(f"vscanner.jobs.{rec.job_id[:8]}")

    def _emit(self, job_id: str, event: JobEvent) -> bool:
        rec = self._record(job_id)
        if rec is None:
            self._logger.warning(
                "event for unknown/pruned job dropped (id=%s…)", job_id[:8]
            )
            return False
        return self._dispatch(rec, event)

    def _dispatch(self, rec: _JobRecord, event: JobEvent) -> bool:
        """One emission = drop-check + seq assignment + delivery, serialized
        per job by ``rec.emit_lock`` (per-job ordering guarantee). The state
        lock is only held for the bookkeeping, never while callbacks run."""
        with rec.emit_lock:  # re-entrant: cancel() from a subscriber is safe
            with self._lock:
                terminal_now = is_terminal_job_state(rec.state)
                if isinstance(event, JobTerminalEvent):
                    if rec.terminal_emitted:
                        rec.post_terminal_drops += 1
                        drop = True
                    else:
                        drop = False  # the terminal event itself must pass
                elif terminal_now:
                    rec.post_terminal_drops += 1
                    drop = True
                else:
                    drop = False
                if drop:
                    first_drop = rec.post_terminal_drops == 1
            if drop and first_drop:
                self._job_logger(rec).warning(
                    "post-terminal event dropped (%s); outcome already fixed",
                    type(event).__name__,
                )
            if drop:
                return False
            if isinstance(event, JobProgressEvent):
                with self._lock:
                    if event.current < rec.last_progress:
                        raise InputValidationError(
                            "progress cannot move backwards",
                            {"field": "current", "job_id": rec.job_id},
                        )
                    rec.last_progress = event.current
            typed = dataclasses.replace(
                event, job_id=rec.job_id, kind=rec.kind,
                seq=self._next_seq(rec), ts=time.monotonic(),
            )
            self._deliver(rec, typed)
            return True

    def _next_seq(self, rec: _JobRecord) -> int:
        with self._lock:
            seq = self._seqs.get(rec.job_id, 0) + 1
            self._seqs[rec.job_id] = seq
            return seq

    def _deliver(self, rec: _JobRecord, event: JobEvent) -> None:
        with self._subscriber_lock:
            subscribers = self._subscribers
        first_failure: Optional[type] = None
        for callback in subscribers:
            try:
                callback(event)
            except Exception as exc:  # contained; never re-raised into jobs
                if first_failure is None:
                    first_failure = type(exc)
        if first_failure is not None:
            self._job_logger(rec).warning(
                "subscriber(s) failed while handling %s (exception type: %s)",
                type(event).__name__, first_failure.__name__,
            )

    def _emit_terminal(
        self,
        rec: _JobRecord,
        outcome: JobState,
        *,
        result: Any = None,
        error: Optional[VScannerError] = None,
        retriable: bool = False,
        at_point: Optional[str] = None,
        expected_state: Optional[JobState] = None,
    ) -> None:
        """Exactly-one-terminal guard + terminal event publication.

        ``expected_state`` restricts the claim to a specific pre-terminal
        state (used by queued-cancel so a worker that already claimed
        RUNNING cannot be cancelled mid-flight by a stale queued path)."""
        with self._lock:
            if is_terminal_job_state(rec.state):
                return  # first transition wins; no duplicate terminal event
            if expected_state is not None and rec.state is not expected_state:
                return
            rec.state = outcome
            rec.finished_at = time.monotonic()
            rec.terminal_event.set()
            duration_ms = (
                int(max(0.0, rec.finished_at - rec.started_at) * 1000.0)
                if rec.started_at is not None else 0
            )
        self._stop_timer(rec)
        self._dispatch(rec, JobTerminalEvent(
            outcome=outcome,
            duration_ms=duration_ms,
            result=result,
            error=error,
            retriable=retriable,
            at_cancellation_point=at_point,
        ))
        with self._lock:
            rec.terminal_emitted = True

    def _stop_timer(self, rec: _JobRecord) -> None:
        timer = rec.timer
        if timer is not None:
            timer.cancel()

    # ------------------------------------------------------------------ #
    # worker body (contract §4: error propagation and cleanup)
    # ------------------------------------------------------------------ #

    def _run_plan(self, rec: _JobRecord) -> None:
        ctx = JobContext(self, rec.job_id, rec.kind, rec.cancel_token)
        with self._lock:
            if rec.state is not JobState.QUEUED:
                return  # cancelled while queued — the plan must not run
            rec.state = JobState.RUNNING
            rec.started_at = time.monotonic()
        if rec.timeout_s is not None:
            timer = threading.Timer(rec.timeout_s, self._on_deadline, args=(rec,))
            timer.daemon = True
            with self._lock:
                if rec.state is not JobState.RUNNING:
                    return  # defensive: terminal raced in during setup
                rec.timer = timer
            timer.start()
        self._dispatch(rec, JobStartedEvent(
            device_serial=rec.device_serial,
            params_summary=dict(rec.params_summary),
        ))
        try:
            result = rec.plan(ctx)
        except JobCancelRequested as exc:
            if rec.deadline_exceeded:
                self._job_logger(rec).info(
                    "deadline reached; stopped at checkpoint %r", exc.message
                )
                self._emit_terminal(
                    rec,
                    JobState.FAILED,
                    error=VScannerError(
                        "job exceeded its timeout and stopped at a cancellation "
                        "checkpoint",
                        {
                            "timeout_s": "" if rec.timeout_s is None
                            else str(rec.timeout_s),
                            "stopped_at": _sanitize_point(exc.message),
                        },
                    ),
                    retriable=True,
                )
            else:
                self._emit_terminal(rec, JobState.CANCELLED,
                                    at_point=_sanitize_point(exc.message))
            return
        except VScannerError as exc:
            self._job_logger(rec).info(
                "plan failed: %s", redact_text(exc.message)[:500]
            )
            self._emit_terminal(rec, JobState.FAILED, error=exc,
                                retriable=_retriable_of(exc))
            return
        except (KeyboardInterrupt, SystemExit) as exc:
            rec.exception = exc
            self._emit_terminal(
                rec,
                JobState.FAILED,
                error=VScannerError(
                    "plan was interrupted by an interpreter-level signal",
                    {"signal_type": type(exc).__name__},
                ),
            )
            self._job_logger(rec).error(
                "plan interrupted by %s", type(exc).__name__
            )
            raise  # contract §4: never wrap KeyboardInterrupt-class signals
        except BaseException as exc:  # unexpected — summarized, type only
            rec.exception = exc  # preserved internally; NOT raw-logged/emitted
            self._job_logger(rec).error(
                "plan failed with unexpected exception type %s",
                type(exc).__name__,
            )
            self._emit_terminal(
                rec,
                JobState.FAILED,
                error=VScannerError(
                    f"unexpected failure in job ({rec.kind.value})",
                    {"exception_type": type(exc).__name__},
                ),
            )
            return
        else:
            # Deterministic race resolution: a plan that finishes validly
            # despite a queued cancel/timeout reports SUCCEEDED — its result
            # is honest and must not be discarded. A plan that hits a
            # checkpoint AFTER the deadline reports FAILED(timeout) instead.
            self._emit_terminal(rec, JobState.SUCCEEDED, result=result)
        finally:
            with self._lock:
                still_running = rec.state is JobState.RUNNING
            if still_running:  # defense-in-depth against interior bugs
                self._emit_terminal(
                    rec,
                    JobState.FAILED,
                    error=VScannerError("plan exited without a terminal outcome"),
                )

    def _on_deadline(self, rec: _JobRecord) -> None:
        with self._lock:
            if is_terminal_job_state(rec.state) or rec.deadline_exceeded:
                return
            rec.deadline_exceeded = True
        rec.cancel_token.request()
        self._job_logger(rec).warning(
            "job exceeded its %ss timeout; cooperative cancellation requested",
            rec.timeout_s,
        )
