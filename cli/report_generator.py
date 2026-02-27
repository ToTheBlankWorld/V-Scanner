"""
Report Generator Module for Android Security Scanner

Generates HTML, JSON, and text reports for security assessments.
"""

import json
import os
from datetime import datetime
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
from jinja2 import Template

from permissions import RiskLevel, PermissionInfo


@dataclass
class AppSecurityReport:
    """Security report for a single app."""
    package_name: str
    app_name: str
    version_name: str
    version_code: int
    target_sdk: int
    min_sdk: int
    permissions: List[str]
    dangerous_permissions: List[Dict]
    risk_score: int
    risk_level: str
    sdk_issues: List[str]
    insecure_urls: List[str]
    recommendations: List[str]
    scan_time: str


@dataclass
class FullScanReport:
    """Complete security scan report."""
    device_info: Dict
    scan_time: str
    total_apps: int
    high_risk_apps: int
    medium_risk_apps: int
    low_risk_apps: int
    apps: List[AppSecurityReport]
    summary: Dict


HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Mobile Security Scan Report</title>
    <style>
        :root {
            --bg-dark: #1a1a2e;
            --bg-card: #16213e;
            --text-primary: #eaeaea;
            --text-secondary: #a0a0a0;
            --accent: #0f4c75;
            --critical: #e74c3c;
            --high: #e67e22;
            --medium: #f39c12;
            --low: #27ae60;
            --info: #3498db;
        }
        
        * { box-sizing: border-box; margin: 0; padding: 0; }
        
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: var(--bg-dark);
            color: var(--text-primary);
            line-height: 1.6;
            padding: 20px;
        }
        
        .container { max-width: 1400px; margin: 0 auto; }
        
        header {
            background: linear-gradient(135deg, var(--accent), var(--bg-card));
            padding: 30px;
            border-radius: 15px;
            margin-bottom: 30px;
            text-align: center;
        }
        
        header h1 { font-size: 2.5em; margin-bottom: 10px; }
        header p { color: var(--text-secondary); }
        
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }
        
        .stat-card {
            background: var(--bg-card);
            padding: 25px;
            border-radius: 12px;
            text-align: center;
            border-left: 4px solid var(--accent);
        }
        
        .stat-card.critical { border-color: var(--critical); }
        .stat-card.high { border-color: var(--high); }
        .stat-card.medium { border-color: var(--medium); }
        .stat-card.low { border-color: var(--low); }
        
        .stat-number {
            font-size: 3em;
            font-weight: bold;
        }
        
        .stat-label {
            color: var(--text-secondary);
            text-transform: uppercase;
            font-size: 0.85em;
            letter-spacing: 1px;
        }
        
        .app-card {
            background: var(--bg-card);
            border-radius: 12px;
            margin-bottom: 20px;
            overflow: hidden;
            border: 1px solid rgba(255,255,255,0.1);
        }
        
        .app-header {
            padding: 20px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid rgba(255,255,255,0.1);
            cursor: pointer;
        }
        
        .app-header:hover { background: rgba(255,255,255,0.05); }
        
        .app-name {
            font-size: 1.3em;
            font-weight: 600;
        }
        
        .app-package {
            color: var(--text-secondary);
            font-size: 0.9em;
            font-family: monospace;
        }
        
        .risk-badge {
            padding: 8px 16px;
            border-radius: 20px;
            font-weight: bold;
            font-size: 0.85em;
            text-transform: uppercase;
        }
        
        .risk-CRITICAL { background: var(--critical); }
        .risk-HIGH { background: var(--high); }
        .risk-MEDIUM { background: var(--medium); color: #333; }
        .risk-LOW { background: var(--low); }
        .risk-INFO { background: var(--info); }
        
        .app-details {
            padding: 20px;
            display: none;
        }
        
        .app-details.active { display: block; }
        
        .detail-section {
            margin-bottom: 20px;
        }
        
        .detail-section h4 {
            color: var(--accent);
            margin-bottom: 10px;
            padding-bottom: 5px;
            border-bottom: 1px solid rgba(255,255,255,0.1);
        }
        
        .permission-list {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
        }
        
        .permission-tag {
            background: rgba(255,255,255,0.1);
            padding: 6px 12px;
            border-radius: 6px;
            font-size: 0.85em;
            font-family: monospace;
        }
        
        .permission-tag.dangerous {
            background: rgba(231, 76, 60, 0.3);
            border: 1px solid var(--critical);
        }
        
        .recommendation {
            background: rgba(52, 152, 219, 0.2);
            padding: 12px 16px;
            border-radius: 8px;
            margin-bottom: 8px;
            border-left: 3px solid var(--info);
        }
        
        .sdk-info {
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 15px;
        }
        
        .sdk-box {
            background: rgba(255,255,255,0.05);
            padding: 15px;
            border-radius: 8px;
        }
        
        .sdk-label { color: var(--text-secondary); font-size: 0.85em; }
        .sdk-value { font-size: 1.2em; font-weight: bold; }
        
        .risk-meter {
            width: 100%;
            height: 10px;
            background: rgba(255,255,255,0.1);
            border-radius: 5px;
            overflow: hidden;
            margin-top: 10px;
        }
        
        .risk-meter-fill {
            height: 100%;
            transition: width 0.3s ease;
        }
        
        .insecure-url {
            font-family: monospace;
            background: rgba(231, 76, 60, 0.2);
            padding: 8px 12px;
            border-radius: 6px;
            margin-bottom: 6px;
            word-break: break-all;
        }
        
        footer {
            text-align: center;
            padding: 30px;
            color: var(--text-secondary);
            font-size: 0.9em;
        }
        
        @media (max-width: 768px) {
            .app-header { flex-direction: column; gap: 10px; }
            .sdk-info { grid-template-columns: 1fr; }
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>🔒 Mobile Security Scan Report</h1>
            <p>Generated: {{ report.scan_time }}</p>
            <p>Device: {{ report.device_info.model }} (Android {{ report.device_info.android_version }})</p>
        </header>
        
        <div class="stats-grid">
            <div class="stat-card">
                <div class="stat-number">{{ report.total_apps }}</div>
                <div class="stat-label">Total Apps Scanned</div>
            </div>
            <div class="stat-card critical">
                <div class="stat-number">{{ report.high_risk_apps }}</div>
                <div class="stat-label">High Risk Apps</div>
            </div>
            <div class="stat-card medium">
                <div class="stat-number">{{ report.medium_risk_apps }}</div>
                <div class="stat-label">Medium Risk Apps</div>
            </div>
            <div class="stat-card low">
                <div class="stat-number">{{ report.low_risk_apps }}</div>
                <div class="stat-label">Low Risk Apps</div>
            </div>
        </div>
        
        <h2 style="margin-bottom: 20px;">📱 Application Security Details</h2>
        
        {% for app in report.apps %}
        <div class="app-card">
            <div class="app-header" onclick="toggleDetails('app-{{ loop.index }}')">
                <div>
                    <div class="app-name">{{ app.app_name }}</div>
                    <div class="app-package">{{ app.package_name }}</div>
                </div>
                <div style="display: flex; align-items: center; gap: 15px;">
                    <div>
                        <div style="font-size: 0.8em; color: var(--text-secondary);">Risk Score</div>
                        <div style="font-size: 1.5em; font-weight: bold;">{{ app.risk_score }}/100</div>
                    </div>
                    <span class="risk-badge risk-{{ app.risk_level }}">{{ app.risk_level }}</span>
                </div>
            </div>
            
            <div class="app-details" id="app-{{ loop.index }}">
                <div class="detail-section">
                    <h4>📊 Risk Assessment</h4>
                    <div class="risk-meter">
                        <div class="risk-meter-fill" style="width: {{ app.risk_score }}%; background: {% if app.risk_score >= 70 %}var(--critical){% elif app.risk_score >= 50 %}var(--high){% elif app.risk_score >= 30 %}var(--medium){% else %}var(--low){% endif %};"></div>
                    </div>
                </div>
                
                <div class="detail-section">
                    <h4>📦 SDK Information</h4>
                    <div class="sdk-info">
                        <div class="sdk-box">
                            <div class="sdk-label">Target SDK</div>
                            <div class="sdk-value">API {{ app.target_sdk }}</div>
                        </div>
                        <div class="sdk-box">
                            <div class="sdk-label">Minimum SDK</div>
                            <div class="sdk-value">API {{ app.min_sdk }}</div>
                        </div>
                    </div>
                    {% if app.sdk_issues %}
                    <div style="margin-top: 15px;">
                        {% for issue in app.sdk_issues %}
                        <div class="recommendation">⚠️ {{ issue }}</div>
                        {% endfor %}
                    </div>
                    {% endif %}
                </div>
                
                {% if app.dangerous_permissions %}
                <div class="detail-section">
                    <h4>⚠️ Dangerous Permissions ({{ app.dangerous_permissions|length }})</h4>
                    <div class="permission-list">
                        {% for perm in app.dangerous_permissions %}
                        <span class="permission-tag dangerous" title="{{ perm.description }}">{{ perm.name }}</span>
                        {% endfor %}
                    </div>
                </div>
                {% endif %}
                
                {% if app.insecure_urls %}
                <div class="detail-section">
                    <h4>🔓 Insecure URLs Found</h4>
                    {% for url in app.insecure_urls %}
                    <div class="insecure-url">{{ url }}</div>
                    {% endfor %}
                </div>
                {% endif %}
                
                {% if app.recommendations %}
                <div class="detail-section">
                    <h4>💡 Recommendations</h4>
                    {% for rec in app.recommendations %}
                    <div class="recommendation">{{ rec }}</div>
                    {% endfor %}
                </div>
                {% endif %}
            </div>
        </div>
        {% endfor %}
        
        <footer>
            <p>Generated by V Scanner - Mobile Security Suite</p>
            <p>© 2024 Mobile Security Tools</p>
        </footer>
    </div>
    
    <script>
        function toggleDetails(id) {
            const details = document.getElementById(id);
            details.classList.toggle('active');
        }
        
        // Expand high-risk apps by default
        document.querySelectorAll('.risk-CRITICAL, .risk-HIGH').forEach((badge, i) => {
            const card = badge.closest('.app-card');
            const details = card.querySelector('.app-details');
            if (details && i < 5) details.classList.add('active');
        });
    </script>
</body>
</html>
"""


TEXT_TEMPLATE = """
================================================================================
                      MOBILE SECURITY SCAN REPORT
================================================================================

Scan Time: {{ report.scan_time }}
Device: {{ report.device_info.model }} (Android {{ report.device_info.android_version }})

--------------------------------------------------------------------------------
                              SUMMARY
--------------------------------------------------------------------------------

Total Apps Scanned:     {{ report.total_apps }}
High Risk Apps:         {{ report.high_risk_apps }}
Medium Risk Apps:       {{ report.medium_risk_apps }}
Low Risk Apps:          {{ report.low_risk_apps }}

--------------------------------------------------------------------------------
                          APP DETAILS
--------------------------------------------------------------------------------
{% for app in report.apps %}

┌─────────────────────────────────────────────────────────────────────────────┐
│ {{ app.app_name }} ({{ app.package_name }})
├─────────────────────────────────────────────────────────────────────────────┤
│ Version: {{ app.version_name }} ({{ app.version_code }})
│ Risk Level: {{ app.risk_level }} (Score: {{ app.risk_score }}/100)
│ Target SDK: {{ app.target_sdk }} | Min SDK: {{ app.min_sdk }}
│
│ Dangerous Permissions: {{ app.dangerous_permissions|length }}
{% for perm in app.dangerous_permissions %}
│   • {{ perm.name }} [{{ perm.risk_level }}]
│     {{ perm.description }}
{% endfor %}
{% if app.sdk_issues %}
│
│ SDK Issues:
{% for issue in app.sdk_issues %}
│   ⚠ {{ issue }}
{% endfor %}
{% endif %}
{% if app.insecure_urls %}
│
│ Insecure URLs:
{% for url in app.insecure_urls %}
│   ✗ {{ url }}
{% endfor %}
{% endif %}
{% if app.recommendations %}
│
│ Recommendations:
{% for rec in app.recommendations %}
│   → {{ rec }}
{% endfor %}
{% endif %}
└─────────────────────────────────────────────────────────────────────────────┘
{% endfor %}

================================================================================
                    Generated by V Scanner - Mobile Security Suite
================================================================================
"""


class ReportGenerator:
    """Generates security reports in multiple formats."""
    
    def __init__(self, output_dir: str = "reports"):
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)
    
    def generate_html(self, report: FullScanReport, filename: str = None) -> str:
        """Generate HTML report."""
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"security_report_{timestamp}.html"
        
        template = Template(HTML_TEMPLATE)
        html_content = template.render(report=report)
        
        filepath = os.path.join(self.output_dir, filename)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        return filepath
    
    def generate_json(self, report: FullScanReport, filename: str = None) -> str:
        """Generate JSON report."""
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"security_report_{timestamp}.json"
        
        # Convert to dict
        report_dict = {
            "device_info": report.device_info,
            "scan_time": report.scan_time,
            "total_apps": report.total_apps,
            "high_risk_apps": report.high_risk_apps,
            "medium_risk_apps": report.medium_risk_apps,
            "low_risk_apps": report.low_risk_apps,
            "summary": report.summary,
            "apps": [asdict(app) if hasattr(app, '__dataclass_fields__') else app for app in report.apps]
        }
        
        filepath = os.path.join(self.output_dir, filename)
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(report_dict, f, indent=2, default=str)
        
        return filepath
    
    def generate_text(self, report: FullScanReport, filename: str = None) -> str:
        """Generate plain text report."""
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"security_report_{timestamp}.txt"
        
        template = Template(TEXT_TEMPLATE)
        text_content = template.render(report=report)
        
        filepath = os.path.join(self.output_dir, filename)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(text_content)
        
        return filepath
    
    def generate_all(self, report: FullScanReport, base_filename: str = None) -> Dict[str, str]:
        """Generate reports in all formats."""
        if base_filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            base_filename = f"security_report_{timestamp}"
        
        return {
            "html": self.generate_html(report, f"{base_filename}.html"),
            "json": self.generate_json(report, f"{base_filename}.json"),
            "text": self.generate_text(report, f"{base_filename}.txt")
        }


def create_app_report(
    package_name: str,
    app_name: str,
    version_name: str,
    version_code: int,
    target_sdk: int,
    min_sdk: int,
    permissions: List[str],
    permission_analysis: Dict,
    sdk_analysis: Dict,
    insecure_urls: List[str] = None
) -> AppSecurityReport:
    """Create an AppSecurityReport from analysis results."""
    dangerous_perms = []
    for perm in permission_analysis.get("dangerous_permissions", []):
        if isinstance(perm, PermissionInfo):
            dangerous_perms.append({
                "name": perm.name,
                "risk_level": perm.risk_level.value,
                "category": perm.category,
                "description": perm.description
            })
        else:
            dangerous_perms.append(perm)
    
    return AppSecurityReport(
        package_name=package_name,
        app_name=app_name,
        version_name=version_name,
        version_code=version_code,
        target_sdk=target_sdk,
        min_sdk=min_sdk,
        permissions=permissions,
        dangerous_permissions=dangerous_perms,
        risk_score=permission_analysis.get("risk_score", 0),
        risk_level=permission_analysis.get("risk_level", RiskLevel.INFO).value if hasattr(permission_analysis.get("risk_level"), "value") else str(permission_analysis.get("risk_level", "INFO")),
        sdk_issues=sdk_analysis.get("recommendations", []),
        insecure_urls=insecure_urls or [],
        recommendations=permission_analysis.get("recommendations", []),
        scan_time=datetime.now().isoformat()
    )


def create_full_report(
    device_info: Dict,
    app_reports: List[AppSecurityReport]
) -> FullScanReport:
    """Create a FullScanReport from app reports."""
    high_risk = sum(1 for app in app_reports if app.risk_level in ["CRITICAL", "HIGH"])
    medium_risk = sum(1 for app in app_reports if app.risk_level == "MEDIUM")
    low_risk = sum(1 for app in app_reports if app.risk_level in ["LOW", "INFO"])
    
    # Sort by risk score descending
    sorted_apps = sorted(app_reports, key=lambda x: x.risk_score, reverse=True)
    
    summary = {
        "most_common_permissions": _get_common_permissions(app_reports),
        "highest_risk_apps": [app.package_name for app in sorted_apps[:5]],
        "total_dangerous_permissions": sum(len(app.dangerous_permissions) for app in app_reports),
        "apps_with_insecure_urls": sum(1 for app in app_reports if app.insecure_urls)
    }
    
    return FullScanReport(
        device_info=device_info,
        scan_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        total_apps=len(app_reports),
        high_risk_apps=high_risk,
        medium_risk_apps=medium_risk,
        low_risk_apps=low_risk,
        apps=sorted_apps,
        summary=summary
    )


def _get_common_permissions(app_reports: List[AppSecurityReport]) -> List[Dict]:
    """Get most common dangerous permissions across all apps."""
    perm_counts = {}
    for app in app_reports:
        for perm in app.dangerous_permissions:
            name = perm.get("name", perm) if isinstance(perm, dict) else perm.name
            perm_counts[name] = perm_counts.get(name, 0) + 1
    
    sorted_perms = sorted(perm_counts.items(), key=lambda x: x[1], reverse=True)
    return [{"permission": p, "count": c} for p, c in sorted_perms[:10]]
