# V-Scanner 3.0 — Stage 11 Implementation Report

**Stage:** 11 — Desktop scanner and findings (PySide6)
**Scope:** Desktop scan workspace (target/preflight/scope/engine-supported scan types, live job progress, cancellation) over the Stage 04 `JobManager`; findings explorer (search, severity/category/provenance filters, deterministic sorts, 100-row pagination, provenance-honest detail); reports screen (SC-9 export of the last completed full-device bundle through the real `ReportService`, T-08 scan-history reader).
**Status:** COMPLETE with recorded deviations (single-app scans not exportable; deep-scan URL path [UNVERIFIED]; fakes-not-hardware — see §4).
**Date:** 2026-10-19
**Branch:** `main` (base `ad4419d` — the Stage 10 docs head).

---

## 1. What was delivered

### 1.1 Package layout changes

```
ui_desktop/
├─ backend.py           EXTENDED — scan/export/history seam (§1.2)
├─ main_window.py        scan/reports section builders + version label text
├─ sections.py           `scan` and `reports` registry rows: future → LIVE (Stage 11 owner)
└─ screens/
    ├─ scan.py           NEW — ScanWorkspacePage (A1.3: target + scan + findings explorer)
    ├─ reports.py        NEW — ReportsPage (A1.4: export + history)
    ├─ dashboard.py      boundary panel updated (remaining ranges now Stage 12 rows)
    └─ __init__.py       exports + ScanWorkspacePage/ReportsPage
tests/unit/
    └─ test_stage11_desktop.py  NEW — 58 offscreen tests (§2)
```

### 1.2 Engine seam extensions (`ui_desktop/backend.py`) — TUI-parity surface

No engine service changed; the desktop layer still contains no parsing, no subprocess, no ADB literals.

| Method | Thread contract | Notes |
|---|---|---|
| `start_scan_job(serial, include_system=False, deep=False, package=None)` | submit → queue | Stage 07 parity: `scan_full_device_plan` / `scan_single_app_plan` with a **serial-bound client** (the dumpsys/aapt stream runs against one device, never registry-global state) |
| `cancel_scan_job(serial)` | idempotent request → int | cancels **only `FULL_DEVICE_SCAN` + `SINGLE_APP_SCAN`** jobs for the serial; never touches `APP_LISTING` (test-locked §2). Request ≠ acknowledgement (contract A5) |
| `active_scan_handle(serial)` | read-only | most recent non-terminal scan-kind handle, or None |
| `remember_scan(result_or_bundle, status_word, serial)` | UI-thread safe | session memory: `(status_word, serial, bundle)`; a `ScanResultBundle` is the only result shape stored for export — every other shape stores `None` |
| `last_scan()` | read-only | the remembered tuple, or None |
| `start_export_job(bundle, requested=None, output_dir=None, device_info=None, serial=None)` | submit → queue | Stage 04 `EXPORT` job over the real `export_reports_plan(ReportService(output_dir), …)` (SC-9; atomic, exempt from cancellation in the engine) |
| `history_entry(entry) -> Path` | UI-thread caller | one real `ScanHistoryStore.append` over `history_dir()` (T-08); `history_dir` is imported at module level (`backend_module.history_dir`) so tests can repoint it without the engine |
| `history_recent() -> tuple` | worker-only in the page | real tolerant store read (newest-first, corrupt-file counting) |

### 1.3 Scan workspace (`ui_desktop/screens/scan.py`)

One page, cached by the shell (repeated navigation rebuilds nothing, duplicate subscriptions impossible — tested), replacing the Stage 09 "scan" placeholder:

**Device target panel.** Own compact engine discovery (`backend.list_devices()` through its own `WorkerCoordinator` slot; overlapping refresh refused at the slot level). The first `activate()` runs **exactly one** auto-refresh. Rows verify the parser output verbatim (serial/state/transport); non-actionable states can never be targeted. Selection rules are Stage 06 parity: auto-preselect ONLY one unambiguous actionable device; with 0 or 2+ devices nothing is auto-selected and the scan controls stay disabled; an explicit row selection enables them; a vanished target invalidates the selection with the truthful note ("… invalidated on purpose — nothing is auto-switched").

**Preflight panel.** An always-current honest summary: the current target, the next scan kind (full-device vs single-app), the scope toggles (system apps included/excluded · deep scan on/off), and the standing preflight refrains (a reported state change before the scan; nothing auto-switched; full-device dumpsys permission analysis is host-side; a cancellation request is not a completion).

**Scan execution (SC-2 pipeline).** Preflight then submit:
- The preflight re-runs a FRESH discovery (`backend.list_devices()` in a worker slot) and refuses honestly ("no longer connected or authorized…") when the selected serial is absent — no scan is ever submitted against a stale target.
- Engine-supported scan types in this stage: **`FULL_DEVICE`** (include-system and deep toggles explicit) and **`SINGLE_APP`** (package input validated by the engine's `validate_package_name` before any work starts; deep toggle explicit). No other scan surface exists on this page and none is fabricated.
- Progress is the REAL streamed job events through the `QtJobEventBridge`: only the engine's honest counts (skipped apps named by the engine's own rule; single-app scope shows "no per-app progress"). Cancellation (`c`-parity button) is a request: the state stays `running` until the terminal; a **queued** scan cancels to `CANCELLED` immediately (never reaching package analysis — verified by call counting); a running scan cancels with PARTIAL-stream honesty (streamed findings kept, history record `cancelled`). Overlapping submission is refused ("already active…", job call-count verified). Late/foreign events after the terminal (superseded job id, replayed job id) never mutate state.
- **Truthfulness per outcome:** `SUCCEEDED` + `ScanResultBundle` → findings replaced `from-bundle`, memory `completed`, history `completed`; `SUCCEEDED` + `AppScanResult` → page state `not-exportable` (the legacy export schema needs a bundle; nothing is fabricated — §4.1) + memory completed (bundle `None`) + history `kind: single_app`; `SUCCEEDED` + unexpected shape → `failed` with "unexpected engine result shape…" (no row invented); `FAILED` → typed engine message surfaced ("full-device scan could not start: …" / "scan failed: …"); history records the honest `failed`. A zero-findings completed scan says exactly that — plus "the device is not thereby certified secure".

**Findings explorer.** `QAbstractTableModel` + `QTableView` over the engine's typed findings (no desktop-side parsing):
- Columns: severity / category / title (detail body) / app (honest `(no app)` when device-scoped) / evidence count.
- Text search (substring over title+detail+category+package, non-mutating), severity-threshold filter, category filter, and **provenance buckets derived from `EvidenceKind`** (observed → confirmed artifact/command output; unverified → unverified condition; heuristic → heuristic pattern; informational → annotation …; plus "no evidence") — unverified conditions stay visible and filterable (deep-scan honesty is test-locked).
- Deterministic sorts (severity rank / package / title, stable collation), `PAGE_SIZE = 100` pagination with clamped out-of-range pages, live count label. Malformed rows cannot crash the view: every cell access is exception-guarded and renders `(malformed finding)` / `(unreadable field)` honestly instead.
- Detail panel rows (full facts: title/severity/category/detail/app/device/finding id/detected-by/run id/evidence list incl. provenance word and redacted excerpt/recommended fix); evidence excerpts render the engine's redaction, values redacted by construction never leak; missing optional fields render "not available"/"no evidence recorded" honestly. The detail clears when its row leaves the filtered view (no stale detail leaks).

### 1.4 Reports & history (`ui_desktop/screens/reports.py`), replacing the Stage 09 "reports" placeholder

**Last-terminal scan panel.** Reads the session memory (`backend.last_scan()`) **at construction** so a first visit after a scan reflects reality immediately, and on refresh:
- no scan yet → "no terminal scan this session yet — nothing can be exported yet" (export disabled);
- completed full-device bundle → totals from the bundle (apps/findings/severity counters), export enabled;
- cancelled / failed → honest "not exportable", export refuses programmatically (typed refusal word, job id stays None);
- completed single-app → "not eligible" (§4.1).

**Export flow (SC-9 via the real `ReportService`).** All three legacy formats: a native directory dialog (`QFileDialog.getExistingDirectory`), service-generated timestamped names (`security_report_<ts>.html/json/text`); single format: `getSaveFileName`, with an engine-side suffix append when the user typed none. Existing target files are overwritten ONLY after an explicit `QMessageBox.question` confirm (default No; the declined path leaves the file untouched and refuses loudly — both branches test-locked). The export runs as a Stage 04 `EXPORT` job through `start_export_job`; success is claimed only after the write: the `ok` state lists exactly `ExportResult.formats_written` paths (verified existing on disk); a write failure renders the typed message with "nothing is claimed as saved". States: `idle / refused / running / ok / failed` (already-running export refused honestly). Export content is the legacy byte-schema (verified: JSON top-level `device_info/scan_time/total_apps/summary/apps` and per-app `package_name/permissions/dangerous_permissions/risk_score/risk_level` — parity with direct `ReportService.export`).

**Scan history (T-08).** Real `ScanHistoryStore.recent()` read in a worker slot into `HistoryTableModel` (finished-at / kind / status / device / apps / findings columns); honest states: `empty` / `ok` ("counters only — the local store never holds secrets") / `failed` (typed message + "no record is invented"). One JSON file per scan; on-write completion pumps a small serialize-queue so a stream of finished scans cannot interleave.

### 1.5 Registry / shell wiring

`sections.py`: `scan` and `reports` rows now `live` (Stage 11 owns them; sub-screens verified by the same registry-kind contract). `main_window.py` builds the two pages only when a backend is wired (a section without one keeps the Stage 09 honest `ErrorState`). The Stage 10 registry test was updated exactly once: the future set shrinks to `monitoring / forensics / mirroring / demo` (Stage 12 scope) — Stage 09/10 behavior untouched. Dashboard boundary text now lists only the Stage 12 rows as future.

## 2. Test facts (`tests/unit/test_stage11_desktop.py`, 58 tests)

Offscreen harness identical to Stage 09/10 (session `qapp`, deterministic `pump_until`, GUI-thread assertions by captured `threading.get_ident()`). The engine is exercised FOR REAL: a dumpsys-capable `FakeAdbTransport` extension runs the actual `DeviceDiscoveryService`/`ScanService` (`scan_full_device`/`scan_single_app`), Stage 04 `JobManager`, `QtJobEventBridge`, `DesktopBackend`, real `ReportService` writes into a real `tmp_path` directory, and the real T-08 store (repointed to `tmp_path` via `backend_module.history_dir`). The dumpsys fixture is re-extracted from the engine tests via AST (importing that module fails by construction: it imports a test-local conftest; the literal is read, never duplicated).

| Class | Count | Covers |
|---|---|---|
| `TestBackendScanSeam` | 5 | serial-bound scan jobs (kinds/serial), engine conflict refusal (scan mutex group), cancel hits scan kinds only (APP_LISTING survives), export job → real 3-format write |
| `TestScanMemoryContract` | 4 | completed bundle remembered as export material; failed/cancelled remembered with material `None`; non-bundle result never report material; `ReportService` typed failure on an uncreatable destination |
| `TestScanLifecycle` | 14 | full-device completes with the REAL fixture findings (5 typed findings incl. `READ_SMS` CRITICAL + SDKCompat; history record keys verified); single-app completes → `not-exportable` + single_app history; preflight refuses target-less start (no `pm` call ever); vanished-device selection invalidation (truthful note); stale target caught by the FRESH preflight discovery; failed scans honest (typed reason, `failed` history, memory worked-free); single-app service failure honest; duplicate submission refused (job call count); cancellation request ≠ completion (PARTIAL keep, `cancelled` history); queued-cancel terminalizes immediately (zero package analysis calls); late events never mutate post-terminal state; foreign job terminal ignored; stale replay never crosses the new selection; zero-findings honesty ("not thereby certified secure") |
| `TestDeliveryDiscipline` | 4 | hub deliveries only on the GUI thread (spy page through the real `MainWindow`); navigation can never duplicate subscriptions (exactly one terminal delivery across re-entry); `shutdown()` during an active job disconnects safely (post-shutdown emit = no-op); unexpected engine result shape fails honestly and the later REAL success terminal stays ignored |
| `TestFindingsModel` | 6 | 220 unique-id rows, headers/display data, honest unknowns for missing fields, malformed row cannot crash (row AND detail), full detail facts, redacted evidence never leaks raw excerpts |
| `TestFindingsExplorer` | 7 | pagination clamps and live counts; text search; severity/category/provenance filters; deterministic sorts; combined filters; detail clears with the filter; deep-scan unverified note visible + filterable |
| `TestReportsWorkflow` | 13 | honest no-scan state; completed enables export with real totals; cancelled refuses programmatically; success only after files hit disk (`.html/.json/.text` verified); legacy JSON schema parity; unwritable destination honest ("nothing is claimed as saved"); explicit-confirm overwrite (default No); directory dialog flow; save-dialog flow + suffix append + cancel refusal; declined overwrite leaves the file untouched; T-08 round-trip (status words); typed history read failure; empty history |
| `TestScanScope` | 3 | scope toggles update the preflight summary; package input required/validated (engine `InputValidationError` surfaced); deep scan with an non-extractable surface yields the engine's honest `UNVERIFIED_CONDITION` note (6th finding) which stays visible and filterable |
| `TestStage11Architecture` | 2 | no `subprocess`/`adb_setup`/`textual` import in ANY `ui_desktop` module; no UI framework import ever reaches `vscanner/` |

Engine facts locked by the tests (learned this stage): the dumpsys fixture produces exactly 5 findings (a subject-INTERNET-LOW duplicate-engine quirk yields two INTERNET entries; `READ_SMS` CRITICAL, `ACCESS_FINE_LOCATION` HIGH, plus the SDK advisory CRITICAL); a deep scan over a non-extractable APK adds a 6th INFO `insecure_url` finding titled "Deep-scan URL/secret analysis unavailable…" carrying `unverified_condition` evidence — engine honesty preserved end-to-end.

## 3. Design/engine truths recorded

- `cancel_scan_job` is weld-limited to the two scan kinds: the JobManager has no per-kind cancel API, so the backend filters its own handles by job id and kind. `APP_LISTING` cancellation (Stage 10 surface) is untouched — regression-locked.
- Single-app scans end in an `AppScanResult` (not a `ScanResultBundle`): the desktop reports page treats ONLY completed full-device scans as export material. This is engine truth, not a desktop shortcut — see §4.1.
- T-08 store naming is `<UTC stamp>-<scan_id[:8]>.json`: engine-generated scan ids (request-id-based) are collision-free in practice; the Stage 11 tests use distinct prefixes deliberately (two 8-char-prefix-colliding same-second writes would overwrite — documented here, not "fixed" by inventing a new naming scheme in Stage 11; store behavior itself is unchanged engine source).
- History record writes from the page are serialized through one worker slot (a completed write pumps the next queued record); a write failure drops loudly instead of pretending success.

## 4. Known limitations / deviations (honest)

1. **Single-app scans are not exportable.** The legacy `ReportService` export schema requires a `ScanResultBundle` (full-device shape: per-app permission sets + device blocks). A completed single-app scan honestly says "not exportable (only completed full-device scans are eligible)" instead of fabricating a bundle. Owner: parity decision lives with the engine (SC-9), not the desktop — matches the TUI Stage 07/08 reports contract.
2. **Deep-scan URL/secret path [UNVERIFIED].** With the byte-safe exec-out transport available, the engine's host-side URL/credential extraction runs; in this environment the fake transport exposes only the text surface, so every deep scan executes the engine's honest `UNVERIFIED_CONDITION` note path (engine rule kept intact, presentation-locked by tests). The on-device byte path remains [M: not re-executed on physical hardware this stage] as recorded in Stage 08.
3. **Fakes-not-hardware.** No real device, ADB binary, root, or network was involved: scans ran over documented fake transports against the real services. All [M] real-device items (C-F07/C-F08 wording checks on live output shapes) remain recorded-when-absent.
4. **Engine-supported scan types = FULL_DEVICE + SINGLE_APP only.** The scan page offers nothing else; no monitor/forensics/mirror surface exists (Stage 12 scope) and none is hinted as available.
5. The full-device silent-drop engine quirk (apps without a dumpsys permissions answer are dropped from summary counts) is preserved unchanged by the shared engine — documented in Stage 07, intentionally NOT fixed here (no new heuristics on either side).

## 5. Quality gates (exact results)

| Gate | Command | Result |
|---|---|---|
| Full suite A-2 | `python -m pytest -q` | run ① **765 passed** ② **764 + 1 flake** ③ 765 ④ **765** (≈63 s each; see the flake note below) |
| Stage 11 file | `python -m pytest tests/unit/test_stage11_desktop.py -q` | **58 passed** |
| Stage 09+10 regression | both desktop files | **105 passed** |
| Lint | `python -m ruff check .` | All checks passed |
| Types | `python -m mypy` | Success: no issues found in **116 source files** (+3 Stage 11 modules; legacy `cli/` stays out of scope by design) |
| Byte-compile | `python -m compileall -q ui_desktop ui_terminal vscanner tests` | exit 0 |
| Desktop startup smoke | `python -m ui_desktop --smoke` | `DESKTOP_SMOKE_OK`, exit 0 |
| Coverage | `coverage` over `tests/unit` | TOTAL **71%** including the uncovered legacy `cli/` (engine+UIs only: 88%); Stage 11 detail: `ui_desktop/backend.py` 94% (94–95% on the new scan/export/history seam), `screens/scan.py` **90%**, `screens/reports.py` **87%** |

**Flake note (honest):** full-suite run ② saw one failure in the pre-existing engine test
`test_stage07_engine.py::TestExportIntegration::test_unwritable_destination_never_reports_success`
(covers "an unwritable destination never reports success"). It passed in the same-session
targeted rerun, in **25/25 isolated repeats**, and in the two subsequent full-suite runs
(765/765). Non-reproducible environment transient (Windows file-lock interference on an
intentionally unwritable path); no Stage 11 change touches that path (the new
`TestScanMemoryContract`/`TestReportsWorkflow` failure-path tests passed in every run).

**Platform honesty: every GUI test ran on the `offscreen` Qt platform; the desktop scan and
reports workspaces were NOT operated in a real interactive Windows window, and no device,
ADB, root, or network was involved.** No gate was skipped.

## 6. Git record

- Implementation commit: `feat(desktop): add scanning and findings workflows` (source/tests only; staged diff inspected: no binaries, no secrets, no device config; `.gitignore` NOT staged; `cli/adb_config.json` untouched; `cli/python usb_charging_control.py` untracked; `android/**` untouched).
- Docs commit: `docs(progress): record Stage 11 completion` (docs/vscanner-3: PROGRESS, ROADMAP, ACCEPTANCE_CRITERIA, FEATURE_PARITY_MATRIX, TESTING_STRATEGY, this report).
- Push: HTTPS-only `git push origin main`; `git fetch origin` + `git rev-parse main origin/main` equality verified after the docs commit.
