"""Job event contracts (Stage 04 — JOB_AND_EVENT_CONTRACTS §1–2, DATA_MODELS §9).

Implemented here: the shared enums and typed event models that both future
UIs consume. Everything in this module is:

* a frozen stdlib dataclass (``slots=True``) or an ``Enum`` — events NEVER
  carry UI/framework objects, never carry functions, and never call back
  into services (contract §2 delivery rule);
* identity-neutral: ``job_id``/``kind``/``seq``/``ts`` carry defaults so
  service code inside a ``plan`` builds events without knowing which job it
  runs under. ``JobContext.emit`` fills them via ``dataclasses.replace`` —
  the event is immutable from the moment of emission onward.

Time fields use ``time.monotonic()`` seconds (ts) and integer
``duration_ms`` — monotonic clocks are required for duration math
(mission §8); wall-clock timestamps live in the existing UTC-typed models.

Validation lives in ``__post_init__`` where it is cheap and local; the
runtime rules (progress monotonicity, post-terminal drops, redaction)
enforce at the ``JobContext`` boundary in ``vscanner.services.jobs``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Optional

from vscanner.core.errors import InputValidationError, VScannerError
from vscanner.core.models import Finding

__all__ = [
    "JobId",
    "JobState",
    "TERMINAL_JOB_STATES",
    "is_terminal_job_state",
    "JobKind",
    "JobConflictScope",
    "OperationConfirmation",
    "JobEvent",
    "JOB_EVENT_CLASSES",
    "event_category",
    "JobStartedEvent",
    "JobProgressEvent",
    "JobLogChunkEvent",
    "ALLOWED_LOG_LEVELS",
    "JobFindingEvent",
    "JobSnapshotStreamEvent",
    "JobTerminalEvent",
]

JobId = str  # uuid4 hex, unique for the process lifetime (contract §1)


# ---------------------------------------------------------------------------
# §1 lifecycle enums
# ---------------------------------------------------------------------------

class JobState(Enum):
    """Exact documented state names; the last three are terminal."""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_JOB_STATES = frozenset(
    {JobState.SUCCEEDED, JobState.FAILED, JobState.CANCELLED}
)


def is_terminal_job_state(state: JobState) -> bool:
    return state in TERMINAL_JOB_STATES


class JobKind(Enum):
    """Work categories; the UI-independent job taxonomy (contract §1)."""

    DEVICE_DISCOVERY = "device_discovery"
    APP_LISTING = "app_listing"
    SINGLE_APP_SCAN = "single_app_scan"
    FULL_DEVICE_SCAN = "full_device_scan"
    DEVICE_INFO = "device_info"
    ADMIN_OP = "admin_op"
    MONITORING_SESSION = "monitoring_session"
    TOOL_PROVISIONING = "tool_provisioning"
    MIRRORING = "mirroring"
    FORENSICS_OP = "forensics_op"
    EXPORT = "export"
    DEMO = "demo"
    OTHER = "other"


class JobConflictScope(Enum):
    """Duplicate-operation identity scope (contract §7)."""

    GLOBAL = "global"          # e.g. tool provisioning: one at any time
    PER_DEVICE = "per_device"  # identity is (device_serial, mutex group)


@dataclass(frozen=True, slots=True)
class OperationConfirmation:
    """Submit-time confirmation token stub (SERVICE_CONTRACTS SC-5 note).

    Full consume-at-atomicity semantics belong to the AdministrationService
    port (Stage 08); Stage 04 validates the token shape only — empty
    references and naive timestamps are refused (honesty rule: dates are
    timezone-aware UTC, DATA_MODELS §10).
    """

    reference: str
    confirmed_at: Any  # datetime; Any keeps this module import-cheap


# ---------------------------------------------------------------------------
# §2 event objects
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class JobEvent:
    """Base event; ``seq`` is per-job, strictly increasing, assigned by the
    ``JobManager`` at dispatch, so per-job seq order == delivery order."""

    job_id: str = ""
    kind: JobKind = JobKind.OTHER
    seq: int = 0
    ts: float = 0.0  # time.monotonic() seconds at dispatch; duration math only


@dataclass(frozen=True, slots=True)
class JobStartedEvent(JobEvent):
    """Emitted once when a job leaves QUEUED and its plan begins."""

    device_serial: Optional[str] = None
    params_summary: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class JobProgressEvent(JobEvent):
    """Progress tick: bounds validated (0 <= current; total None until the
    work's enumeration completes, else current <= total)."""

    current: int = 0
    total: Optional[int] = None
    unit: str = "steps"
    context: str = ""  # <= 120 chars, redaction-applied at the boundary

    def __post_init__(self) -> None:
        _validate_progress_bounds(self.current, self.total)


@dataclass(frozen=True, slots=True)
class JobLogChunkEvent(JobEvent):
    """Log-lane message (R-12 boundary groundwork: redaction applied by the
    emitting context, never trusted from the caller)."""

    level: str = "info"
    message: str = ""

    def __post_init__(self) -> None:
        _validate_log_level(self.level)


ALLOWED_LOG_LEVELS = frozenset({"debug", "info", "warning", "error"})


@dataclass(frozen=True, slots=True)
class JobFindingEvent(JobEvent):
    """Streaming finding (immutable, already evidence-resolved by the scan
    service; evidence excerpts are redacted at ``Evidence.of``)."""

    finding: Optional[Finding] = None


@dataclass(frozen=True, slots=True)
class JobSnapshotStreamEvent(JobEvent):
    """Monitoring payload channel (SC-6 Stage 08): payload becomes
    ``HardwareUsageSnapshot | SensorReadingSet`` when those models land."""

    payload: Any = None


@dataclass(frozen=True, slots=True)
class JobTerminalEvent(JobEvent):
    """Exactly one per job (either SUCCEEDED / FAILED / CANCELLED)."""

    outcome: JobState = JobState.FAILED  # conservative default — never fabricate success
    duration_ms: int = 0
    result: Any = None
    error: Optional[VScannerError] = None
    retriable: bool = False
    at_cancellation_point: Optional[str] = None

    def __post_init__(self) -> None:
        _validate_terminal_outcome(self.outcome)


_EVENT_CATEGORY_BY_CLASS: Mapping[type, str] = {
    JobStartedEvent: "started",
    JobProgressEvent: "progress",
    JobLogChunkEvent: "log",
    JobFindingEvent: "finding",
    JobSnapshotStreamEvent: "snapshot",
    JobTerminalEvent: "terminal",
}

JOB_EVENT_CLASSES = tuple(_EVENT_CATEGORY_BY_CLASS)


def event_category(event: JobEvent) -> str:
    """UI-bridge dispatch category (contract §10): identical for both
    frontends; no event type is UI-only."""
    return _EVENT_CATEGORY_BY_CLASS[type(event)]


# ---------------------------------------------------------------------------
# local validation (typed errors; cheap and deterministic)
# ---------------------------------------------------------------------------

def _validate_log_level(level: str) -> None:
    if level not in ALLOWED_LOG_LEVELS:
        raise InputValidationError(
            f"job log level must be one of {sorted(ALLOWED_LOG_LEVELS)}",
            {"field": "level", "value": level},
        )


def _validate_progress_bounds(current: int, total: Optional[int]) -> None:
    if current < 0:
        raise InputValidationError("progress 'current' must be >= 0", {"field": "current"})
    if total is not None and total <= 0:
        raise InputValidationError("progress 'total' must be > 0 or None", {"field": "total"})
    if total is not None and current > total:
        raise InputValidationError(
            "progress 'current' exceeds 'total'", {"field": "current"}
        )


def _validate_terminal_outcome(outcome: JobState) -> None:
    if not is_terminal_job_state(outcome):
        raise InputValidationError(
            "JobTerminalEvent.outcome must be a terminal state",
            {"field": "outcome", "value": outcome.value},
        )
