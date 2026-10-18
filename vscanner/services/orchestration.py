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
