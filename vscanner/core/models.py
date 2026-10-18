"""Typed domain models for the V-Scanner 3.0 engine.

Implements DATA_MODELS.md §1–8 with stdlib dataclasses only (no pydantic, no
UI-framework types). Honesty rules encoded here:

* Fields that may be unavailable on some device are ``Optional`` — renderers
  show "Unknown", services never fabricate.
* Missing information is never a finding; evidence carries the certainty
  ``EvidenceKind`` of its detection basis.
* ``Finding.stable_id`` deduplicates across runs (sha256 of identity fields,
  first 16 hex chars).
* Serialization: ``model_to_dict`` → enum values + ISO-8601 UTC datetimes;
  ``model_to_json`` adds ``schema_version`` and ``created_by`` envelope.

Python floor for the new engine is 3.10 (``slots=True`` dataclasses; the
legacy CLI stays byte-compatible regardless of its own interpreter).
"""

from __future__ import annotations

import dataclasses
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping, Optional, Tuple

from vscanner.core.redact import RedactionPreset, redact_excerpt

__all__ = [
    "DeviceTransport", "DeviceState", "ConnectionInfo", "DeviceIdentity",
    "AppLabelSource", "AppInfo",
    "ScanKind", "ScanConfiguration", "ScanRequest", "ScanLifecycleState", "ScanRun",
    "FindingSeverity", "FindingCategory", "EvidenceKind", "Evidence",
    "Remediation", "Finding",
    "AppScanResult", "ScanSummary", "ScanResultBundle",
    "ReportFormat", "ReportMetadata", "ExportResult",
    "ToolId", "ToolState", "ToolStatusReflected",
    "RootStatus", "DeviceProfile",
    "RedactionPreset",
    "model_to_dict", "model_to_json",
    "SCHEMA_VERSION",
]

# Engine output envelope version (DATA_MODELS §10).
SCHEMA_VERSION = 1
# Keep in sync with pyproject [project] version until T-08 wires them.
CREATED_BY = "vscanner/3.0.0a0"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    """Serialize a datetime as ISO-8601 in UTC, converting naive values."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# §1 Device identity & connection state
# ---------------------------------------------------------------------------

class DeviceTransport(Enum):
    USB = "usb"
    WIFI = "wifi"
    UNKNOWN = "unknown"


class DeviceState(Enum):
    DEVICE = "device"
    OFFLINE = "offline"
    UNAUTHORIZED = "unauthorized"
    RECOVERY = "recovery"
    ABSENT = "absent"


@dataclass(frozen=True, slots=True)
class ConnectionInfo:
    """One ``adb devices`` row, honestly typed.

    Unknown status tokens map to ``ABSENT`` with the raw token preserved in
    ``usb_props["raw_state"]`` (never silently reinterpreted as present).
    """

    serial: str
    transport: DeviceTransport = DeviceTransport.UNKNOWN
    state: DeviceState = DeviceState.ABSENT
    usb_props: Mapping[str, str] = field(default_factory=dict)

    @property
    def raw_state(self) -> str:
        return self.usb_props.get("raw_state", self.state.value)


@dataclass(frozen=True, slots=True)
class DeviceIdentity:
    """Resolved device facts; every property may be absent on real devices."""

    serial: str
    model: str = ""
    manufacturer: str = ""
    android_version: str = ""
    sdk_int: Optional[int] = None
    security_patch: str = ""
    unknown_when_missing: bool = True


# ---------------------------------------------------------------------------
# §2 Installed application metadata
# ---------------------------------------------------------------------------

class AppLabelSource(Enum):
    EXACT = "exact"
    HEURISTIC = "heuristic"
    UNKNOWN = "unknown"


_PACKAGE_RE = r"^[A-Za-z0-9_]+(\.[A-Za-z0-9_+]+)+$"  # tolerant canonical pattern


@dataclass(frozen=True, slots=True)
class AppInfo:
    """Installed-app snapshot.

    ``label_source`` records how ``label`` was obtained so UIs may badge
    heuristic names instead of implying an exact label. Timestamps are
    timezone-aware UTC datetimes (``None`` when unavailable honestly).
    """

    package_name: str
    label: str = "(unknown)"
    label_source: AppLabelSource = AppLabelSource.HEURISTIC
    version_name: Optional[str] = None
    version_code: Optional[int] = None
    target_sdk: Optional[int] = None
    min_sdk: Optional[int] = None
    apk_path: Optional[str] = None
    first_install_time: Optional[datetime] = None
    last_update_time: Optional[datetime] = None
    is_system: bool = False
    requested_permissions: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.package_name or not self.package_name.strip():
            raise ValueError("AppInfo.package_name must be non-empty")
        import re

        if re.match(_PACKAGE_RE, self.package_name) is None:
            raise ValueError(
                f"AppInfo.package_name {self.package_name!r} is not a valid package name"
            )

    @classmethod
    def tolerant(cls, package_name: str, **kwargs: Any) -> "AppInfo":
        """Build an AppInfo with the strict-pattern check relaxed, keeping the
        non-empty invariant. Rare vendor oddities stay flagged in reports."""
        info = cls(package_name="_legitimate_placeholder", **kwargs)
        object.__setattr__(info, "package_name", package_name)
        return info


# ---------------------------------------------------------------------------
# §3 Scan request / configuration / lifecycle
# ---------------------------------------------------------------------------

class ScanKind(Enum):
    SINGLE_APP = "single_app"
    FULL_DEVICE = "full_device"


@dataclass(frozen=True, slots=True)
class ScanConfiguration:
    include_system: bool = False
    deep: bool = False
    export_paths: Tuple[str, ...] = ()
    output_dir: Optional[str] = None
    device_serial: Optional[str] = None


@dataclass(frozen=True, slots=True)
class ScanRequest:
    """Scan work item; ``id`` is always engine-generated (uuid4 hex)."""

    kind: ScanKind
    config: ScanConfiguration = field(default_factory=ScanConfiguration)
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created_at: datetime = field(default_factory=_utcnow)

    def __post_init__(self) -> None:
        if self.kind is ScanKind.FULL_DEVICE and not (self.config.device_serial or "").strip():
            raise ValueError(
                "ScanConfiguration.device_serial must be set for FULL_DEVICE scans"
            )


class ScanLifecycleState(Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


_TERMINAL_STATES = frozenset(
    {ScanLifecycleState.COMPLETED, ScanLifecycleState.FAILED, ScanLifecycleState.CANCELLED}
)


def is_terminal_state(state: ScanLifecycleState) -> bool:
    return state in _TERMINAL_STATES


@dataclass(frozen=True, slots=True)
class ScanRun:
    request: ScanRequest
    state: ScanLifecycleState = ScanLifecycleState.QUEUED
    device: Optional[DeviceIdentity] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# §4 Findings and evidence
# ---------------------------------------------------------------------------

class FindingSeverity(Enum):
    """Mirrors the legacy five-level ``RiskLevel`` string values exactly."""

    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"


class FindingCategory(Enum):
    PERMISSION_EXCESS = "permission_excess"
    SDK_COMPAT = "sdk_compat"
    INSECURE_URL = "insecure_url"
    HARDCODED_SECRET = "hardcoded_secret"
    DEVICE_EXPOSURE = "device_exposure"
    FORENSICS_ARTIFACT = "forensics_artifact"
    INFO_NOTE = "info_note"


class EvidenceKind(Enum):
    CONFIRMED_ARTIFACT = "confirmed_artifact"
    CONFIRMED_COMMAND_OUTPUT = "confirmed_command_output"
    HEURISTIC_PATTERN = "heuristic_pattern"
    INFORMATIONAL = "informational"
    UNVERIFIED_CONDITION = "unverified_condition"


RAW_EXCERPT_MAX_CHARS = 2048


@dataclass(frozen=True, slots=True)
class Evidence:
    """One observation backing a finding; untrusted text is redacted+bounded
    at construction time via :func:`Evidence.of` (R-12 boundary groundwork)."""

    kind: EvidenceKind
    description: str
    source: str
    extracted_at: datetime = field(default_factory=_utcnow)
    raw_excerpt: Optional[str] = None

    @classmethod
    def of(
        cls,
        kind: EvidenceKind,
        description: str,
        source: str,
        raw_excerpt: Optional[str] = None,
        extracted_at: Optional[datetime] = None,
    ) -> "Evidence":
        """Constructor that applies the evidence boundary rules:
        raw excerpt capped at 2 KiB and redaction-applied; the redaction-preset
        is LOGCONSOLE (FULL exists only behind an explicit export action)."""
        return cls(
            kind=kind,
            description=description,
            source=source,
            extracted_at=extracted_at or _utcnow(),
            raw_excerpt=redact_excerpt(raw_excerpt, RAW_EXCERPT_MAX_CHARS) if raw_excerpt else None,
        )


@dataclass(frozen=True, slots=True)
class Remediation:
    recommendation: str
    category: FindingCategory = FindingCategory.INFO_NOTE
    effort: Optional[str] = None


@dataclass(frozen=True, slots=True)
class Finding:
    """A normalized finding; ``id`` is the stable cross-run dedup key.

    ``tags`` is a controlled free-form string tuple (UI badges and
    compat-writer metadata such as the permission-KB category). It must never
    carry secret material and is always safe to render.
    """

    kind: FindingCategory
    severity: FindingSeverity
    title: str
    detail: str
    evidence: Tuple[Evidence, ...] = ()
    remediation: Tuple[Remediation, ...] = ()
    app: Optional[AppInfo] = None  # device-scope findings carry None
    device_serial: Optional[str] = None
    detected_by: str = "scan-service"
    run_id: str = ""
    tags: Tuple[str, ...] = ()
    id: str = field(default="")


def stable_finding_id(
    kind: FindingCategory,
    severity: FindingSeverity,
    title: str,
    app_package: Optional[str],
    device_serial: Optional[str],
    first_evidence_source: str,
) -> str:
    """The documented stable-id transform (DATA_MODELS §4)."""
    import hashlib

    identity = "|".join(
        (
            kind.value,
            severity.value,
            app_package or "",
            device_serial or "",
            title,
            first_evidence_source,
        )
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]


def make_finding(**kwargs: Any) -> Finding:
    """Create a Finding computing ``id`` when not supplied."""
    finding = Finding(**kwargs)
    if not finding.id:
        first_source = finding.evidence[0].source if finding.evidence else ""
        computed = stable_finding_id(
            finding.kind, finding.severity, finding.title,
            finding.app.package_name if finding.app else None,
            finding.device_serial,
            first_source,
        )
        object.__setattr__(finding, "id", computed)
    return finding


# ---------------------------------------------------------------------------
# §5 Scan results and summaries
# ---------------------------------------------------------------------------

_SEVERITY_ORDER = {
    FindingSeverity.INFO: 0,
    FindingSeverity.LOW: 1,
    FindingSeverity.MEDIUM: 2,
    FindingSeverity.HIGH: 3,
    FindingSeverity.CRITICAL: 4,
}


def app_severity(result: "AppScanResult") -> FindingSeverity:
    """Highest severity among an app's findings; apps with only a skip reason
    (or nothing to report) rank INFO — never the fabricated-CRITICAL default."""

    if result.findings:
        return max((f.severity for f in result.findings), key=lambda s: _SEVERITY_ORDER[s])
    return FindingSeverity.INFO


@dataclass(frozen=True, slots=True)
class AppScanResult:
    app: Optional[AppInfo] = None           # device-scope result entries carry None
    findings: Tuple[Finding, ...] = ()
    scan_skipped_reason: Optional[str] = None  # legacy "no permissions accessible" drop


@dataclass(frozen=True, slots=True)
class ScanSummary:
    run: ScanRun
    total_apps: int = 0
    high_risk: int = 0
    medium_risk: int = 0
    low_risk: int = 0
    info_count: int = 0
    findings_total: int = 0
    per_category_counts: Mapping[FindingCategory, int] = field(default_factory=dict)
    skipped_apps: Tuple[str, ...] = ()
    generation_ms: float = 0.0


@dataclass(frozen=True, slots=True)
class ScanResultBundle:
    """Full scan outcome; ``apps`` are stored risk-descending as a
    convenience but ordering is recomputable from findings."""

    summary: ScanSummary
    apps: Tuple[AppScanResult, ...] = ()

    # --- legacy-compat computed aliases (NOT stored; DATA_MODELS §5) -----
    @property
    def total_apps(self) -> int:
        return len(self.apps)

    @property
    def high_risk_apps(self) -> int:
        # legacy: HIGH counts CRITICAL+HIGH
        return sum(1 for a in self.apps if app_severity(a) in (FindingSeverity.HIGH, FindingSeverity.CRITICAL))

    @property
    def medium_risk_apps(self) -> int:
        return sum(1 for a in self.apps if app_severity(a) is FindingSeverity.MEDIUM)

    @property
    def low_risk_apps(self) -> int:
        # legacy: LOW counts LOW+INFO
        return sum(1 for a in self.apps if app_severity(a) in (FindingSeverity.LOW, FindingSeverity.INFO))


# ---------------------------------------------------------------------------
# §6 Report metadata & export
# ---------------------------------------------------------------------------

class ReportFormat(Enum):
    HTML = "html"
    JSON = "json"
    TEXT = "text"

    @property
    def suffix(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class ReportMetadata:
    scan_run_id: str
    generated_at: datetime = field(default_factory=_utcnow)
    device_model: Optional[str] = None
    total_apps: int = 0
    tool_versions: Mapping[str, str] = field(default_factory=dict)
    redaction: RedactionPreset = RedactionPreset.LOGCONSOLE


@dataclass(frozen=True, slots=True)
class ExportResult:
    ok: bool
    path: Optional[str] = None
    size_bytes: Optional[int] = None
    error: Optional[str] = None
    formats_written: Mapping[str, str] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# §7 Tool provisioning state
# ---------------------------------------------------------------------------

class ToolId(Enum):
    ADB = "adb"
    SCRCPY = "scrcpy"


class ToolState(Enum):
    NOT_FOUND = "not_found"
    FOUND_UNVALIDATED = "found_unvalidated"
    VALIDATED = "validated"
    PROVISIONING = "provisioning"
    INSTALL_FAILED = "install_failed"


@dataclass(frozen=True, slots=True)
class ToolStatusReflected:
    tool: ToolId
    state: ToolState
    path: Optional[str] = None
    version: Optional[str] = None
    last_checked: Optional[datetime] = None
    last_validation_ok: Optional[bool] = None
    notes: Tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# SC-4 tri-state root honesty (R-05 groundwork model) + DeviceProfile
# ---------------------------------------------------------------------------

class RootStatus(Enum):
    ROOTED = "rooted"
    NOT_ROOTED = "not_rooted"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class DeviceProfile:
    """Device facts assembled from getprop-safe reads; every field may stay
    ``None`` when the device does not provide it (honesty rule — DATA_MODELS).

    ``root_status`` is the R-05 tri-state: it is ``UNKNOWN`` until a verified
    probe succeeded; nothing in the engine reports ROOTED on failed detection.
    """

    mfr: Optional[str] = None
    serial: Optional[str] = None
    model: Optional[str] = None          # ro.product.model
    brand: Optional[str] = None          # ro.product.brand
    board: Optional[str] = None          # ro.product.board
    device: Optional[str] = None         # ro.product.device
    hardware: Optional[str] = None       # ro.hardware
    build_id: Optional[str] = None       # ro.build.id
    android: Optional[str] = None        # ro.build.version.release
    sdk_int: Optional[int] = None        # ro.build.version.sdk
    patch: Optional[str] = None          # ro.build.version.security_patch
    kernel: Optional[str] = None         # uname -r
    fingerprint: Optional[str] = None    # ro.build.fingerprint
    bootloader: Optional[str] = None     # ro.bootloader
    locale: Optional[str] = None         # ro.product.locale
    timezone: Optional[str] = None       # persist.sys.timezone
    ip: Optional[str] = None
    mac: Optional[str] = None
    root_status: RootStatus = RootStatus.UNKNOWN


# ---------------------------------------------------------------------------
# §10 Serialization helpers
# ---------------------------------------------------------------------------

def model_to_dict(value: Any, *, redact: bool = False) -> Any:
    """Recursive serialization: dataclass → dict, Enum → value, datetime →
    ISO-8601 UTC string. ``redact=True`` applies LOGCONSOLE redaction to plain
    string leaves (used by any caller preparing persisted/log payloads)."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {k: model_to_dict(v, redact=redact) for k, v in dataclasses.asdict(value).items()}
    if isinstance(value, Enum):
        return model_to_dict(value.value, redact=redact)
    if isinstance(value, datetime):
        return _iso(value)
    if isinstance(value, dict):
        return {str(k): model_to_dict(v, redact=redact) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [model_to_dict(v, redact=redact) for v in value]
    if isinstance(value, str) and redact:
        from vscanner.core.redact import redact_text

        return redact_text(value)
    return value


def model_to_json(value: Any, *, redact: bool = False) -> str:
    """Deterministic JSON: ``ensure_ascii=False``, ``indent=2``, plus the
    engine envelope (``schema_version`` / ``created_by``)."""
    payload = {
        "schema_version": SCHEMA_VERSION,
        "created_by": CREATED_BY,
        "data": model_to_dict(value, redact=redact),
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)
