"""DemoService — SC-10 deterministic demo dataset (Stage 08).

Ports the legacy ``demo_mode`` output shape into a typed
:class:`~vscanner.core.models.ScanResultBundle`:

* deterministic fixture (same apps/findings every call — honest because it
  is *labeled* demo, not because it looks like a device);
* every finding carries INFORMATIONAL severity + a provenance note
  marking it demo data; the bundle's device serial is ``None``;
* no device, transport, or network is ever created here (local-first,
  honest: the demo screen must make that unmissable);
* UIs label DEMO prominently; reports are only written when the user
  explicitly exports (SC-10 legacy preservation note).
"""

from __future__ import annotations

from typing import Optional

from vscanner.core.models import (
    AppInfo,
    AppScanResult,
    Evidence,
    EvidenceKind,
    Finding,
    FindingCategory,
    FindingSeverity,
    Remediation,
    ScanConfiguration,
    ScanKind,
    ScanLifecycleState,
    ScanRequest,
    ScanResultBundle,
    ScanRun,
    ScanSummary,
    make_finding,
)

__all__ = ["DemoService", "DEMO_NOTE"]

DEMO_NOTE = "demo fixture — no device was contacted"

_APPS = (
    ("com.demo.chat", "Demo Chat", "GET_ACCOUNTS,READ_CONTACTS,INTERNET", 27, 21),
    ("com.demo.notes", "Demo Notes", "INTERNET,ACCESS_FINE_LOCATION", 30, 24),
    ("com.demo.tools", "Demo Tools", "WRITE_EXTERNAL_STORAGE,INTERNET", 25, 19),
)


class DemoService:
    """Deterministic demo bundle generator (SC-10)."""

    def scan(self) -> ScanResultBundle:
        started = self._fixed_start()
        apps = []
        for package, label, perms, target_sdk, min_sdk in _APPS:
            app = AppInfo(
                package_name=package, label=label,
                requested_permissions=tuple(perms.split(",")),
                target_sdk=target_sdk, min_sdk=min_sdk,
            )
            apps.append(
                AppScanResult(app=app, findings=self._findings(app, package)))
        results = tuple(apps)
        total_findings = sum(len(r.findings) for r in results)
        run = ScanRun(
            request=ScanRequest(
                kind=ScanKind.SINGLE_APP, config=ScanConfiguration()),
            state=ScanLifecycleState.COMPLETED,
            started_at=started, finished_at=self._fixed_end(),
        )
        summary = ScanSummary(
            run=run,
            total_apps=len(results),
            findings_total=total_findings,
            demo=True,
        )
        return ScanResultBundle(summary=summary, apps=results)

    # ------------------------------------------------------------------ #
    # static fixture findings (INFORMATIONAL only — demo shows shapes, not
    # a security verdict; severity stays honest-by-construction)
    # ------------------------------------------------------------------ #

    def _findings(self, app: AppInfo, package: str) -> tuple:
        if package == "com.demo.chat":
            finding = make_finding(
                kind=FindingCategory.PERMISSION_EXCESS,
                severity=FindingSeverity.INFO,
                title="[DEMO] Contacts + account permissions example",
                detail=(
                    "The demo fixture pairs GET_ACCOUNTS with "
                    "READ_CONTACTS to show how combined contact-reach "
                    "permissions render. Demo data — not a device "
                    "observation."
                ),
                evidence=(
                    Evidence.of(
                        EvidenceKind.INFORMATIONAL,
                        description=f"demo fixture permissions for {package}",
                        source="demo fixture (no device)",
                    ),
                ),
                remediation=Remediation(
                    "request the narrowest contact permissions for the "
                    "feature actually needed",
                    category=FindingCategory.INFO_NOTE,
                ),
                app=app,
                device_serial=None,
            )
            return finding,
        if package == "com.demo.notes":
            finding = make_finding(
                kind=FindingCategory.INSECURE_URL,
                severity=FindingSeverity.INFO,
                title="[DEMO] Cleartext endpoint example",
                detail=(
                    "A demo cleartext-config endpoint appears here so the "
                    "findings explorer can show an INSECURE_URL row shape. "
                    "DEMO DATA — nothing was fetched or observed."
                ),
                evidence=(
                    Evidence.of(
                        EvidenceKind.HEURISTIC_PATTERN,
                        description="demo fixture placeholder URL",
                        source="demo fixture (no device)",
                    ),
                ),
                app=app,
                device_serial=None,
            )
            return finding,
        return (make_finding(
            kind=FindingCategory.INFO_NOTE,
            severity=FindingSeverity.INFO,
            title="[DEMO] Informational row example",
            detail=(
                "Storage permissions on a legacy SDK combine to show an "
                "INFO severity row with remediation text. DEMO fixture — "
                "no evidence of a real device."
            ),
            evidence=(
                Evidence.of(
                    EvidenceKind.INFORMATIONAL,
                    description=f"demo fixture information row for {package}",
                    source="demo fixture (no device)",
                ),
            ),
            remediation=Remediation(
                "scope storage permissions to the media the app needs",
                category=FindingCategory.INFO_NOTE,
            ),
            app=app,
            device_serial=None,
        ),)

    # fixed clock values keep the fixture deterministic (SC-10)
    @staticmethod
    def _fixed_start():
        from datetime import datetime, timezone
        return datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

    @staticmethod
    def _fixed_end():
        from datetime import datetime, timezone
        return datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


def _demo_note_guard(note: Optional[str]) -> str:  # pragma: no cover
    return note or DEMO_NOTE
