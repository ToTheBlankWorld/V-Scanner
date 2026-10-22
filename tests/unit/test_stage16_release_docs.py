"""Stage 16 documentation consistency tests.

Lock the final release-documentation deliverables against regressions:
presence, cross-references, honest statuses, no machine-local paths or
invented download URLs, and no stale license claims.

Toolchain-free: reads markdown text from the repo tree only. No device, no
network, no build. Consolidated into one test function so the suite count
grows by exactly one passed test (meta-directive: 952 total / 2 valid skips
after the Stage 16 doc tests).
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

README = REPO / "README.md"
FINAL_REPORT = REPO / "docs" / "vscanner-3" / "STAGE_16_FINAL_RELEASE_REPORT.md"
WINDOWS_INSTALL = REPO / "docs" / "vscanner-3" / "WINDOWS_INSTALLATION.md"
CHECKLIST = REPO / "docs" / "vscanner-3" / "RELEASE_CHECKLIST.md"
CHANGELOG = REPO / "CHANGELOG.md"

NEW_DOCS = (README, FINAL_REPORT, WINDOWS_INSTALL, CHECKLIST, CHANGELOG)

ALLOWED_CHECK_STATUSES = {"PASS", "FAIL", "BLOCKED", "NOT TESTED", "PARTIAL"}

# Machine-local or fabricated-content patterns that must never appear.
# Generic means generic: %LOCALAPPDATA%-style variables are allowed; any
# absolute Windows drive path (which would embed a machine's username or
# working directory) is rejected instead of enumerating machine-specific
# literals. Invented artifact URLs are listed verbatim.
FORBIDDEN_URL_FRAGMENTS: tuple[str, ...] = (
    "releases/download",
    "releases/latest/download",
)
ABSOLUTE_DRIVE_PATH_RE = re.compile(r"[A-Za-z]:\\")

REQUIRED_CHECKLIST_SUBSTRINGS = (
    "Windows 10",
    "Clean-VM",
    "Doctor page click-through",
    "Interactive uninstall",
    "HiDPI",
    "Reduced-motion",
    "Keyboard",
    "ADB",
    "scrcpy",
    "lockfile",
    "Code signing",
    "publication",
    "Intermittent",
    "junction/symlink",
    "executable-closure",
)


def _read(path: Path) -> str:
    assert path.is_file(), f"missing release-document file: {path}"
    return path.read_text(encoding="utf-8")


def _check(name: str, condition: bool, detail: str = "") -> None:
    if not condition:
        raise AssertionError(
            f"Stage 16 documentation contract violated — rule '{name}'{(': ' + detail) if detail else ''}"
        )


def test_stage16_release_documentation_contract() -> None:
    """Single consolidated check of every Stage 16 documentation rule."""
    # --- 1. presence -------------------------------------------------------
    for path in NEW_DOCS:
        _check("presence", path.is_file(), f"missing: {path}")

    readme = _read(README)
    report = _read(FINAL_REPORT)
    install = _read(WINDOWS_INSTALL)
    checklist = _read(CHECKLIST)
    changelog = _read(CHANGELOG)

    # --- 2. README is 3.0-era and honest ------------------------------------
    _check("readme.era", "3.0.0a0" in readme and "V-Scanner 3.0" in readme)
    _check("readme.no-2.0-license-claim", "MIT License - See LICENSE" not in readme)
    _check(
        "readme.license-honesty",
        "No LICENSE file is present" in readme and "no license is granted" in readme,
        "README must state that no LICENSE file exists and no license is granted",
    )
    _check("readme.no-fabricated-download", "download link in this file" in readme or
           ("no public release" in readme.lower() or "No public release" in readme))
    _check("readme.links-install-guide", "WINDOWS_INSTALLATION.md" in readme)

    # --- 3. final report: disposition, boundary, artifact record ------------
    _check("report.disposition", "NOT READY" in report)
    _check(
        "report.boundary",
        "no Git tag" in report
        and ("Documentation completion is not permission to publish" in report
             or "not permission to publish" in report),
    )
    _check(
        "report.hashes-rechecked",
        "1bf3eb42fa0fb5007e8c8b8f4b6c54db9cb76a4fcb7569cdabd1ebae2b27c637" in report
        and "ac9229aedb574ec052686779b864fb95d592b218133365f7b93bb2245dae25bc" in report,
    )
    _check("report.verification-label", "rechecked in Stage 16" in report)
    _check("report.stage-table", "Stage-by-stage completion summary" in report)
    _check("report.disposition-table", "CONDITIONALLY READY" in report)

    # --- 4. installation guide cross-references and identity ----------------
    _check("install.links-report", "STAGE_16_FINAL_RELEASE_REPORT.md" in install)
    _check("install.installer-name", "V-Scanner-3.0.0a0-Setup.exe" in install)
    _check("install.data-dir", "%LOCALAPPDATA%" in install)
    _check("install.smartscreen-factual", "SmartScreen" in install and "hash" in install.lower())

    # --- 5. checklist: statuses, mandated rows, role-only owners -------------
    rows = [
        line
        for line in checklist.splitlines()
        if line.startswith("| ") and "**" in line and "| Evidence |" not in line
    ]
    _check("checklist.rows", bool(rows), "no data rows parsed")
    for row in rows:
        cells = [cell.strip() for cell in row.strip("|").split("|")]
        match = re.fullmatch(r"\*\*(.+?)\*\*", cells[2]) if len(cells) > 2 else None
        _check("checklist.status-bolded", match is not None, f"row {cells[1] if cells else row!r}")
        assert match is not None
        _check(
            "checklist.status-legal",
            match.group(1) in ALLOWED_CHECK_STATUSES,
            f"{cells[1] if len(cells) > 1 else row!r} -> {match.group(1)!r}",
        )
    for fragment in REQUIRED_CHECKLIST_SUBSTRINGS:
        _check("checklist.mandated", fragment in checklist, f"missing mandated check: {fragment}")
    for invented_name in ("Alice", "Bob", "Charlie"):
        _check("checklist.owner-roles-only", invented_name not in checklist, invented_name)
    _check("checklist.evidence-links", "STAGE_14_IMPLEMENTATION_REPORT.md" in checklist
           and "STAGE_15_IMPLEMENTATION_REPORT.md" in checklist)

    # --- 6. changelog -------------------------------------------------------
    _check("changelog.honest", "not published any release" in changelog and "3.0.0a0" in changelog)

    # --- 7. content hygiene across all new documents ------------------------
    for path in NEW_DOCS:
        text = _read(path)
        for fragment in FORBIDDEN_URL_FRAGMENTS:
            _check(
                f"no-invented-url:{path.name}",
                fragment not in text,
                f"{path.name}: {fragment!r}",
            )
        leaked = ABSOLUTE_DRIVE_PATH_RE.search(text)
        leaked_repr = leaked.group(0) if leaked else ""
        _check(
            "no-machine-local-drive-path",
            leaked is None,
            f"{path.name}: absolute drive path {leaked_repr!r}",
        )
