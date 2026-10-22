# Changelog

This project has **not published any release yet** (no Git tag, no GitHub
Release — publication awaits separate maintainer authorization; see
`docs/vscanner-3/STAGE_16_FINAL_RELEASE_REPORT.md` §13). The entries below
record the release-candidate state and the history that produced it.

## 3.0.0a0 — release candidate (2026-10-22 record; not published)

The 3.0 line is a ground-up rewrite of the 2.0-era CLI into one audited engine
behind three surfaces, with Windows packaging.

* **Engine** (`vscanner/`): typed core (models, errors, redaction, paths,
  permission KB) + service layer (ADB clients, config, doctor, registry,
  events/jobs, orchestration, scanning, app inventory, reports, history,
  tools provisioning). Byte-identical three-format report output, verified.
* **Job system**: frozen events, cancellation, watchdog timeouts, mutex
  conflict groups, boundary redaction.
* **Terminal UI** (`ui_terminal`, Textual): theme + dashboards, device
  workspace, scanning/findings, reports, monitoring, forensics, mirroring,
  demo, admin.
* **Desktop app** (`ui_desktop`, PySide6): full parity with the TUI and
  honest-by-construction rules; restrained motion + accessibility pass
  (automated WCAG-AA contrast matrix, accessible names, Escape safety).
* **Windows packaging** (`packaging_windows/`): Nuitka standalone
  `V-Scanner.exe` + per-user Inno Setup installer; version derived from the
  `pyproject.toml` authority; installer lifecycle (install/reinstall/uninstall)
  executed on the build host with user data retained on uninstall.
* **Security**: remediations R-01…R-13 recorded and regression-locked; Stage 15
  found and fixed two release-pipeline defects (D1 staging link-follow leak →
  typed link refusal; D2 dist-closure weakness → exactly-one-exe +
  compiled-closure-only rules).
* **Quality**: suite at 952 passed / 2 honest privilege skips; coverage TOTAL
  74% (13,854 statements); Ruff/mypy/compileall/smoke gates green per stage.
* **Known limitations** (release record §11): unsigned artifacts, Windows 10 /
  clean-VM verification BLOCKED (no environment), several interactive GUI
  walkthroughs untested, dependency lockfile gap, no LICENSE file, monitoring
  test flake investigated but not root-caused (never reproduced).
* **Packaging note:** Windows VERSIONINFO quadruple `3.0.0.0` is derived from
  `3.0.0a0` (`derive_version_quad()`); `AppVerName`/installer filename keep the
  verbatim prerelease suffix.

## 2.0 — legacy line

The pre-3.0 CLI-era product (see the 2.0-era git history up to `abdb4cb` and
`TOOLS_SYSTEM.md` / `QUICK_START.md` / `MASTER_README.md`, kept as historical
references). No versioned changelog was maintained for that line.
