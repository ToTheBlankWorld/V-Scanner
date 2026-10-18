# Stage 06 — TUI Device Workspace — Implementation Report

**Branch:** `main` (base of record `7d9fade`, stack on Stage 05) · **Date:** 2026-10-18
**Scope honored:** device workspace (discovery / refresh / explicit selection / details) **plus** the app inventory browser (C-F03/C-F04/C-F06/C-F19), cancellable through the Stage 04 job system. **No Stage 07** scanning/findings work, no desktop, no installer.

---

## 1. Deliverables

### 1.1 Engine additions (narrow, contract-compatible — documented + tested)

- `vscanner/services/scanning/app_inventory.py`: `list_app_rows(include_system: bool, label_mode: Literal["legacy","exact-first"], timeout: float) -> tuple[AppInfo, ...]`
  - ONE `pm list packages [-3]` command (no per-package dumpsys/aapt chatter; legacy `list_packages()` untouched).
  - Labels ALWAYS `AppLabelSource.HEURISTIC` — the UI badge reads `derived (heuristic)` and never implies EXACT; `exact-first` degrades honestly instead of lying.
  - `is_system` established with one extra `pm list packages -s` command when `include_system=True`.
  - Non-canonical package names (a real device lists a framework package literally named `android`, which strict `AppInfo` validation rejects) preserved via `AppInfo.tolerant(...)` so listings reflect reality.
- `vscanner/services/orchestration.py`: `app_listing_rows_plan(inventory_service, include_system)` — checkpoints `before_package_listing` **and** `after_package_listing`. The post-listing checkpoint makes cancel-during-run deterministically end CANCELLED (Stage 04 semantics: a cancel request with no later checkpoint would otherwise end SUCCEEDED). One `unit="apps"` progress event. Old `app_listing_plan` untouched.
- `vscanner/services/registry.py`: `ServiceRegistry.device_info(serial=None)` — narrow SC-4 accessor returning a serial-bound `DeviceInfoService`.

### 1.2 UI seam (`ui_terminal/backend.py`)

- `DeviceBackend` Protocol (structural; every test fake implements it without importing production code) + `WorkspaceBackend` production implementation.
- `WorkspaceBackend` composes `ServiceRegistry` — cached **per adb path** from `ConfigService` (rebuilt only if the user saves a different path); lazy `JobManager(max_workers=2)` owning the JobManager lifecycle (attribute named `_manager_obj` — the `_manager` attribute/method name collision bit twice and is recorded below); one `AsyncJobBridge` pump.
- Blocking calls (`list_devices`, `profile`) are worker-thread-only; `adb_path_saved()` is UI-thread safe; `AdbNotAvailable` still raised honestly when no path is saved.
- `start_listing_job` builds the inventory service with a **serial-bound client** (`registry.client(serial)`) — the workspace's own explicit selection; no registry-global selection state is touched, so two devices can never race a listing to the wrong device.

### 1.3 App wiring (`ui_terminal/app.py`, `sections.py`, `theme.py`)

- `VScannerApp(config_service=None, backend=None)` — backend injectable for tests; `.backend` property; `BINDINGS` adds `w` → goto devices; `on_mount` starts the backend pump once; `_dispatch_job_event` fans out **only to the current `DeviceWorkspaceScreen`** (undelivered events to a non-visible screen are never faked as delivered — see §2 honesty); `action_quit` shuts the job system down (`shutdown_jobs()`) before exiting.
- `sections.devices` is now `kind="live"`, key `w`, lazily importing `DeviceWorkspaceScreen`; next future section is `scan` (Stage 07).
- `WORKSPACE_TCSS` fragment in `theme.py` (combined `app.CSS = APP_TCSS + SECTION_TCSS + WORKSPACE_TCSS`).

### 1.4 Screen (`ui_terminal/screens/workspace.py` — `DeviceWorkspaceScreen`)

- Widgets: refresh button `#ws-refresh-btn`, updated-stamp `#ws-updated`, explainer `#ws-explain`, banner `#ws-banner`, devices DataTable `#ws-devices` (Serial / State / Model-as-reported-from-usb_props), selected-hint `#ws-selected`, details DataTable `#ws-details` (Field/Value from SC-4 probes, root row via `_ROOT_WORDS`, missing → `unknown`, **no phone-number row at all**), security note `#ws-security-note`, list button `#ws-list-btn`, filter input `#ws-filter`, listing banner `#ws-listing-banner`, apps DataTable `#ws-apps` (Package / Label / `derived (heuristic)` label source / system|3rd-party kind), 100-per-page pagination (`[`/`]` keys).
- `PAGE_SIZE = 100`; filter and pagination interplay pinned by tests (filter resets page).

## 2. Honesty behaviors (the core of this stage)

- **Opening the screen runs exactly ONE auto-discovery**; every further refresh is the explicit `r`/button action.
- Refresh dedup: state guard + `run_worker(group="ws-refresh", exclusive=True, thread=True)` on the **app** (not the screen, so unmount is safe); a second refresh while one is running gives feedback, never overlap.
- A failed refresh **preserves last-good rows** marked "may be failed/stale"; `_last_success` stamp untouched; success and failure are always distinguishable on screen.
- Auto-select only when exactly one actionable (`device`-state) device exists; multi-device → explicit notify "select one explicitly"; offline/unauthorized rows are listed honestly but **refused** as selection targets; unknown state tokens (`sideload`, `recovery`, …) render raw.
- Selection kept across refreshes only if the serial is still actionable; vanished or state-changed device → selection, details and app rows invalidated with an explicit reason ("no longer connected").
- Disconnect-after-selection leaves **no fabricated data**: profile table renders `unavailable — <typed failure word>`; every missing field is `unknown`, never invented.
- Failure words are typed: `AdbNotAvailable` → guidance to check the path (Settings), timeout vs exit-code+redacted-excerpt distinguished for `AdbCommandError`, `ConfigError` → config wording, unknown → exception-type name only. All banner text passes through the engine's redaction boundary (R-12 verified by test).
- Root is the R-05 tri-state: `not determined` (UNKNOWN) vs `not rooted (verified probe)` read differently; the verified root probe itself belongs to Stage 08.
- Inventory states are job-event driven: `running` / `ok` (rows + count + page badges) / `cancelled` / `failed (typed banner)`; foreign job ids are ignored; **reconcile-on-remount**: if the tracked listing finished while the user was elsewhere, the screen says exactly that ("finished while the screen was not visible — its results could not be streamed here; press a to list again") — never "here are the results" for events it never received.
- No destructive commands anywhere; no selection persistence to disk; honest empty states for no devices / no ADB path (with Settings guidance) / no apps.

## 3. Implementation decisions recorded (for future stages)

1. **Screen has no workers of its own.** All discovery/profile workers are app-owned (`app.run_worker(group=…, exclusive=True, thread=True)`) and apply results via `app.call_from_thread`; `switch_screen` unmounts cached screens, so screen-owned workers would be cancelled mid-flight. Any Stage 08 screen with background work must follow this pattern.
2. **One dispatch point.** `_dispatch_job_event` on the app routes job events only to the currently visible workspace screen. Job-receiving screens of later stages extend this dispatcher rather than adding their own subscriptions (one pump, one subscription).
3. **Name collision pitfall (bit twice):** a class attribute and a method with the same name (`_manager`, `_registry`) — the attribute silently shadows the method and the call site throws `TypeError: 'NoneType' object is not callable` at runtime. Backend internals are therefore named `_manager_obj`/`_registry_obj`. Keep this convention.
4. **`JobHandle.id` / `.kind` / `.device_serial` / `.state` are properties** (not methods) in the engine — fakes and UI code must not call them.
5. **Textual 8 pin realities:** DataTable default cursor is `cell`; the device rows must be selectable with enter, so `#ws-devices` is constructed with `cursor_type="row"`. DataTable cells are NOT Labels — `_visible_text` (Label query) cannot see table content; tests read cells via `get_row_at`.
6. The registry stays a **per-path cache**, never a global selection holder for the workspace; services are constructed serial-bound for each operation.
7. Inventory labels are heuristic by design in Stage 06; the exact-label path (`aapt`/labelRes "when reachable") stays a documented deferral — the UI badge `derived (heuristic)` is the honesty mechanism, not an apology.

## 4. Test additions (+47 → 446 total, all headless)

| File | Coverage |
|---|---|
| `tests/unit/test_stage06_engine.py` (10) | `list_app_rows`: third-party rows heuristic-sourced, `-s` system set, typed command failure, honest empty result, exact-first honesty (never EXACT), tolerant non-canonical names; `app_listing_rows_plan`: one progress event, pre/post checkpoints, cancel-before-run → CANCELLED without running any command; `ServiceRegistry.device_info` serial binding; registry select rejects unusable state (offline → typed error with serial detail). |
| `tests/unit/test_device_workspace.py` (31) | Navigation/registry/palette contract for the live `devices` section (`w`, escape, instance cache); discovery honesty: exactly-one auto discovery, empty state, missing ADB guidance, multi-device never auto-selected, single-device preselection + probe, unknown-field `unknown` rendering, offline/unauthorized refusal with feedback, unknown state tokens, typed failure banners (not-launchable / timeout vs exit-code), last-good preserved + "may be stale" after failure, recovery, in-progress feedback without overlap, selection preserved / invalidated (vanished, turned-offline); details: not-checked, probe failure honest, verified-profile wording, redaction (`hunter2` never appears); inventory UI: selection required, started/ok/badges, failed/cancelled terminal wording, foreign-job events ignored, filter + 3-page pagination, system-apps toggle re-lists, cancel binding; away reconciliation honesty. |
| `tests/unit/test_inventory_ui.py` (4) | Full production pipeline with ONLY the ADB subprocess faked (monkeypatched `SubprocessAdbClient` in the registry module, never a real device): screen → WorkspaceBackend → ServiceRegistry → `list_app_rows` → `app_listing_rows_plan` → JobManager thread → AsyncJobBridge → app dispatch → rows on screen (200 apps → 2 pages); serial-bound listing client assertion; cancel mid-listing honours CANCELLED via the post-listing checkpoint (deterministic blocked-command gate); typed failure banner delivered through events. |
| `tests/unit/test_import_architecture.py` (+1) | Stage 06 guard: presentation screens/`app`/`sections`/`theme`/bridge must not import `subprocess` or ADB-transport modules directly (only the sanctioned `ui_terminal.backend` seam; `vscanner.services.adb.executable` path-facts module remains sanctioned for the Stage 05 settings screen). |
| `tests/unit/test_tui_entry.py` (+1) | Stage 06 doc-consistency: every `DeviceWorkspaceScreen.BINDINGS` key documented in `TUI_KEYMAP.md` + the "Device workspace keys" section exists. |

## 5. Verification results (exact)

| Gate | Command | Result |
|---|---|---|
| Full suite | `python -m pytest -q` | **446 passed, 4 xfailed** (~62 s; device/network/root-free; xfails R-04…R-07 unchanged, strict) |
| Coverage | `python -m coverage run -m pytest -q` + `report` | **TOTAL 55%** (6338 stmts; up from 51%). Stage 06 anchors: `workspace.py` **92%**, `backend.py` **90%**, `app_inventory.py` **95%**, `orchestration.py` **100%**, `registry.py` **86%** |
| Lint | `python -m ruff check .` | All checks passed |
| Types | `python -m mypy` | **Success: no issues found in 76 source files** (was 71 at Stage 05) |
| Bytecode | `python -m compileall -q ui_terminal vscanner` | exit 0 |
| Architecture guards | (within suite) import-cycle, framework-independence, no-`shell=True`, no-pip, layering AST tests + new UI-subprocess guard | green |
| Startup AC | timed headless launch + non-interactive guard | 0.163 s ≤ 2 s (`w` → DeviceWorkspaceScreen reachable); non-TTY exit 0 with guidance |
| Post-commit | full suite re-run after the code commit | **green** (446 passed / 4 xfailed). One anomalous data point interleaved: a single full-suite run (2 of 4 observed) flipped the pre-existing Stage 04 race test `test_services_jobs.py::TestConcurrency::test_cancel_vs_success_race_resolves_deterministically` under suite-timing pressure; three subsequent runs (2 full + module-scope) were green. Not touched and not weakened: `vscanner/services/jobs.py` and its test file are untouched since Stage 04 (`2a9d548`) — recorded as a pre-existing intermittent narrow race for the Stage 08 hardening pass. |

## 6. Honest limitations (this stage does NOT claim these)

- **No real device hardware was attached** — all selection/details/listing evidence is from the Textual headless harness with engineered fakes (FakeBackend) and a monkeypatched subprocess transport (fake runner). [UNVERIFIED] on physical hardware remains true for C-F03/C-F04/C-F06/C-F19 device-path behavior.
- App labels are `derived (heuristic)` only; exact labels via `aapt`/labelRes stay deferred per FEATURE_PARITY_MATRIX C-F06 ("when reachable").
- Root shows the R-05 tri-state; the *verified* root probe (dangerous/permissioned commands) belongs to Stage 08 — until then `not determined` is the honest answer.
- The engine deliberately exposes **no phone-number fact**; the workspace renders no such row instead of reproducing the legacy hardcoded `N/A` placeholder.
- Device rows show model "as reported" from `usb_props` — if a device's state line omits it, the cell honestly stays empty/unknown.
- Un-delivered job events (screen away) are never back-filled; the reconcile banner asks the user to re-list.

## 7. Risks / follow-ups for later stages

- Stage 07 (scanning/findings) should extend `_dispatch_job_event` for `JobFindingEvent`/snapshot streams and add a finding-source screen; the pump/dispatcher pattern is in place.
- `start_listing_job` re-uses the serial-bound client; a Stage 08 root probe should follow the same per-operation serial binding.
- Job conflict (`JobConflictError`, one job per device) surfaces as an honest banner; a queued-jobs UX can be revisited later without contract change.
- Textual 8.2.8 pinned `<9` — §3 point 5 must be re-verified on any major bump.
