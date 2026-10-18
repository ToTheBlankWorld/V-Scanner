# V-Scanner 3.0 — Target Architecture Proposal

**Status: PROPOSAL ONLY — not implemented in Stage 00.** This document defines the target shape that Stages 01–16 will build toward. Nothing in this file authorizes code changes yet.

## 1. Design principles

1. **One engine, two frontends.** Every scanning, device, report, and provisioning capability lives in a single Python application-service layer. The Textual TUI and the PySide6 desktop app are thin, replaceable views over the same services.
2. **Legacy CLI keeps working.** `python cli/main.py` and `python cli/scanner.py <cmd>` continue to function during and after migration, wired onto the same services (Stage 02 regression contract).
3. **No new infrastructure.** No network server, no cloud accounts, no telemetry, no hosted backend. All data stays local. (Any future sync feature requires a written requirement first.)
4. **Explicit boundaries.** UI tools never call ADB directly; services never import `rich`/`textual`/`PySide6`.
5. **Typed data.** Findings, devices, jobs, and reports are dataclasses/Pydantic-style models, not dicts passed across module lines.
6. **Honest results.** No fabricated data (kills the "landed" sensor fallback pattern of legacy `get_sensor_values_live` Method 3), no optimistic root status, no fake app labels where real labels are obtainable.

## 2. Layered structure (suggested package root `vscanner/`)

```
vscanner/                      # new package (Stage 03+); legacy cli/ untouched until migration completes
├── core/                      # domain models — no imports outside stdlib
│   ├── models.py              # Device, AppInfo, Finding, ScanResult, ScanSummary, ReportBundle
│   └── enums.py               # RiskLevel, FindingCategory, JobState, ConnectivityState
├── services/                  # application services — pure orchestration, NO UI imports
│   ├── adb/
│   │   ├── adb_client.py      # low-level process wrapper (timeout, encoding, binary-safe exec)
│   │   ├── devices.py         # discovery, selection, connection-state watching
│   │   └── device_info.py     # property/dumpsys collection → DeviceProfile
│   ├── scanning/
│   │   ├── package_scan.py    # inventory + package info
│   │   ├── permission_analysis.py  # port of permissions.py knowledge base
│   │   ├── sdk_risk.py
│   │   ├── apk_analysis.py    # deep scan (pull-or-stream APK, real string extraction)
│   │   └── scanner.py         # orchestration of findings per app / per device
│   ├── monitoring/
│   │   ├── hardware_usage.py  # camera/mic/location polling (dumpsys-based, honest confidence)
│   │   └── sensors.py         # available-sensor listing, real readings only
│   ├── forensics/
│   │   ├── case_store.py      # case dirs, metadata, manifest of artifacts (hash list)
│   │   └── extractors.py      # databases/prefs/files/logs/packages/processes/wifi (byte-safe)
│   ├── tools/
│   │   └── provisioning.py    # port of tools_manager (downloads, verify, progress events)
│   ├── reports/
│   │   ├── html_report.py     # Jinja2 templates moved out of source into package templates
│   │   ├── json_report.py
│   │   ├── text_report.py
│   │   └── io_compat.py       # legacy filename/directory behavior
│   ├── config.py              # versioned, validated config (dataclass + atomic save); adb path overrides
│   └── jobs.py                # job system (see §4)
├── ui_terminal/               # Textual + Rich frontend (Stages 05–08)
│   ├── app.py                 # Textual app shell, theming, key bindings (Claude/OpenCode-style)
│   ├── screens/…              # device workspace, scan dashboards, findings, forensics
│   └── widgets/…              # tables, progress bars, log panes
├── ui_desktop/                # PySide6 frontend (Stages 09–12)
│   ├── main_window.py, dashboards, scanner views, settings dialogs
│   └── themes/design_tokens.py  # one design-token file shared conceptually with ui_terminal
├── cli/
│   ├── interactive_cli.py     # shim re-wiring legacy menu onto services (compatibility phase)
│   └── commands.py            # shim for legacy Click surface
└── packaging/                 # Nuitka spec + installer config (Stage 14)
```

**Dependency direction:** `ui_* → services → core → (nothing)`; `cli/` shims depend on `services` only. No cycles (legacy `main.py ⇄ scanner.py` tangles resolve to one-directional service usage).

## 3. Typed models and error propagation

- `Finding(id, category, severity: RiskLevel, title, detail, evidence, remediation, app_ref)` — single finding primitive used by permission, SDK, URL, and (future) APK-content categories so all UIs render one shape.
- `ScanResult(app: AppInfo, findings: list[Finding], honors_legacy_flags: dict)`; `ScanSummary(device, per_app stats, totals)` computed, not stored as divergent counters.
- **Error model:** services raise typed errors (`AdbNotAvailable`, `DeviceNotConnected`, `ADBCommandError(reason, cmd, returncode)`, `ScanInterrupted`, `ConfigError`). Frontends catch at edges and translate to UI affordances; services never `print()`. Progress/failures are events, not console writes.
- Byte safety: ADB low layer gains a mode returning raw bytes (`adb shell` binary-safe, or `adb exec-out`) — eliminates the legacy text-roundtrip corruption in forensics DB extraction.

## 4. Jobs, progress events, cancellation

- `Job(job_id, kind, params) → JobHandle` running in a `ThreadPoolExecutor`/asyncio task either behind the TUI's asyncio loop or a Qt `QThreadPool` adapter.
- Event stream: `concurrent.futures`-agnostic `EventSource` emitting typed events (`Started`, `Progress(current,total,context)`, `LogChunk`, `FindingAvailable(finding)`, `Completed(summary)`, `Failed(error)`, `Cancelled`).
- **Cancellation is cooperative:** scan loops check a `cancel_token` between apps/file groups; ADB subprocess calls are terminated on cancel; multi-file forensics extraction aborts between files, marks partial state in the case manifest.
- Report generation, tool downloads, device polling, and hardware monitoring are all jobs, uniformly cancellable in both UIs.

## 5. Configuration and optional local history

- Versioned `vscanner.toml` (or JSON) written to the standard user-config directory (e.g. `%LOCALAPPDATA%/vscanner/config.json`), schema-validated with migration on version bump; CLI `--config` override kept for tests; ADB/scrcpy binary paths, default scan flags, output dirs, UI theme.
- Optional **local scan history** (`%LOCALAPPDATA%/vscanner/history/`, JSON per scan, size-capped, expirable) so both UIs can show past scans; purely local, opt-out.
- Legacy `cli/adb_config.json` is imported/migrated; the machine-specific tracked copy stays out of the new path (Stage 05 hygiene decision).

## 6. Tool provisioning

- `services/tools/provisioning.py` ports `tools_manager` but: resolves versions from the GitHub API with a **pinned verified fallback** (v2.4 URL replaced or validated), verifies checksums when available, emits progress events through the job system, and installs under a user-scoped tools dir (not the source tree). Offline mode degrades gracefully with clear status, never auto-`pip install`.

## 7. Frontends

- **TUI (Textual + Rich):** Claude Code/OpenCode-inspired screens — startup doctor, device workspace, scan dashboards with streaming findings, forensics cockpit, settings. Rich handled inside Textual widgets; keymap documented; mouse optional.
- **Desktop (PySide6/Qt Widgets):** main window with device pane, dashboard, scan views, findings tables/detail panes, settings dialog, notification-free status bar. Qt-specific theming via design tokens.
- **Both frontends call identical service calls and job API.** UI code may never spawn `adb` or cast analysis dicts directly.

## 8. Packaging (Stage 14)

- **Nuitka** (onefile or standalone, chosen in Stage 01 spec) targeting Windows `x86_64`; splash + icon; includes ADB/scrcpy via first-run provisioning rather than bundling (repo hygiene) with optional bundled mode for offline installers.
- Installer: Inno Setup or MSI (decided Stage 14) — creates shortcuts, adds uninstall entry; no admin required by default.
- Representation parity tests: the packaged binary must expose the same feature list (documented in `FEATURE_PARITY_MATRIX.md`) and run the same regression suite in a device-emulation harness where possible.

## 9. Test boundaries (Stage 02 foundation + onward)

- `core/` — pure unit tests (findings, scoring, config round-trip).
- `services/` — unit tests with a **faked ADB client** (record/replay of dumpsys/getprop outputs captured from real devices, committed as fixtures only if license-safe); report snapshot tests (HTML/JSON/text golden files).
- `jobs.py` — cancellation/timeout/ordering tests.
- `ui_terminal/` and `ui_desktop/` — thin smoke/integration tests (frontend renders a canned service state); device-dependent paths always through fakes in CI.
- Legacy CLI compatibility contract — `scanner.py list/analyze/demo` output shape + `main.py` imports verified each stage (no behavioral change until Stage 16 sign-off).

## 10. Migration boundaries (Stage 01 will refine)

| Migration move | Constraint |
|---|---|
| Extract `permissions.py` knowledge base | datafiles, not code; freeze content, version it |
| Extract `report_generator` templates | keep legacy filenames until Stage 16 |
| Extract ADB layer | byte-safe replace of text-mode cats; scan results must reproduce legacy format for regression |
| Replace monolith menus | one option at a time; legacy menu remains default until feature parity confirmed |
| Delete/decide dead code (device_unlock, broken extractors, duplicate functions) | decision recorded, not silently removed; destructive device-injection code not carried forward without explicit approval |
| Android app | **untouched** in all stages |

**Explicit exclusions:** network server, cloud, telemetry, adb-shell/qrcode plugin revival (or removal with rationale), new Android features, license headers changes, CI platform migration beyond what is needed for tests.
