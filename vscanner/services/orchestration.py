"""Stage 04 orchestration seam (smallest practical).

Plan factories that route Stage 03 services through the JobManager
(ROADMAP Stage 04: "re-route scanning/reporting/provisioning/monitoring
jobs through it"). Each factory is a thin closure — it MUST NOT duplicate
service logic; the services stay directly call-compatible (legacy shims and
tests keep using them unchanged). The MonitoringService plan arrives with
SC-6 (Stage 08); a MONITORING_SESSION-kind plan is a plain closure over the
future service contract.

Contract notes:
* FULL_DEVICE_SCAN checkpoints live inside ``ScanService.scan_full_device``
  (between apps / progress-emit boundary) when it receives a ``context``;
* SINGLE_APP analysis is currently one indivisible service stage — the
  supported cancellation boundary is before/after the call (documented
  limitation; deep-scan stage boundaries arrive with the Stage 08 work);
* TOOL_PROVISIONING checkpoints live inside ``ToolProvisioningService``
  (download-chunk boundaries, before extract, before install move);
* export (SC-9) is fast/atomic and exempt from checkpoints (§5 table).
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from vscanner.core.models import (
    AppScanResult,
    ExportResult,
    ReportFormat,
    ScanConfiguration,
    ScanResultBundle,
    ToolId,
    ToolStatusReflected,
)
from vscanner.services.scanning.app_inventory import PackageInventoryService
from vscanner.services.scanning.scanner import ScanService
from vscanner.services.tools.provisioning import (
    DownloadProgress,
    ToolProvisioningService,
)

__all__ = [
    "full_device_scan_plan",
    "single_app_scan_plan",
    "app_listing_plan",
    "app_listing_rows_plan",
    "export_reports_plan",
    "tool_provisioning_plan",
    "monitoring_session_plan",
    "admin_op_plan",
    "forensics_job_plan",
    "demo_scan_plan",
]

Plan = Callable[[Any], Any]  # (JobContext) -> result; untyped to avoid a cycle


def full_device_scan_plan(
    scan_service: ScanService,
    request: Any,  # ScanRequest
) -> Plan:
    """FULL_DEVICE_SCAN: streaming progress/findings + between-app cancel."""
    def plan(context: Any) -> ScanResultBundle:
        return scan_service.scan_full_device(request, context=context)
    return plan


def single_app_scan_plan(
    scan_service: ScanService,
    package: str,
    config: Optional[ScanConfiguration] = None,
) -> Plan:
    """SINGLE_APP_SCAN; checkpoint boundaries are before/after the call —
    the analysis stage itself is indivisible until Stage 08 (documented)."""
    def plan(context: Any) -> AppScanResult:
        context.cancel_token.checkpoint("before_app_analysis")
        result = scan_service.analyze_single_app(package, config=config)
        context.cancel_token.checkpoint("after_app_analysis")
        return result
    return plan


def app_listing_plan(
    inventory_service: PackageInventoryService,
    include_system: bool = False,
) -> Plan:
    """APP_LISTING (SC-2): one `pm list packages` command — the cancellation
    boundary is before the command; per-label checkpoints arrive with the
    Stage 06 label-resolution work."""
    def plan(context: Any) -> tuple[str, ...]:
        context.cancel_token.checkpoint("before_package_listing")
        return inventory_service.list_packages(include_system=include_system)
    return plan


def app_listing_rows_plan(
    inventory_service: PackageInventoryService,
    include_system: bool = False,
) -> Plan:
    """APP_LISTING (SC-2, Stage 06 rows): returns documented ``AppInfo``
    rows (honest ``HEURISTIC`` labels — see
    ``PackageInventoryService.list_app_rows``). Cancellation boundary is
    before the listing command, unchanged from ``app_listing_plan``."""
    def plan(context: Any) -> tuple:
        context.cancel_token.checkpoint("before_package_listing")
        rows = inventory_service.list_app_rows(include_system=include_system)
        # Cooperative post-listing boundary (Stage 06): a cancel request
        # that arrives while the command ran is acknowledged HERE, so the
        # job terminalizes as CANCELLED deterministically (request ≠ ack
        # unless the plan passes a checkpoint).
        context.cancel_token.checkpoint("after_package_listing")
        if rows:
            context.progress(len(rows), len(rows), unit="apps",
                             context="package listing received")
        return rows
    return plan


def export_reports_plan(
    report_service: Any,
    bundle: ScanResultBundle,
    requested: "Optional[dict[ReportFormat, Optional[str]]]" = None,
    output_dir: Optional[str] = None,
    device_info: Optional[dict] = None,
) -> Plan:
    """EXPORT (SC-9): fast, atomic write — exempt from cancellation."""
    def plan(context: Any) -> ExportResult:
        return report_service.export(bundle, requested, output_dir, device_info)
    return plan


def tool_provisioning_plan(
    provisioning_service: ToolProvisioningService,
    tool: ToolId,
    version: Optional[str] = None,
) -> Plan:
    """TOOL_PROVISIONING (SC-7): chunk-level download progress + cooperative
    cancellation inside the staged pipeline (documented R-11 flow)."""
    def plan(context: Any) -> ToolStatusReflected:
        # Parameter names must match the DownloadProgress protocol's keyword
        # names (mypy structural check: keyword-compatible signatures).
        def progress(downloaded: int, total: Optional[int]) -> None:
            context.progress(
                downloaded,
                total,
                unit="bytes",
                context="provisioning download",
            )
        handler: DownloadProgress = progress
        return provisioning_service.provision_tool(
            tool, version=version, progress=handler, context=context,
        )
    return plan


# ---------------------------------------------------------------------------
# Stage 08 plans (SC-5 / SC-6 / forensics / demo)
# ---------------------------------------------------------------------------

def monitoring_session_plan(
    monitor_service: Any,
    serial: Optional[str],
    interval_s: float = 2.0,
    max_consecutive_failures: int = 3,
) -> Plan:
    """MONITORING_SESSION (SC-6, Stage 08): poll the honest usage surface
    each tick and emit typed snapshot payloads. The session runs until the
    user stops it (cancel→CANCELLED, the contract's session semantic) or
    aborts honestly after ``max_consecutive_failures`` consecutive failed
    polls (log-noted; result carries the abort reason).

    Cancellation boundary: checkpoints between polls and inside the sleep
    slices (documented §5 contract row for MONITORING_SESSION). The loop
    NEVER runs on the UI thread — it executes inside the job's worker
    thread."""
    import time as _time

    def plan(context: Any) -> "dict[str, object]":
        polls = 0
        consecutive_failures = 0
        while True:
            context.cancel_token.checkpoint("between_polls")
            try:
                snapshot = monitor_service.read_hardware_usage_once(
                    serial=serial)
                context.emit_snapshot(snapshot)
                for capability, line in snapshot.evidence:
                    context.log("info", f"{capability} observed: {line}")
                for failure in snapshot.failures:
                    context.log("warn", failure)
                consecutive_failures = 0
                polls += 1
            except Exception as exc:  # failed poll is recorded, not fabricated
                consecutive_failures += 1
                context.log(
                    "error",
                    f"poll failed ({type(exc).__name__}); "
                    f"{consecutive_failures}/{max_consecutive_failures} "
                    "consecutive failures",
                )
                if consecutive_failures >= max_consecutive_failures:
                    return {
                        "status": "aborted",
                        "reason": (
                            f"{consecutive_failures} consecutive failed polls"
                        ),
                        "polls_completed": polls,
                    }
            # cooperative sleep: check for cancellation each slice so a stop
            # request never waits longer than the configured granularity
            slices = max(1, int(max(0.0, interval_s) * 10))
            for _ in range(slices):
                context.cancel_token.checkpoint("monitor_sleep_slice")
                _time.sleep(max(0.0, interval_s / 10.0))
    return plan


def admin_op_plan(
    admin_service: Any,
    op: str,
    package: str,
    confirmation: Any,
) -> Plan:
    """ADMIN_OP (SC-5, Stage 08): one-shot destructive-capable operation.
    The service performs the confirmation gate itself (R-13 service-side),
    so this plan adds no second gate — double-gating would double-ask."""
    def plan(context: Any) -> "object":
        context.log("info", f"admin operation {op} started for {package}")
        result = getattr(admin_service, op)(package, confirmation)
        context.log("info", f"admin operation {op} finished: {result.message}")
        return result
    return plan


def forensics_job_plan(runner: Callable[[Any], Any],
                       description: str) -> Plan:
    """FORENSICS_OP (Stage 08): a plain closure over a forensic service
    call; per-file progress/log emission happens INSIDE the service when
    a ``context`` is threaded through (extract_app_data path)."""
    def plan(context: Any) -> Any:
        context.log("info", f"forensics op started: {description}")
        result = runner(context)
        if isinstance(result, tuple) and len(result) == 2:
            manifest, report_path = result
            context.log("info", f"forensics op finished: {description}; "
                                f"manifest updated ({len(manifest.files)} files)")
            return manifest
        context.log("info", f"forensics op finished: {description}")
        return result
    return plan


def demo_scan_plan(demo_service: Any) -> Plan:
    """DEMO (SC-10): deterministic fixture bundle; no device involved."""
    def plan(context: Any) -> Any:
        context.log("info", "building demo dataset (no device contacted)")
        bundle = demo_service.scan()
        context.progress(
            bundle.summary.total_apps, bundle.summary.total_apps,
            unit="apps", context="demo dataset ready")
        return bundle
    return plan
