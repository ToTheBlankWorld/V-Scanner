"""SC-9 ReportService: legacy-format export from typed scan bundles.

Compat guarantee (Stage 03 acceptance): feeding the same legacy-shaped
inputs produces BYTE-IDENTICAL HTML/JSON/text files with the legacy
``cli/report_generator.py`` — filenames ``security_report_<ts>.<ext>``,
JSON keys ``device_info``/``summary``/``apps[]``/..., template output
byte-for-byte.

Mechanism: the legacy templates are copied verbatim (``templates.py``);
the legacy-keyed dict projected from a :class:`ScanResultBundle`
(``bundle_to_legacy_dict``) reconstructs exactly what
``create_app_report()``/``create_full_report()`` produced, recomputing
score-derived facts with the same pure knowledge-base functions the engine
runs elsewhere (single source of truth — no duplicated scoring logic).

Filesystem errors and template failures map to :class:`ExportError`; a
fully-failed export raises, a partial one reports what it wrote via
``ExportResult`` (never a silently half-written run).
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from jinja2 import Template

from vscanner.core.errors import ExportError
from vscanner.core.kb.permissions import analyze_permissions, get_sdk_risk
from vscanner.core.models import ExportResult, ReportFormat, ScanResultBundle
from vscanner.services.reports.templates import LEGACY_HTML_TEMPLATE, LEGACY_TEXT_TEMPLATE

__all__ = ["ReportService", "default_report_filename"]

DEFAULT_OUTPUT_DIR = "reports"


def default_report_filename(base: Optional[str] = None, ext: str = ".json") -> str:
    """Legacy filename convention: ``security_report_<YYYYmmdd_HHMMSS><ext>``."""
    if base:
        return base if base.endswith(ext) else base + ext
    return f"security_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}{ext}"


class ReportService:
    """SC-9 export face (synchronous; Stage 04 wraps as an export job)."""

    def __init__(self, output_dir: str = DEFAULT_OUTPUT_DIR) -> None:
        self.output_dir = output_dir

    # ------------------------------------------------------------------ #
    # export face
    # ------------------------------------------------------------------ #

    def export(
        self,
        bundle: ScanResultBundle,
        requested: Optional[Mapping[ReportFormat, Optional[str]]] = None,
        output_dir: Optional[str] = None,
        device_info: Optional[Mapping[str, str]] = None,
    ) -> ExportResult:
        """Export ``bundle`` in the requested formats (all three by default).

        ``device_info`` supplies the legacy ``device_info`` JSON block. When
        a format is requested with an explicit filename it is honored
        verbatim; ``None`` filenames share one generated base timestamp
        (matching legacy ``generate_all``)."""
        formats = dict(requested) if requested is not None else {fmt: None for fmt in ReportFormat}
        target_dir = Path(output_dir or self.output_dir)
        legacy_dict = self.bundle_to_legacy_dict(bundle, device_info=device_info)
        shared_base = datetime.now().strftime("%Y%m%d_%H%M%S")

        try:
            target_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ExportError(
                f"cannot create output directory {target_dir}: {exc}",
                {"output_dir": str(target_dir), "cause": str(exc)},
            ) from exc

        written: Dict[str, str] = {}
        failed: Dict[str, str] = {}
        for fmt in ReportFormat:
            if fmt not in formats:
                continue
            name = formats[fmt] or f"security_report_{shared_base}.{fmt.suffix}"
            try:
                path = self._write_one(legacy_dict, fmt, target_dir, name)
            except ExportError as exc:
                failed[fmt.name] = exc.message
                continue
            written[fmt.name] = str(path)

        if formats and not written:
            raise ExportError(
                "no report format could be written",
                {"failed": "; ".join(f"{k}: {v}" for k, v in failed.items())},
            )
        error_summary = "; ".join(f"{k}: {v}" for k, v in failed.items()) or None
        return ExportResult(ok=bool(written), formats_written=written, error=error_summary)

    def _write_one(self, legacy_dict: Dict[str, Any], fmt: ReportFormat,
                   target_dir: Path, filename: str) -> Path:
        filepath = target_dir / filename
        try:
            if fmt is ReportFormat.JSON:
                with open(filepath, "w", encoding="utf-8") as fh:
                    json.dump(legacy_dict, fh, indent=2, default=str)
            elif fmt is ReportFormat.HTML:
                content = Template(LEGACY_HTML_TEMPLATE).render(report=legacy_dict)
                with open(filepath, "w", encoding="utf-8") as fh:
                    fh.write(content)
            else:
                content = Template(LEGACY_TEXT_TEMPLATE).render(report=legacy_dict)
                with open(filepath, "w", encoding="utf-8") as fh:
                    fh.write(content)
        except OSError as exc:
            raise ExportError(
                f"failed to write {fmt.name} report {filepath}: {exc}",
                {"path": str(filepath), "cause": str(exc)},
            ) from exc
        except Exception as exc:  # template/render failures
            raise ExportError(
                f"failed to render {fmt.name} report {filepath}: {exc}",
                {"path": str(filepath), "cause": str(exc)},
            ) from exc
        return filepath

    # ------------------------------------------------------------------ #
    # legacy-dict projection (byte-parity core)
    # ------------------------------------------------------------------ #

    def bundle_to_legacy_dict(
        self,
        bundle: ScanResultBundle,
        device_info: Optional[Mapping[str, str]] = None,
    ) -> Dict[str, Any]:
        """Project a typed bundle into the exact legacy report dict shape.

        Derived facts (risk score/level, sdk recommendations) are recomputed
        with the same pure KB functions over the app's captured permission
        list, so identical scan inputs give identical report bytes."""
        device_info = dict(device_info or {})
        apps = [self.app_result_to_legacy_dict(r) for r in bundle.apps if r.app is not None]
        high = sum(1 for a in apps if a["risk_level"] in ("CRITICAL", "HIGH"))
        medium = sum(1 for a in apps if a["risk_level"] == "MEDIUM")
        low = sum(1 for a in apps if a["risk_level"] in ("LOW", "INFO"))

        ordered = sorted(apps, key=lambda a: a["risk_score"], reverse=True)
        summary = {
            "most_common_permissions": self._common_permissions(apps),
            "highest_risk_apps": [a["package_name"] for a in ordered[:5]],
            "total_dangerous_permissions": sum(len(a["dangerous_permissions"]) for a in apps),
            "apps_with_insecure_urls": sum(1 for a in apps if a["insecure_urls"]),
        }
        started = bundle.summary.run.started_at or datetime.now()
        return {
            "device_info": device_info,
            "scan_time": started.strftime("%Y-%m-%d %H:%M:%S"),
            "total_apps": len(apps),
            "high_risk_apps": high,
            "medium_risk_apps": medium,
            "low_risk_apps": low,
            "summary": summary,
            "apps": ordered,
        }

    # ------------------------------------------------------------------ #
    # single-app projection
    # ------------------------------------------------------------------ #

    @staticmethod
    def app_result_to_legacy_dict(result: "Any") -> Dict[str, Any]:
        app = result.app
        assert app is not None  # filtered by callers
        perms = list(app.requested_permissions)
        perm_analysis = analyze_permissions(perms)
        sdk_analysis = get_sdk_risk(app.target_sdk or 0, app.min_sdk or 0)

        dangerous_perms = [
            {
                "name": f.title,
                "risk_level": f.severity.value,
                "category": f.tags[0] if f.tags else "Other",
                "description": f.detail,
            }
            for f in result.findings if f.kind.value == "permission_excess"
        ]
        insecure_urls = [
            f.detail for f in result.findings
            if f.kind.value == "insecure_url"
            and f.evidence and f.evidence[0].kind.value == "heuristic_pattern"
        ]
        first_evidence_at = None
        for f in result.findings:
            for ev in f.evidence:
                first_evidence_at = ev.extracted_at
                break
            if first_evidence_at is not None:
                break
        return {
            "package_name": app.package_name,
            "app_name": app.label,
            "version_name": app.version_name or "Unknown",
            "version_code": app.version_code or 0,
            "target_sdk": app.target_sdk or 0,
            "min_sdk": app.min_sdk or 0,
            "permissions": perms,
            "dangerous_permissions": dangerous_perms,
            "risk_score": perm_analysis.get("risk_score", 0),
            "risk_level": (perm_analysis["risk_level"].value
                           if hasattr(perm_analysis.get("risk_level"), "value")
                           else str(perm_analysis.get("risk_level", "INFO"))),
            "sdk_issues": list(sdk_analysis.get("recommendations", [])),
            "insecure_urls": insecure_urls,
            "recommendations": list(perm_analysis.get("recommendations", [])),
            "scan_time": (first_evidence_at.isoformat() if first_evidence_at is not None
                          else datetime.now().isoformat()),
        }

    @staticmethod
    def _common_permissions(apps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Legacy ``_get_common_permissions`` port — same counting, same shape."""
        perm_counts: Dict[str, int] = {}
        for app in apps:
            for perm in app["dangerous_permissions"]:
                name = perm.get("name", perm) if isinstance(perm, dict) else perm
                perm_counts[name] = perm_counts.get(name, 0) + 1
        sorted_perms = sorted(perm_counts.items(), key=lambda x: x[1], reverse=True)
        return [{"permission": p, "count": c} for p, c in sorted_perms[:10]]
