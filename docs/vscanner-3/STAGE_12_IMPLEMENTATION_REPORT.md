# V-Scanner 3.0 — Stage 12 Implementation Report

**Stage:** 12 — Desktop feature parity and administration (PySide6)
**Scope:** Desktop parity for the remaining TUI surface over the existing engine services: live sensor monitoring (`MonitoringService`), forensics cockpit (`ForensicsService`), screen-mirroring launcher (`ScreenMirrorService` lifecycle), demo mode (`DemoService`), and the R-13 double-gated **administration operations** (launch / force-stop / uninstall) on the devices workspace; honest navigation/status parity (the last four placeholder registry rows become live).
**Status:** COMPLETE with recorded deviations (real scrcpy window display behavior [UNVERIFIED]; fakes-not-hardware — see §4).
**Date:** 2026-10-21
**Branch:** `main` (base `d67c411` — the Stage 11 docs head).

---

## 1. What was delivered

### 1.1 Package layout changes

```
ui_desktop/
├─ backend.py           EXTENDED — monitoring/forensics/mirroring/demo/admin seams (§1.2)
├─ main_window.py        four Stage 12 builders + honest ErrorState when unwired
├─ sections.py           `monitoring`/`forensics`/`mirroring`/`demo` rows: future → LIVE
│                        (no future rows remain anywhere in the registry)
└─ screens/
    ├─ monitoring.py     NEW — MonitoringPage (live poll + sensors-once)
    ├─ forensics.py      NEW — ForensicsPage (case-first forensics cockpit)
    ├─ mirroring.py      NEW — MirroringPage (scrcpy lifecycle)
    ├─ demo.py           NEW — DemoPage (deterministic sample dataset)
    ├─ devices.py        EXTENDED — Administration tab + AdminConfirmDialog (R-13)
    ├─ dashboard.py      boundary panel rewritten as "Honest boundaries of the
    │                     desktop shell" (per-boundary rows, no future-stage rows left)
    ├─ help.py           section list updated (all sets live)
    └─ __init__.py       exports + the four new page classes
vscanner/services/forensics.py   FIXED — typed progress-contract violation
                                 surfaced through the real desktop pipeline (§3)
tests/unit/
├─ test_stage12_desktop.py  NEW — 62 offscreen tests (§2)
└─ test_stage10_desktop.py  UPDATED — future-sections registry test (now `== ()`)
```

### 1.2 Engine seam extensions (`ui_desktop/backend.py`) — TUI-parity surface

No engine service was rewritten; the desktop layer still contains no parsing, no subprocess, no ADB literals. Each call reuses the Stage 08 services through the existing `ServiceRegistry` faces; all long work runs as Stage 04 `JobManager` jobs (typed kinds) or named `WorkerCoordinator` slots, delivered to the GUI thread through the existing queued `QtJobEventBridge`.

| Seam | Job/slot | Notes |
|---|---|---|
| `start_monitoring_session(serial, interval_s)` | `MONITORING_SESSION` | real `MonitoringService` + engine `monitoring_session_plan` (serial-bound); infinite honest poll that aborts after 3 consecutive probe failures (`SUCCEEDED` with `{"status": "aborted", "reason": …, "polls_completed": n}`) |
| `stop_monitoring(serial)` | targeted cancel | cancels ONLY `MONITORING_SESSION` jobs of that serial — never a running scan or listing (test-locked) |
| `active_monitoring_handle(serial)` | read-only | re-wrapped `JobHandle` or None |
| `start_forensics_job(serial, op, kwargs, confirmation)` | `FORENSICS_OP` | ops = `create_case` · `extract_app_data` · `system_logs` · `installed_packages` · `running_processes` · `wifi_redacted` · `wifi_cleartext` (confirmation travels to the SERVICE gate) · `report`; the `wifi_redacted` branch **rejects** a confirmation kwarg with a typed `InputValidationError` ("the wifi redacted op accepts no acknowledgement (use wifi_cleartext)") |
| `forensics_load_case(case_id)` | worker slot | real `ForensicsService.load_case` (manifest.json → typed `CaseManifest`) |
| `mirror_launch(serial, options)` / `mirror_list` / `mirror_stop` | worker slots | real `ScreenMirrorService` lifecycle (argv-only spawn, `-s`, `-m 1024`, `--max-fps 30`, `-S` NOT offered); ONE service instance per serial is cached in the backend for the session (§3) |
| `demo_bundle()` | in-process | real `DemoService` fixture build; ZERO device/ADB/history contact |
| `start_admin_job(serial, op, package, confirmation)` | `ADMIN_OP` | the ONLY three service-supported ops (`launch_app`/`force_stop_app`/`uninstall_app`); the minted `OperationConfirmation(reference="admin:<op>:<package>")` travels to the service's own `validate_confirmation` gate (R-13 §SC-5) — the backend builds NO gate of its own and cannot bypass one |

### 1.3 Live monitoring (`ui_desktop/screens/monitoring.py`)

One page, cached by the shell. An explicit device selection is the only way controls enable (device rows verified verbatim through the engine; the disabled reason is always stated inline). The poll stream is the REAL typed `HardwareUsageSnapshot` events of the engine session plan:

- **Honest observation words per row** and regardless of capability: `NOT_OBSERVED` is rendered as not-observed — **never** as "not in use"; `UNKNOWN` renders "unknown (probe failed)"; matched/unmatched output can never upgrade an absent observation.
- The copy states plainly that this is **host-side read-only polling started and stopped explicitly — NOT continuous monitoring** and nothing runs on the device (A-F01 stays excluded; dashboard boundary row §1.8).
- **Identity discipline:** only snapshots from the tracked job id whose payload serial still equals the selected target can render; late events from a finished session, foreign payloads, and events of a changed target are dropped and never overwrite the current target's results (test-locked).
- **Explicit stop** ("stop requested — the terminal event will confirm it"; state stays `stopping` until the `CANCELLED` terminal), a queued-vs-running start guard (no duplicate sessions), the engine's honest `aborted` wording rendered verbatim, and the user-initiated "sensors once" op (`dumpsys sensorservice` honesty: empty/unparseable ⇒ one `UNAVAILABLE` row; never an invented sensor row).

### 1.4 Forensics cockpit (`ui_desktop/screens/forensics.py`) — case-first flow

Typed case directory under the engine's `paths.cases_dir()` (relocate-able for tests; default production root). All device operations are `FORENSICS_OP` jobs with the engine's honesty preserved:

- **Create case** runs the real `create_case` (one root probe recorded in the manifest; duplicate case names refused with the engine's verbatim "case directory already exists: …"); **open case** reloads via the real `load_case` (typed failure when absent/unreadable — nothing invented).
- **Extract app data** (`extract_app_data_files`): byte-exact `exec-out` copies (per-record sha256/byte-count in the manifest `files` list), device-path/entry validation against traversal engine-side; a failed/unverified copy Promotes an honest note ("copy failed (su unavailable or read error)") while the succeeded count stays truthful — partial-failure honesty, no silent overwrite; a listing gap yields "listing unavailable: …".
- **One-shot text ops:** `system_logs` (logcat -d), `installed_packages`, `running_processes` — engine-written files with honest rc/gap notes.
- **WiFi (R-12):** the default op writes `wifi_networks.txt` REDACTED with the preset `default-redacted`; the unredacted `wifi_networks_cleartext.txt` (`explicit-unredacted` preset) exists ONLY through the modal that re-types the exact phrase `I ACCEPT CLEARTEXT PSK` — the page mints the typed `OperationConfirmation` for the service's `wifi_cleartext_psk` gate; cancel/mismatch dispatches nothing (exact-phrase dialog behavior itself is test-locked with a real `CleartextConfirmDialog`).
- **Report:** `generate_report` writes `report.json` with the legacy field names (`case_name`, `created`, `device`, `android_version`, `is_rooted`, `root_status`, `redaction_preset`, `files`, `extractions` — verified byte-for-byte by test); the terminal banner says "report finished: report.json written into the case folder" (see §3 for the wording plumbing).
- The manifest files table renders the engine's records (path / in-case / sha256 prefix / size / kind); case reload after every operation re-reads the REAL manifest from disk.

### 1.5 Mirroring (`ui_desktop/screens/mirroring.py`)

- **Tool preflight panel:** the engine's provisioning state for scrcpy rendered verbatim (`validated` / "found but never validated" …) with the standing copy "launches are REFUSED until the tool is validated (engine ToolProvisioningService workflow; the desktop screen does not provision tools)".
- **Lifecycle through the real `ScreenMirrorService`:** `LAUNCH_OPTIONS = MirrorOptions(resolution=1024, max_fps=30, turn_screen_off=False, …)` — `turn_screen_off` is **NOT offered** (device-mutating; would need `confirm_screen_off` and is refused by the model anyway). Launch, list, stop run via worker slots; states `starting/running/stopping/stopped/failed` are the real registry-handle facts (pid, serial, launched-at, exit code "exited (n)").
- **Duplicate prevention:** the worker-side list check returns the existing running handles and the page refuses with the pids; the launch button is additionally disabled while a launch is in flight (one in flight at a time; the not-started release path is honest). §3 documents the page-level + per-serial-cache layering versus the TUI's workspace-level duplicate guard.
- **Truthfulness:** the launch banner says "launch recorded: pid …" followed by the standing disclaimer that whether any window appears on screen is scrcpy's own display behavior and is NOT claimed or verified by this application. Stop reports the terminated pids (or "nothing was running") and re-lists handles.

### 1.6 Demo mode (`ui_desktop/screens/demo.py`)

The real `DemoService` deterministic fixture (3 apps, INFO findings titled `[DEMO] …`, `ScanSummary.demo=True`, FIXED run start/end timestamps). DEMO labeling is unmissable on every rendered row and the page header. Isolation is structural and test-locked:

- **ZERO device contact:** no transport call of any kind (call-count verified) — no ADB, no discovery, no sensors.
- **ZERO history/selection impact:** the demo bundle never passes through `remember_scan`/`history_entry` or the device selection state — the devices page's selection and the scan history are byte-identical after a demo build (asserted directly).
- An obvious "back to live data" navigation action into the real devices workspace.

### 1.7 Administration (device workspace tab, R-13 desktop gate)

Only the engine-supported ops are surfaced (`uninstall_app`, `launch_app`, `force_stop_app`) — no invented operation:

- `AdminConfirmDialog` is operation-specific (exact op word + package + target serial + impact copy including "this is a REAL device-side removal" for uninstall), and the Proceed action stays disabled until the FULL package name is typed back exactly; **cancel/dismiss/Close/Esc mints NO token and dispatches NOTHING** (typed dialog behavior test-locked).
- The target is re-fetched and re-validated immediately before submission: NEVER auto-selected, `unavailable/offline/unauthorized` targets refuse honestly, a vanished device refuses with the truthful note.
- Duplicate submissions while an `ADMIN_OP` is active for the workspace are refused (one at a time); the confirmation token is minted ONLY after the exact retyping and travels into `start_admin_job` → `AdministrationService` → the service-side `validate_confirmation` gate (stale/fresh-window enforcement is the engine's — tested for the unsupported-op/missing-token/stale-token refusals surfacing verbatim).
- **Result wording distinguishes attempted vs verified:** the rendered outcome is the operation's dispatched result ("requested …: dispatched — the device's return code is reported, the desktop does NOT re-verify the effect on the device").

### 1.8 Registry / shell wiring

`sections.py`: `monitoring`/`forensics`/`mirroring`/`demo` rows now `live` with honest descriptions (monitoring: "HOST-SIDE", "NOT continuous"; demo: "no device is contacted", "no real scan data is touched"; mirroring: "validated", "not verified", "refused"); `reg.future_sections() == ()`. `main_window.py` builds the four pages only when a backend is wired (an unwired launch keeps the honest `ErrorState`). The dashboard boundary panel now lists the standing honest boundaries (no provisioning UI / no Android-side background monitoring / no verified scrcpy-window claims / redaction by default) instead of pointing at later stages; `help.py` lists every section as live. The Stage 10 registry-state test was updated exactly once: the future set became empty and the four rows are asserted live — Stage 09/10/11 behavior untouched.

## 2. Test facts (`tests/unit/test_stage12_desktop.py`, 62 tests)

Offscreen harness extending the Stage 10 base (`FakeAdbTransport`, `pump_until`, `GUI_THREAD` identification, session `qapp` with flush/deleteLater teardown). The engine is exercised FOR REAL: `Stage12Transport` (dumpsys/logcat/ps/su cat wpa/exec-out byte surface over the Stage 08 fake) drives the REAL `MonitoringService`, `ForensicsService`, `AdministrationService`, `DemoService`, the Stage 04 `JobManager`, the queued `QtJobEventBridge`, and the extended `DesktopBackend`. `ScreenMirrorService` is the ONE faked service (a per-serial registry-seam `FakeMirrorService` with real pid/exit-code lifecycles — spawning/displaying the actual scrcpy window is out of scope for tests; §4). Pages are tracked and `shutdown()`-closed in the factory teardown (Stage-11 learning: a page left with a running worker thread aborts Windows processes once collected).

| Class | Count | Covers |
|---|---:|---|
| `TestSectionRegistryParity` | 5 | four rows flipped live with honest description words; no future rows remain; placeholder fallback still importable |
| `TestBackendMonitoringSeam` | 5 | typed `MONITORING_SESSION` job lifecycle (running → targeted cancel → cancelled), targeted stop never touches scans/listings, active-handle identity, serial-bound service construction |
| `TestMonitoringPage` | 8 | real-pipeline poll delivering snapshots ON THE GUI THREAD (captured thread id), UNKNOWN probe row, late/foreign/mislabeled-event guards, targeted stop wording, sensors-once UNAVAILABLE, aborted status rendered verbatim, duplicate-start refusal |
| `TestBackendAdminSeam` | 5 | unsupported op / missing confirmation / stale token refusals surface the SERVICE gate verbatim; minted reference parity `admin:<op>:<package>`; ops dispatch the documented legacy command shapes (`uninstall`, `am force-stop`, query-activities + `am start -n`) |
| `TestAdminDialogExactness` | 2 | Proceed disabled until the exact full package is typed (mismatch included); cancel/Esc/dismiss mints nothing and starts no job |
| `TestAdminPageFlow` | 7 | tab flow end-to-end: revalidated explicit target (vanished device refuses; no auto-selection), exact retype dispatches, success/failure OperationResult renderings distinguish "dispatched" from "verified on device", duplicate submission refused, dispatches hit the service gate |
| `TestBackendForensicsSeam` | 4 | op-map coverage incl. the `wifi_redacted` confirmation rejection typed error; `FORENSICS_OP` job kinds; report tuple handling |
| `TestForensicsPage` | 12 | case-first flow (create → auto-open of real manifest; duplicate-name verbatim refusal), open/reload honesty, byte-exact app-data extraction (sha256/byte-count verified on disk) with honest gap notes, path-traversal refusal engine-side, system logs op, WiFi defaults redacted, cleartext exact-phrase accept (real dialog) + mismatch dispatches nothing, report.json legacy fields, report wording |
| `TestMirroringPage` | 8 | preflight states/refusal words, launch through the lifecycle (recorded pid + disclaimer), duplicate-launch refusal (pids listed; disabled-button no-op regression included), handles list with exit codes, targeted stop, `turn_screen_off` not offered (and refused by the model), orderly shutdown leaves no unmanaged children |
| `TestDemoPage` | 5 | auto-build on first show, `[DEMO]` labels unmissable, ZERO transport calls and ZERO history/selection writes (asserted against `remember_scan`/selection state), deterministic content + fixed run timestamps (with the run-unique request envelope documented honestly), obvious back-to-live navigation, section wording |
| `TestShellNavigation` | 1 | all four sections round-trip through the real `MainWindow` (built once, cached, honest ErrorState when unwired) |

Engine facts locked by the tests (learned this stage): `read_sensor_values_once` parses `dumpsys sensorservice` (zero parseable names ⇒ a single `UNAVAILABLE` row); usage probes read `dumpsys media.camera|audio|location` and pair UNKNOWN with a `<capability>: probe failed or output unparseable` failure entry; the session plan aborts honestly after 3 consecutive failures with `polls_completed` in the result; the service confirmation gate compares freshly against TTL (stale tokens refused even when minted legitimately); `forensics_job_plan` flattens `(manifest, report_path)` tuples to the manifest (the report path travels via the log line, so the page bridges the wording per tracked op, §3).

## 3. Design/engine truths and fixed defects (real bugs the tests caught)

Every fix below is regression-locked by the named test:

1. **Engine progress-contract violation (`vscanner/services/forensics.py`) — fixed in the ENGINE.** `extract_app_data_files` emitted `context.progress(0, 0, …)` per file copy; `JobProgressEvent` validation requires `total > 0 or None`, so ANY extraction through a standard `JobManager` plan failed with the typed error "progress 'total' must be > 0 or None". The desktop's real-pipeline test surfaced it (the TUI path only worked because its earlier tests exercised the service without a validating progress context). Fixed to honest typed per-entry progress: `progress(entry_index, entry_total, unit="files", context=f"{source}/{entry}")` under `enumerate(listing.entries)`. Engine Stage 07 tests re-run green.
2. **Backend forensics op map missed `wifi_redacted`** — any redacted WiFi op died with "unknown forensics op". Added the branch calling `extract_wifi_networks(manifest)` (NO acknowledgement) and explicitly rejecting a `confirmation` kwarg (typed `InputValidationError` pointing at `wifi_cleartext`).
3. **Monitoring page `ObservationState.UNKNOWN` was missing from the observation-word map** — a failed probe raised `KeyError` instead of rendering an honest row; added "unknown (probe failed)".
4. **Monitoring page disabled the poll button while `running`** — a started session could NEVER be stopped from the page; enablement is now `not (running and state == "stopping")`.
5. **Forensics page inputs did not re-sync control enablement on typing** (`_case_id_input.textChanged` / `_package_input.textChanged`) — the open/extract buttons stayed disabled after typing until an unrelated event; fixed with honest enablement hooks.
6. **Mirroring launch/stop did not re-sync controls.** `_apply_launch`'s `launched` branch returned after the handle listing without `_sync_controls()`: after a successful launch the launch button stayed disabled and a subsequent duplicate-launch click was a silent no-op — the safety net "duplicate refused" could never be exercised by a real user (observed as the coverage-run flake root cause; the not-yet-synced window between a successful launch and the follow-up handle-list delivery is what made it timing-sensitive). Fixed to render + sync before listing; `_apply_stop` gained the same sync.
7. **The "launch recorded: pid … — honest window disclaimer" was a transient `setText`** that the follow-up handle refresh overwrote within milliseconds. It is now stored state (`_launch_note`) rendered by the single lifecycle renderer (order: launch-in-flight → launch failure → launch note → stop note → listing → default), and replaced by the stop outcome.
8. **Report wording plumbing:** because `forensics_job_plan` flattens `(manifest, path)` tuples, the terminal result alone cannot say "report written"; the page tracks its own op and renders the honest fixed wording (the path itself is in the engine log line and in the case folder).
9. **Backend mirror cache is per serial per session (desktop hardening).** The backend caches ONE `ScreenMirrorService` per serial for its lifetime, so duplicate-launch checks/stop see every mirror IT opened. Mirrors opened OUTSIDE a desktop session (e.g. by the TUI while the desktop shell runs) are invisible to it — an honest layering difference versus the TUI's workspace-level guard, recorded here (not tunnelled through global state to "fix").
10. **Determinism honesty for demo:** the fixture content AND the run start/end timestamps are deterministic across build; the `ScanRequest` envelope (id/created_at) is per-build by design and `Evidence.extracted_at` records the moment the fixture was assembled — a whole-`ScanResultBundle` equality assert is therefore WRONG and was replaced by a content projection + explicit run-unique-envelope assertions. (An earlier debug run of exactly that whole-bundle assert failed at a millisecond boundary — root-caused to `extracted_at`, not a fixture defect.)

## 4. Known limitations / deviations (honest)

1. **Real scrcpy window display behavior [UNVERIFIED].** Launch/list/stop lifecycle facts are tested through the per-serial registry-seam fake; the tests never spawn the real binary. The on-screen appearance of the scrcpy window on Windows remains an [M] item (the standing in-app disclaimer is exactly this honesty; the section description carries "windows display behavior of the real scrcpy window is not verified by this project").
2. **Fakes-not-hardware.** No real device, ADB binary, root, or network was involved: monitoring snapshots, forensics extraction, WiFi redaction/cleartext, admin dispatching and demo isolation ran over the documented fake transport against the REAL services. The real-device wording checks from earlier stages (`[M: real device]` rows: actual wpa_supplicant content shapes, dumpsys output shapes on modern builds, device-side results of `am`/`pm` commands) remain recorded-when-absent.
3. **Monitoring is host-side polling only.** It is NOT continuous monitoring, NOT Android-side observation (A-F01 stays excluded — no on-device agent exists), and never claims "not in use" for a not-observed capability. Poll cadence/duration is bounded by the engine's abort-after-3-failures rule; the desktop adds no retry loop.
4. **Admin op effects on a real device [M].** The desktop renders the engine's `OperationResult` (dispatched command + device rc) and explicitly does NOT re-verify the effect on the device.
5. **Windows interactive experience [M].** Every GUI test ran on the `offscreen` Qt platform; no real interactive window, display scaling, or input device was involved (same standing limitation as Stages 09–11).
6. The `cli/python usb_charging_control.py` untracked user file and the modified `.gitignore` PRE-DATE this stage and were left untouched and unstaged (repo hygiene unchanged).

## 5. Quality gates (exact results)

| Gate | Command | Result |
|---|---|---|
| Full suite A-2 | `python -m pytest tests -q` | **827 passed / 0 failed / 0 xfailed / 0 skipped**, two consecutive fresh-process runs post-final-code (~71 s each) |
| Instrumented full runs | `python -m pytest tests -q --cov=vscanner --cov=ui_terminal --cov=ui_desktop --cov=cli --cov-report=term` | **827 passed**, ×2 (~109–112 s) — these runs exposed and then verified the §3-6 mirroring control-sync fix |
| Stage 12 file | `python -m pytest tests/unit/test_stage12_desktop.py -q` | **62 passed** (stable across ≥9 fresh runs during development) |
| Stage 09–11 regression | stage 10 + 11 files | **129 passed** (incl. the updated future-sections test) |
| Lint | `python -m ruff check .` | All checks passed |
| Types | `python -m mypy` | Success: no issues found in **121 source files** |
| Byte-compile | `python -m compileall -q ui_desktop vscanner tests` | exit 0 |
| Desktop startup smoke | `python -m ui_desktop --smoke` | `DESKTOP_SMOKE_OK`, exit 0 |
| Coverage | see the instrumented command above | TOTAL **74%** (13755 statements) — Stage 12 anchors: `ui_desktop/backend.py` **94%**, `screens/monitoring.py` **89%** (446 stmts), `screens/forensics.py` **85%** (535 stmts), `screens/mirroring.py` **87%** (396 stmts), `screens/devices.py` **90%** (786 stmts, now incl. the admin tab + dialogs), `screens/demo.py` **83%** (139 stmts); detail table re-measured in `TESTING_STRATEGY.md` §6 |

**Honest mid-flight notes:** (a) one whole-bundle demo determinism assert failed ONCE during development and was root-caused to the legitimate build-time `Evidence.extracted_at` stamp — the test was rewritten as a content projection (§3-10); no engine change. (b) An earlier full-suite run failed the updated Stage 10 future-sections registry test before that test was aligned with the new registry reality (adaptation, not a product bug). (c) The documented Stage 07 export flake (unreproducible 25/25 at Stage 11) was NOT observed in any of this stage's runs. No gate was skipped; no threshold was lowered.

**Platform honesty: every GUI test ran on the `offscreen` Qt platform; the desktop monitoring, forensics, mirroring, demo and administration surfaces were NOT operated in a real interactive Windows window, and no device, ADB, root, or network was involved.**

## 6. Git record

- Implementation commit: `feat(desktop): complete feature parity and administration` (source/tests only; staged diff inspected: no binaries, no secrets, no device config; `.gitignore` NOT staged; `cli/adb_config.json` untouched; `cli/python usb_charging_control.py` untracked; `android/**` untouched).
- Docs commit: `docs(progress): record Stage 12 completion` (docs/vscanner-3: PROGRESS, ROADMAP, ACCEPTANCE_CRITERIA, FEATURE_PARITY_MATRIX, TESTING_STRATEGY, this report).
- Push: HTTPS-only `git push origin main`; `git fetch origin` + `git rev-parse main origin/main` equality verified after the docs commit.
