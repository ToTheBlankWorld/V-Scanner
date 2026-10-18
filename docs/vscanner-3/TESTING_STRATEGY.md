# V-Scanner 3.0 — Testing Strategy

**Stage 02 deliverable.** Governs test design from Stage 02 onward. Updated by each stage that adds tests.

## 1. Development environment requirements

| Component | Version (validated on this stage) | Notes |
|---|---|---|
| Python | 3.12.10 | Dev machine version; legacy dep floor stricter-check task belongs to Stage 03 (T-01 follow-up) |
| pytest | 9.0.3 | Runner; config in `pyproject.toml` |
| pytest-cov | 7.1.0 | Coverage measurement (dev-only install, documented) |
| Ruff | 0.16.8 | Lint; config in `pyproject.toml` |
| mypy | 2.3.1 | Type check; narrowly scoped (see §5) |

`pytest-cov` was installed during this stage (`pip install pytest-cov`). It is a development tool: `cli/requirements.txt` is unchanged and no production dependency was touched.

## 2. Test categories and purpose

| Directory | Purpose | Contact with reality |
|---|---|---|
| `tests/unit/` | Pure-logic characterization: permission KB/scoring, report factories/templates, tool URL resolution, static module structure (AST), config-consumer behavior, defect evidence | No subprocess, no filesystem outside `tmp_path` except temp-time demos |
| `tests/integration/` | Component-through-subprocess paths: `ADBInterface._run_cmd` (mocked subprocess — one real local `python` process for decode semantics), Click CLI via `CliRunner`, tool extraction with generated archives, syntax baseline | Never launches `adb`/`scrcpy`; never touches network; one test intentionally runs `sys.executable` locally |
| test fixtures | Generated in-test (zip/tar writers, JSON payloads) for determinism | No checked-in binary fixtures |

Organization note: the smallest structure fit — `tests/unit` + `tests/integration` only; `tests/fixtures/` was intentionally omitted because fixtures are generated programmatically at test time (deterministic, no repo binaries).

## 3. Exact commands

```powershell
# Run the whole suite (no device, no network, no root):
python -m pytest

# Coverage of the legacy CLI package AND the engine:
python -m coverage run -m pytest; python -m coverage report --include="cli/*,vscanner/*"

# Lint (new code + engine; cli/ excluded until its stages migrate):
python -m ruff check vscanner tests

# Type check (tests + engine, legacy followed "silently", see §5):
python -m mypy

# Byte-compilation of every legacy module + engine package + TUI layer:
python -m compileall -q vscanner cli ui_terminal tests

# Stage 05 TUI slice only (headless Textual harness; asyncio auto mode):
python -m pytest tests/unit/test_tui_app.py tests/unit/test_tui_services_screens.py tests/unit/test_tui_entry.py

# Python syntax validation of all legacy modules (also asserted by tests/integration/test_syntax_baseline.py):
python -m pytest "tests/integration/test_syntax_baseline.py"
```

`pyproject.toml` sets `testpaths = ["tests"]`, `--strict-markers` and `xfail_strict = true`; since Stage 05 also `asyncio_mode = "auto"` for the Textual headless harness tests.

## 4. Mocking conventions

- **ADB subprocess:** patch `scanner.subprocess.run` (and `main`-equivalents) with `subprocess.CompletedProcess`, or reuse `tests/conftest.py::FakeAdb` for object-level fakes (`DeviceForensics` consumes `_run_cmd` tuples directly).
- **Network / tool downloads:** patch `tools_manager.download_file` or `urllib.request.urlopen`; a test fails by design if a download is attempted without being mocked ("network access attempted although tool present").
- **Filesystem:** every generated artifact goes under `tmp_path` (`tmp_cwd` fixture handles cwd-relative writers such as the demo's `reports/` and `ReportGenerator` output).
- **Machine-specific config:** `isolated_config` fixture repoints both legacy config loaders to a temp file; tests never read the developer's real `cli/adb_config.json`.
- Hard rule inherited by later stages: **no test may execute real ADB administrative (uninstall/open/force-stop) commands, real downloads, or read/write production device-data paths.**

## 5. Type-check scope and lint baseline (Stage 02 decision records; Stage 03–05 updates)

- **mypy** since Stage 04 runs on `files = ["tests", "vscanner", "ui_terminal", "ui_desktop"]`; Stage 05 grew the checked set to **71 source files, zero issues** (`Success: no issues found in 71 source files`). Legacy `cli/` imports are followed "silently": errors inside legacy modules stay suppressed until each module migrates, while unresolved imports and all new-code type defects surface. Target: **zero errors in the engine at every stage** — Stage 05 delivered clean.
- **Ruff** selects a minimal fixable set (`E9/F63/F7/F82/E722/F811/F841/B006/B015/B018`), `target-version = "py310"`, `cli/` and `android/` excluded until migrated. Baseline status: **all checks pass** across `vscanner` + `ui_terminal` + `tests`.
- **Syntax validation** compiles all 11 legacy modules plus the full engine package and the TUI layer (`compileall` green for `vscanner ui_terminal tests`).
- **Async TUI tests** (Stage 05): `pytest-asyncio` runs in `asyncio_mode = "auto"` (`asyncio_default_fixture_loop_scope = "function"`), so Textual `run_test` harness coroutines need no per-test markers. Harness rules: headless `run_test(size=...)` only, `pilot.pause()` after actions, injected tmp-path `ConfigService` — never the developer's real config dir; no real device, network, root, or provisioning.

## 6. Current coverage result (honest, re-measured per stage; last: Stage 11)

Stage 02 measured cli-only TOTAL 20%. Stage 03 re-measured over `cli` + the new engine; Stage 04 added the `ui_terminal`/`ui_desktop` bridge stubs; Stage 05 added the full TUI layer to the measured source set; Stage 06 re-measured after adding the device workspace; Stage 07 re-measured after adding the scan/reports screens + history store; Stage 09 re-measured after adding the full desktop shell layer (same command: `python -m coverage run -m pytest -q` + `report`). Stage 09 TOTAL: **68%** (9825 statements). Stage 10 re-measured after adding the device workspace/worker seam/dashboard rebuild: TOTAL **70%** (10653 statements) — new anchors: ui_desktop backend 98%, workers 95%, screens/devices **93%** (562 stmts), screens/dashboard 94%; the desktop-layer detail is in `STAGE_10_IMPLEMENTATION_REPORT.md` §5. Stage 11 re-measured after adding the desktop scan workspace + reports/history screens: TOTAL **71%** (11904 statements — the count grows because the measured source set includes the new desktop modules; legacy `cli/` interactive paths remain the uncovered-by-design bulk) — Stage 11 anchors: `ui_desktop/backend.py` **94%** (the new scan/export/history seam runs in the 90s), `ui_desktop/screens/scan.py` **90%** (851 stmts), `ui_desktop/screens/reports.py` **87%** (329 stmts), `main_window.py` 91%, `screens/dashboard.py` 94%; detail in `STAGE_11_IMPLEMENTATION_REPORT.md` §5. The table below preserves the historical per-module record from Stage 07:

| Module | Statements | Missed | Coverage |
|---|---:|---:|---:|
| vscanner/core/events.py | 96 | 0 | 100% |
| vscanner/core/kb/permissions.py | 63 | 0 | 100% |
| vscanner/core/models.py | 308 | 3 | 99% |
| vscanner/core/redact.py | 25 | 1 | 96% |
| vscanner/core/errors.py | 51 | 4 | 92% |
| vscanner/services/reports/service.py | 98 | 2 | 98% |
| vscanner/services/orchestration.py | 44 | 0 | 100% (Stage 06: + `app_listing_rows_plan`) || vscanner/services/config.py | 90 | 7 | 92% |
| vscanner/services/doctor.py | 45 | 3 | 93% |
| vscanner/services/jobs.py | 370 | 34 | 91% |
| vscanner/services/scanning/* (3 modules) | 221 | 13 | ~94% |
| vscanner/services/scanning/app_inventory.py `list_app_rows` (Stage 06) | 37 | 2 | 95% |
| vscanner/services/adb/* (4 modules) | 181 | 44 | ~76% |
| vscanner/services/tools/provisioning.py | 187 | 33 | 82% |
| vscanner/services/tools/_extraction.py | 45 | 17 | 62% |
| vscanner/services/registry.py | 64 | 9 | 86% (Stage 06: + `device_info` accessor) |
| ui_desktop/jobs_bridge_qt.py | 76 | 6 | 92% (Stage 09: stub layer at 100% + Qt signal hub/bridge) |
| ui_desktop/* Stage 09 (shell/screens/dialog/theme) | 6915−905 | — | measured at Stage 09: theme 98%, settings_dialog 100%, screens 89–100%, main_window 89%, widgets 81%, app.py 48% (exec-loop paths), `__main__.py` 0% (thin launcher) — see STAGE_09_IMPLEMENTATION_REPORT.md §5 |
| ui_terminal/jobs_bridge_async.py | 59 | 8 | 86% |
| ui_terminal/theme.py (Stage 05) | 20 | 0 | 100% |
| ui_terminal/sections.py (Stage 05) | 46 | 0 | 100% |
| ui_terminal/screens/dashboard.py (Stage 05) | 50 | 0 | 100% |
| ui_terminal/screens/help.py (Stage 05) | 35 | 0 | 100% |
| ui_terminal/screens/placeholder.py (Stage 05) | 24 | 0 | 100% |
| ui_terminal/screens/doctor.py (Stage 05) | 67 | 2 | 97% |
| ui_terminal/screens/shell.py (Stage 05) | 66 | 4 | 94% |
| ui_terminal/app.py (Stage 05) | 99 | 10 | 90% |
| ui_terminal/screens/settings.py (Stage 05) | 108 | 13 | 88% |
| ui_terminal/backend.py (Stage 06, +07 surface) | 124 | 42 | 66% |
| ui_terminal/screens/workspace.py (Stage 06) | 382 | 29 | 92% |
| ui_terminal/screens/scan.py (Stage 07) | 541 | 66 | 88% |
| ui_terminal/screens/reports.py (Stage 07) | 174 | 9 | 95% |
| vscanner/services/history.py (Stage 07, T-08) | 93 | 19 | 80% |
| cli/main.py | 926 | 883 | 5% |
| cli/scanner.py | 1033 | 775 | 25% |
| cli/tools_manager.py | 282 | 165 | 41% |
| cli/adb_setup.py | 80 | 46 | 42% |
| cli/report_generator.py | 95 | 7 | 93% |
| cli/permissions.py (shim) | 7 | 1 | 86% |
| **TOTAL (cli + vscanner + ui)** | **7214** | **2998** | **58%** |

Interpretation: the engine is well anchored (events/models/KB/redaction/reports/orchestration ≥ 92%; surgery-grade anchors on every service; jobs.py 91%), the Stage 06 workspace slice is anchored at 90–95% (workspace 92%, app_inventory `list_app_rows` 95%), and the Stage 07 scan/reports slice is anchored at 80–95% (scan screen 88%, reports screen 95%, T-08 history store 80% — the missed lines are the production directory-bootstrap and eviction paths covered indirectly), via Textual headless harness + fake-transport pipeline tests. Legacy interactive/rich-UI paths remain uncovered by design decision (that coverage arrives with service decomposition in Stages 06–12, not by writing brittle UI tests against legacy print flows). Do **not** flatten the 58% number into a quality claim; cite the per-engine anchors.

## 7. Suite facts (Stage 02 → Stage 11)

- Stage 02: **106 passed, 7 xfailed, 0 skipped** (9 files). Stage 03: **276 passed, 4 xfailed, 0 skipped** (17 files). Stage 04: **363 passed, 4 xfailed, 0 skipped** (21 files), runtime ≈ 3.5 s. Stage 05: **399 passed, 4 xfailed, 0 skipped** (24 files), runtime ≈ 22 s (Textual harness tests dominate; still device/network/root-free). Stage 06: **446 passed, 4 xfailed, 0 skipped** (27 files), runtime ≈ 62 s (new: `test_stage06_engine.py` 10, `test_device_workspace.py` 31, `test_inventory_ui.py` 4, + import-guard/doc-consistency additions). Stage 07: **505 passed, 4 xfailed, 0 skipped** (30 files), runtime ≈ 107 s (new: `test_stage07_engine.py` 15, `test_scan_screen.py` 24, `test_reports_ui.py` 12; `test_services_jobs.py` grew to 44 with the deterministic race-ordering tests and passes ×3 consecutive runs). Stage 08: **602 passed, 0 xfailed, 0 skipped** (33 files), runtime ≈ 150 s (new: `test_stage08_engine.py` 66 - services, plans, bridge §13 containment, deep-scan integration; `test_stage08_ui.py` 17 - monitoring/forensics/mirroring/demo/admin screens; `test_known_defects.py` flipped to 16 fixed-behavior tests, 0 xfails). Repeat-run verification: ×2 recorded in the Stage 08 report. Stage 09: **640 passed, 0 xfailed, 0 skipped** (34 files), runtime ≈ 59 s (new: `test_stage09_desktop.py` 38 - offscreen PySide6 harness for shell lifecycle/navigation/design-system/settings/Qt-job-bridge GUI-thread rule/architecture; PySide6 6.12.0 as the optional `[desktop]` extra; `pytest.importorskip` keeps engine-only environments green). Repeat-run verification: ×2 recorded in the Stage 09 report (run 2 under coverage). Stage 10: **707 passed, 0 xfailed, 0 skipped** (35 files), runtime ≈ 61 s ×2 consecutive (new: `test_stage10_desktop.py` 67 - dashboard honesty, worker coordinator two-hop GUI-thread delivery, registry/backend seam, discovery, selection, root tri-state details, inventory browser with 150-row pagination + cancel + late-event + busy-control honesty, settings validation, module-layer architecture; engine exercised for real through `FakeAdbTransport` with only `ServiceRegistry` swapped). Repeat-run verification: ×3 recorded for the desktop+jobs-integration subset (118 passed). Harness hygiene note (recorded for future desktop stages): PySide6 6.12.0 on Windows aborts nondeterministically at interpreter shutdown when leftover top-level widgets survive to static teardown (0xC0000409/0xC0000005) — the desktop session `qapp` fixtures now flush + `deleteLater` every remaining top-level widget before yielding, which makes process exits deterministic (verified ×8 in isolation; the full suite previously passed 707 ×2 while exit codes flaked).
- Stage 11: **765 passed, 0 xfailed, 0 skipped** (36 files), runtime ~63 s (new: `test_stage11_desktop.py` 58 — backend scan/export/history seam, scan lifecycle incl. stale/partial/queued-cancel/late/foreign/GUI-thread/shutdown honesty, findings model at 220 rows with malformed-row safety and redaction-lock, explorer filters/sorts/pagination, real `ReportService` export with overwrite gates and legacy byte-schema parity, T-08 history round-trip, module architecture). Full-suite runs this stage: 765 / 764 + 1 non-reproducible pre-existing engine export flake / 765 / 765, plus 25/25 isolated reruns of that flake (recorded honestly in `STAGE_11_IMPLEMENTATION_REPORT.md` §5).
- No device, no network, no root; all artifacts under pytest temp dirs; one deterministic R-07 proof spawns `sys.executable` with list-argv (never a shell string).
- All 11 legacy modules + the whole engine byte-compile (`compileall` green).

## 8. Known expected failures (strict xfails — Stage 08 status: NONE REMAIN)

`xfail_strict` is ON: when remediation flips behavior, the XPASS becomes a hard failure and the stage must remove the marker and update the plan row.

**All Stage-08-owned xfails were flipped at Stage 08** (`test_known_defects.py` now 16 passed, 0 xfailed; suite-wide xfail count is 0). Each flip is a behavior change enforced by the remediation; the test now asserts the fixed behavior:

| Test | Defect | Flipped at |
|---|---|---|
| `TestR04FabricatedSensorFallback::test_no_sensor_data_means_no_invented_rows` | R-04 | Stage 08 — legacy `get_sensor_values_live` delegates to the engine `MonitoringService`; empty/failing output now yields an honest empty dict (`{}`), and `test_reported_rows_are_device_rows` pins that reported rows pass through untouched. The characterization rewrite asserts the *result-contract* change ({} instead of invented units/names). |
| `TestR05RootDefaultsToRooted::test_failed_detection_must_not_report_root` | R-05 | Stage 08 — verified tri-state probe over the legacy forensics facade: failed detection ⇒ `is_rooted` False + `root_status == "unknown"` (never ROOTED); sibling tests pin confirmed root, confirmed `not-rooted`, and the both-directions-honest rule. |
| `TestR06SecretPatternsNeverExecuted::test_patterns_actually_applied_in_deep_scan` | R-06 | Stage 08 — fixture rewritten to a three-part proof: `INSECURE_URL_PATTERNS` is consumed in the engine surface (AST load-count > 0 in `vscanner.services.scanning.deep_scan`), plus a behavioral positive/negative pair (`test_synthetic_credential_is_detected_and_redacted`: synthetic secret detected, ordinary text yields nothing, matched value never enters `CredentialHit`). Documented change: the original xfail targeted the never-executed legacy name; the flip keeps the original *intent* (patterns actually applied + honest redaction) against the live surface. |
| `TestR07TextModeDatabaseRewrite::test_requirement_byte_safe_binary_extraction` | R-07 | Stage 08 — the byte-safe `run_bytes` (exec-out semantics) path preserves payloads byte-identically through the legacy facade adapter; the text-mode corruption characterization above it is deliberately KEPT as honest evidence of why the text path is no longer used for binaries. |

No test was weakened in any flip: each converted test asserts the remediated behavior plus a regression lock, and the new-behavior tests in `test_stage08_engine.py` anchor the same services independently.

Still passing, regression-locked from earlier stages (marker removals recorded in their stage logs): R-01 (`TestR01...::test_admin_operations_menu_is_defined_exactly_once`), R-02 (`test_main_delegates_to_adb_setup_helpers` + typed-loader test), R-11 (traversal-hardening pair), and R-03 (`test_extract_all_dbs_from_dir_is_missing` / `test_phantom_extractors_removed` — flipped at Stage 08 with the A-06 closure: the missing call target and the four phantom extractors are deletions asserted as gone).

## 9. Guidance for adding tests (Stages 03–16)

1. New services in Stage 03+ live beside a faked transport: write tests against `AdbClientProtocol` fakes, not `monkeypatch`ed globals, when the new code allows constructor injection.
2. Golden files produced in Stage 02 (report suite) are the byte-stability baseline for Stage 03 parity — extend them, never regenerate silently.
3. Every remediated defect: remove the xfail marker in the same commit as the fix, add the code-behavior test, and update `SECURITY_AND_REMEDIATION_PLAN.md` + this section.
4. Pure functions added to `vscanner/core/` are unit-testable without fixtures; services need the fake transport; UI stages (05+) use headless harnesses (Textual run tests, Qt offscreen platform) — never interactive.
5. Keep the no-device/no-network/no-root promise: any test needing hardware must live in an opt-in marker (`@pytest.mark.hardware`) and default-skip; none exist yet.
6. When the test count changes materially, update §7 and `PROGRESS.md` in the same stage.
