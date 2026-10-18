"""ScanService (SC-3): single-app analysis and full-device orchestration.

Synchronous implementation — the Stage 04 job system wraps these calls with
cancellation, progress events and conflict prevention; the service itself
stays UI-framework-free and returns :class:`ScanResultBundle` per the Stage
03 acceptance contract.

Honesty rules enforced here:

* a deep scan without the (Stage 08) host-side APK extractor produces an
  ``UNVERIFIED_CONDITION`` evidence note — never a silently empty result;
* every unknown/unavailable fact reduces to evidence or skip reasons, not
  fabricated findings;
* per-app errors are recorded as skip reasons — they never masquerade as
  "no dangerous permissions".
"""

from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Protocol, Tuple, TYPE_CHECKING

from vscanner.core.errors import InputValidationError, ScanInterrupted
from vscanner.core.kb.permissions import analyze_permissions, get_sdk_risk, RiskLevel
from vscanner.core.models import (
    AppInfo,
    AppScanResult,
    Evidence,
    EvidenceKind,
    Finding,
    FindingCategory,
    FindingSeverity,
    make_finding,
    Remediation,
    ScanConfiguration,
    ScanKind,
    ScanLifecycleState,
    ScanRequest,
    ScanResultBundle,
    ScanRun,
    ScanSummary,
    app_severity,
)
from vscanner.services.scanning.app_inventory import PackageInventoryService
from vscanner.services.scanning.package_parser import derived_label

__all__ = ["ScanService", "validate_package_name", "MAX_PACKAGE_LENGTH"]

# Stage 04 job-system seam: the context (cancel token + event emission +
# log lane) arrives from the JobManager through ``context=context``. Plain
# ``TYPE_CHECKING`` import keeps the runtime dependency graph unchanged; at
# runtime any object with ``cancel_token``/``progress``/``emit_finding``/
# ``log`` works (structural barrier per JOB_AND_EVENT_CONTRACTS §2).
if TYPE_CHECKING:  # pragma: no cover - import guard only
    from vscanner.services.jobs import JobContext  # noqa: F401


# Mission contract asks for ^[a-z0-9._+]+$; resolution of the ambiguity
# (documented deviation): real-world packages legitimately contain uppercase
# letters and debug-suffix hyphens, so the validator accepts
# [A-Za-z0-9._+-] but still rejects every shell metacharacter, whitespace
# and control character, and empty/odd-shaped names.
_PACKAGE_INPUT_RE = re.compile(r"^[A-Za-z0-9._][A-Za-z0-9._+-]*$")
MAX_PACKAGE_LENGTH = 255


def validate_package_name(package: str) -> str:
    """Pre-flight validation (input never reaches a subprocess unchecked)."""
    name = (package or "").strip()
    if not name:
        raise InputValidationError("package name must be non-empty", {"field": "package"})
    if len(name) > MAX_PACKAGE_LENGTH:
        raise InputValidationError(
            f"package name exceeds {MAX_PACKAGE_LENGTH} characters", {"field": "package"}
        )
    if _PACKAGE_INPUT_RE.match(name) is None:
        raise InputValidationError(
            "package name contains characters that are not valid package-name characters",
            {"field": "package"},
        )
    return name


class _AdbTransport(Protocol):
    def run_text(self, cmd, timeout: float = 30.0):
        ...


class ScanService:
    """SC-3 orchestration over one serial-bound ADB transport."""

    def __init__(self, transport: _AdbTransport) -> None:
        self.inventory = PackageInventoryService(transport)
        self._transport = transport

    # ------------------------------------------------------------------ #
    # single-app analysis
    # ------------------------------------------------------------------ #

    def analyze_single_app(
        self,
        package: str,
        config: Optional[ScanConfiguration] = None,
        device_serial: Optional[str] = None,
    ) -> AppScanResult:
        """Analyze one installed package → :class:`AppScanResult`.

        Raises :class:`InputValidationError` for malformed input and
        :class:`AdbCommandError` when the device commands fail.
        """
        config = config or ScanConfiguration()
        name = validate_package_name(package)
        serial = config.device_serial or device_serial

        app = self.inventory.get_app_info(name)

        if not app.requested_permissions:
            # Legacy parity: apps without accessible permission info are
            # skipped, and the skip is *recorded* (never a zero-find app scan
            # with fabricated "clean" status).
            return AppScanResult(
                app=app,
                scan_skipped_reason="no accessible permission information in dumpsys output",
            )

        perm_analysis = analyze_permissions(list(app.requested_permissions))
        findings = self._permission_findings(perm_analysis, app, serial)

        if app.target_sdk is None and app.min_sdk is None:
            findings = tuple(findings)  # nothing deterministic to reason about
        else:
            findings = tuple(findings) + tuple(
                self._sdk_findings(
                    app.target_sdk or 0,
                    app.min_sdk or 0,
                    app,
                    serial,
                )
            )

        if config.deep:
            findings = tuple(findings) + (
                self._deep_scan_unverified_note(app, serial, config.deep),
            )

        return AppScanResult(app=app, findings=tuple(findings))

    # ------------------------------------------------------------------ #
    # full-device orchestration
    # ------------------------------------------------------------------ #

    def scan_full_device(self, request: ScanRequest,
                         context: Optional["JobContext"] = None) -> ScanResultBundle:
        """Full-device orchestration (SC-3).

        ``context`` is the optional Stage 04 job seam: when provided the run
        emits ``JobProgressEvent``/``JobFindingEvent`` streams and takes
        cancellation checkpoints at the documented points (between apps;
        at the progress-emit boundary). Omitted → identical Stage 03
        behavior and none of that overhead (legacy-callers unaffected).
        """

        started = time.perf_counter()
        run = ScanRun(
            request=request,
            state=ScanLifecycleState.RUNNING,
            started_at=datetime.now(timezone.utc),
        )

        if context is not None:
            context.log("info", "enumerating installed packages")
        try:
            packages = self.inventory.list_packages(include_system=request.config.include_system)
        except Exception as exc:  # transport-level failure → interrupted scan
            raise ScanInterrupted(
                f"full-device scan could not start: {exc}", partial=False
            ) from exc

        total = len(packages)
        if context is not None and total == 0:
            context.log("info", "no packages matched the listing filter")
        results: List[AppScanResult] = []
        for index, pkg in enumerate(packages):
            if context is not None:
                # Cancellation points (JOB_AND_EVENT_CONTRACTS §5):
                # between apps, and at the progress-emit boundary below.
                context.cancel_token.checkpoint("between_apps")
            results.append(self._scan_one_package(pkg, request))
            if context is not None:
                for finding in results[-1].findings:
                    context.emit_finding(finding)
                context.progress(index + 1, total, unit="apps", context=pkg)
                context.cancel_token.checkpoint("after_progress_emit")

        summary = self._summarize(run, results, started)
        return ScanResultBundle(summary=summary, apps=tuple(results))

    def _scan_one_package(self, pkg: str, request: ScanRequest) -> AppScanResult:
        try:
            return self.analyze_single_app(
                pkg,
                config=request.config,
                device_serial=request.config.device_serial,
            )
        except InputValidationError as exc:
            return AppScanResult(
                app=AppInfo.tolerant(pkg, label=derived_label(pkg)),
                scan_skipped_reason=f"invalid package name for analysis: {exc.message}",
            )
        except Exception as exc:  # per-app failure → honest skip with cause
            return AppScanResult(
                app=AppInfo.tolerant(pkg, label=derived_label(pkg)),
                scan_skipped_reason=f"scan failed: {exc}",
            )

    # ------------------------------------------------------------------ #
    # finding construction
    # ------------------------------------------------------------------ #

    @staticmethod
    def _permission_findings(perm_analysis: dict, app: AppInfo,
                             serial: Optional[str]) -> Tuple[Finding, ...]:
        risk_map = {
            RiskLevel.CRITICAL: FindingSeverity.CRITICAL,
            RiskLevel.HIGH: FindingSeverity.HIGH,
            RiskLevel.MEDIUM: FindingSeverity.MEDIUM,
            RiskLevel.LOW: FindingSeverity.LOW,
            RiskLevel.INFO: FindingSeverity.INFO,
        }
        source = f"dumpsys package {app.package_name}"
        findings = []
        for info in perm_analysis.get("dangerous_permissions", []):
            findings.append(
                make_finding(
                    kind=FindingCategory.PERMISSION_EXCESS,
                    severity=risk_map[info.risk_level],
                    title=info.name,
                    detail=info.description,
                    evidence=(
                        Evidence.of(
                            EvidenceKind.CONFIRMED_ARTIFACT,
                            description=f"Permission declared in dumpsys output: {info.name}",
                            source=source,
                            raw_excerpt=info.name,
                        ),
                    ),
                    remediation=(
                        Remediation(
                            recommendation=info.mitigations[0] if info.mitigations else "",
                            category=FindingCategory.PERMISSION_EXCESS,
                        ),
                    ),
                    app=app,
                    device_serial=serial,
                    tags=(info.category,),
                )
            )
        return tuple(findings)

    @staticmethod
    def _sdk_findings(target_sdk: int, min_sdk: int, app: AppInfo,
                      serial: Optional[str]) -> Tuple[Finding, ...]:
        sdk_analysis = get_sdk_risk(target_sdk, min_sdk)
        severity_order = {
            RiskLevel.INFO: 0, RiskLevel.LOW: 1, RiskLevel.MEDIUM: 2,
            RiskLevel.HIGH: 3, RiskLevel.CRITICAL: 4,
        }
        candidates = [
            sdk_analysis.get("target_info", {}).get("risk"),
            sdk_analysis.get("min_info", {}).get("risk"),
        ]
        candidates = [c for c in candidates if c is not None]
        severity = {
            RiskLevel.CRITICAL: FindingSeverity.CRITICAL,
            RiskLevel.HIGH: FindingSeverity.HIGH,
            RiskLevel.MEDIUM: FindingSeverity.MEDIUM,
            RiskLevel.LOW: FindingSeverity.LOW,
            RiskLevel.INFO: FindingSeverity.INFO,
        }[
            max(candidates, key=lambda r: severity_order[r])
            if candidates else RiskLevel.INFO
        ]
        source = f"dumpsys package {app.package_name}"
        findings = []
        for rec in sdk_analysis.get("recommendations", []):
            findings.append(
                make_finding(
                    kind=FindingCategory.SDK_COMPAT,
                    severity=severity,
                    title=f"SDK advisory (target {target_sdk}, min {min_sdk})",
                    detail=rec,
                    evidence=(
                        Evidence.of(
                            EvidenceKind.INFORMATIONAL,
                            description="Derived from dumpsys SDK versions against the security KB",
                            source=source,
                        ),
                    ),
                    remediation=(
                        Remediation(recommendation=rec, category=FindingCategory.SDK_COMPAT),
                    ),
                    app=app,
                    device_serial=serial,
                )
            )
        return tuple(findings)

    @staticmethod
    def _deep_scan_unverified_note(app: AppInfo, serial: Optional[str],
                                   deep: bool) -> Finding:
        return make_finding(
            kind=FindingCategory.INSECURE_URL,
            severity=FindingSeverity.INFO,
            title="Deep-scan URL analysis unavailable",
            detail=(
                "deep=true requested, but the new engine does not yet perform "
                "on-device APK string extraction (planned Stage 08); no URL "
                "findings are claimed."
            ),
            evidence=(
                Evidence.of(
                    EvidenceKind.UNVERIFIED_CONDITION,
                    description="deep-scan requested; extraction stage not implemented yet",
                    source=f"dumpsys package {app.package_name}",
                ),
            ),
            app=app,
            device_serial=serial,
        )

    # ------------------------------------------------------------------ #
    # summary
    # ------------------------------------------------------------------ #

    def _summarize(self, run: ScanRun, results: List[AppScanResult],
                   started: float) -> ScanSummary:

        finished_at = datetime.now(timezone.utc)
        all_findings = [f for r in results for f in r.findings]
        category_counts: Dict[FindingCategory, int] = {}
        for finding in all_findings:
            category_counts[finding.kind] = category_counts.get(finding.kind, 0) + 1

        high = medium = low = 0
        for result in results:
            severity = app_severity(result)
            if severity in (FindingSeverity.CRITICAL, FindingSeverity.HIGH):
                high += 1
            elif severity is FindingSeverity.MEDIUM:
                medium += 1
            else:
                low += 1

        skipped = tuple(
            r.app.package_name for r in results if r.scan_skipped_reason and r.app
        )
        run_completed = ScanRun(
            request=run.request,
            state=ScanLifecycleState.COMPLETED,
            device=run.device,
            started_at=run.started_at,
            finished_at=finished_at,
        )
        return ScanSummary(
            run=run_completed,
            total_apps=len(results),
            high_risk=high,
            medium_risk=medium,
            low_risk=low,
            info_count=low,  # documented: legacy parity keeps the LOW bucket combined
            findings_total=len(all_findings),
            per_category_counts=category_counts,
            skipped_apps=skipped,
            generation_ms=(time.perf_counter() - started) * 1000.0,
        )
