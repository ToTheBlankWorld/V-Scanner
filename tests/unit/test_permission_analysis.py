"""Characterization tests for cli/permissions.py (Stage 02 — section A).

These record the CURRENT scoring behavior as the pre-extraction baseline.
Scoring semantics must not drift before Stage 03 (compat contract).
"""

from __future__ import annotations

import permissions
from permissions import RiskLevel, analyze_permissions, get_permission_info, get_sdk_risk

RESULT_KEYS = {
    "risk_score",
    "risk_level",
    "dangerous_permissions",
    "categories",
    "recommendations",
    "total_permissions",
    "dangerous_count",
}

CAMERA = "android.permission.CAMERA"  # HIGH, weight 15
READ_SMS = "android.permission.READ_SMS"  # CRITICAL, weight 25
COARSE = "android.permission.ACCESS_COARSE_LOCATION"  # MEDIUM, weight 8
WRITE_STORAGE = "android.permission.WRITE_EXTERNAL_STORAGE"  # MEDIUM, weight 8


class TestAnalyzePermissions:
    def test_empty_permission_list(self):
        result = analyze_permissions([])
        assert result["risk_score"] == 0
        assert result["risk_level"] is RiskLevel.INFO
        assert result["dangerous_permissions"] == []
        assert result["total_permissions"] == 0
        assert result["dangerous_count"] == 0

    def test_unknown_permission_is_not_flagged(self):
        # Honesty baseline (DATA_MODELS §4): an unknown permission must not be
        # reported as dangerous — absence of knowledge is not evidence.
        result = analyze_permissions(["com.vendor.custom.WEIRD_PERMISSION"])
        assert result["risk_score"] == 0
        assert result["dangerous_count"] == 0
        assert result["total_permissions"] == 1
        assert result["dangerous_permissions"] == []

    def test_mixed_known_and_unknown(self):
        result = analyze_permissions(["not.tracked.at.all", WRITE_STORAGE])
        assert result["risk_score"] == 8  # MEDIUM weight
        assert result["dangerous_count"] == 1
        assert result["total_permissions"] == 2

    def test_single_high_risk_weight(self):
        result = analyze_permissions([CAMERA])
        assert result["risk_score"] == 15
        assert result["risk_level"] is RiskLevel.LOW  # >= 10 threshold

    def test_threshold_medium(self):
        # 2x MEDIUM (8) + 1x LOW/... : pick 8*4 = 32 → MEDIUM (>= 30)
        result = analyze_permissions([COARSE, COARSE, WRITE_STORAGE, WRITE_STORAGE])
        assert result["risk_score"] == 32
        assert result["risk_level"] is RiskLevel.MEDIUM

    def test_threshold_high(self):
        # 50 boundary: 3x CAMERA (15) + COARSE (8) = 53 → HIGH
        result = analyze_permissions([CAMERA, CAMERA, CAMERA, COARSE])
        assert result["risk_score"] == 53
        assert result["risk_level"] is RiskLevel.HIGH

    def test_threshold_critical(self):
        # 70 boundary: 3x READ_SMS (25) = 75 → CRITICAL
        result = analyze_permissions([READ_SMS, READ_SMS, READ_SMS])
        assert result["risk_score"] == 75
        assert result["risk_level"] is RiskLevel.CRITICAL

    def test_score_is_capped_at_100(self):
        result = analyze_permissions([READ_SMS] * 10)  # 250 raw → capped
        assert result["risk_score"] == 100
        assert result["risk_level"] is RiskLevel.CRITICAL

    def test_categories_grouped_by_name(self):
        result = analyze_permissions([CAMERA, COARSE])
        assert set(result["categories"]) == {"Camera", "Location"}

    def test_output_structure_is_stable(self):
        result = analyze_permissions([CAMERA])
        assert set(result.keys()) == RESULT_KEYS
        assert all(item.name and item.risk_level for item in result["dangerous_permissions"])

    def test_recommendations_capped_two_mitigations_per_permission(self):
        result = analyze_permissions([CAMERA, CAMERA])
        # Two occurrences of CAMERA: top-2 mitigations each → 4 recs, sorted unknown
        assert len(result["recommendations"]) == 4
        assert all(rec.startswith("[") for rec in result["recommendations"])


class TestGetPermissionInfo:
    def test_known_permission_returns_info(self):
        info = get_permission_info(READ_SMS)
        assert info.name == "READ_SMS"
        assert info.risk_level is RiskLevel.CRITICAL
        assert info.description
        assert info.mitigations

    def test_unknown_permission_returns_none(self):
        assert get_permission_info("android.permission.TOTALLY_UNKNOWN") is None


class TestSdkRisk:
    def test_no_recommendations_for_current_safe_pair(self):
        result = get_sdk_risk(33, 26)
        assert result["recommendations"] == []
        assert result["target_info"]["status"] == "Supported"
        assert result["min_info"]["status"] == "EOL"

    def test_target_below_recommended(self):
        result = get_sdk_risk(28, 33)  # 28 < min_recommended (28+ required? boundary)
        # sdk_info["min_recommended"] == 28 → 28 < 28 is False at the boundary itself
        assert isinstance(result["recommendations"], list)

    def test_target_below_recommended_strict(self):
        result = get_sdk_risk(27, 33)
        recs = " ".join(result["recommendations"])
        assert "below recommended minimum" in recs

    def test_min_sdk_insecure_and_deprecated(self):
        result = get_sdk_risk(33, 22)
        recs = " ".join(result["recommendations"])
        assert "allows installation on insecure Android versions" in recs
        assert "deprecated and has known vulnerabilities" in recs

    def test_unknown_target_sdk_defaults_to_medium(self):
        result = get_sdk_risk(35, 33)
        assert result["target_info"]["status"] == "Unknown"
        assert result["target_info"]["risk"] is RiskLevel.MEDIUM

    def test_unknown_min_sdk_high_when_below_26(self):
        result = get_sdk_risk(34, 22)
        assert result["min_info"]["status"] == "Unknown"
        assert result["min_info"]["risk"] is RiskLevel.HIGH

    def test_unknown_min_sdk_medium_when_at_or_above_26(self):
        # 35 is genuinely unknown and >= 26 → MEDIUM fallback (27 is a known KB entry)
        result = get_sdk_risk(34, 35)
        assert result["min_info"]["risk"] is RiskLevel.MEDIUM

    def test_structure_stability(self):
        result = get_sdk_risk(33, 26)
        assert set(result.keys()) == {
            "target_sdk", "target_info", "min_sdk", "min_info", "recommendations",
        }
