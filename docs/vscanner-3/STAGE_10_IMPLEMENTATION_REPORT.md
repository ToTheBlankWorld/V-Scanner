# V-Scanner 3.0 — Stage 10 Implementation Report

**Stage:** 10 — Desktop dashboard and device management (PySide6)
**Scope:** Truthful dashboard; device discovery/selection; device details with honest root tri-state; installed-app inventory browser (search/filter/system toggle/pagination/provenance); cancellable APP_LISTING jobs through the Stage 04 system; Stage 10 settings ADB validation.
**Status:** COMPLETE with a recorded scope deviation (admin operations deferred — see §1.7 and §4).
**Date:** 2026-10-18
**Branch:** `main` (base `2713019`, the Stage 09 docs head).

---

## 1. What was delivered

### 1.1 Package layout changes

```
ui_desktop/
├── backend.py          NEW — DesktopBackend: the Qt counterpart of the TUI's
│                       WorkspaceBackend seam (engine composition; UI-thread-safe
│                       cheap reads; worker-only blocking calls; JobManager owner)
├── workers.py          NEW — CallWorker + WorkerCoordinator: named single-flight
│                       background slots with queued GUI-thread delivery
├── app.py              bootstrap now creates DesktopBackend(config_service) when a
│                       config service is present and always passes it to MainWindow
├── main_window.py      owns the QtJobEventBridge (attached to backend.manager()),
│                       optional `backend` kwarg, devices-section builder wiring,
│                       activate()/shutdown() lifecycle for section widgets
├── sections.py         `devices` registry row: future → LIVE (Stage 10 owner)
├── settings_dialog.py  ADB "Validate path now" flow added (signature unchanged in
│                       positional order: (config_service, parent, *, adb_probe))
├── theme.py            QSS for QTableView/header/QTabWidget/QCheckBox (same token
│                       source; hex centralization still AST-locked)
└── screens/
    ├── dashboard.py    REBUILT — truthful environment readiness; ADB state answers
    │                   "not checked" until an explicit user-initiated probe
    ├── devices.py      NEW — the device workspace (§1.3)
    └── __init__.py     exports build_dashboard/build_doctor/build_help_section/
                        build_placeholder + DeviceWorkspacePage
```

### 1.2 Engine seam (`ui_desktop/backend.py`) — call discipline identical to the TUI

`DesktopBackend` composes the existing engine pieces (`ServiceRegistry`, `JobManager(max_workers=2)`,
`app_listing_rows_plan`, `PackageInventoryService`, discovery/info/root services via the registry).
No engine service was changed; no parsing, no subprocess, no ADB literals in the desktop layer.

| Method | Thread contract | Notes |
|---|---|---|
| `adb_path_saved` | UI-thread safe | config-file read only (cheap) |
| `list_devices()` / `profile()` / `full_profile()` | **worker-only** | blocking subprocess-surfaced engine calls (SC-1/SC-2/SC-4, TUI parity) |
| `start_listing_job(serial, include_system=False)` | submit → queue | cancellable Stage 04 `APP_LISTING` job with a serial-bound client (no registry-global state) |
| `cancel_listing_job(serial)` | idempotent request | `manager.cancel_device_work(serial)`; request ≠ acknowledgement (contract §5) |
| `active_listing_handle(serial)` | read-only | most recent non-terminal `APP_LISTING` handle for the serial, or None |
| `shutdown_jobs()` | close-time | `JobManager.shutdown()`; called from `MainWindow.closeEvent` |
| `manager()` | lazy singleton | one JobManager per application session (TUI parity; `max_workers=2`) |

### 1.3 Device workspace (`ui_desktop/screens/devices.py`)

Three tabs inside one workspace page, one widget cached by the shell (never rebuilt on revisit):

**Devices tab — discovery + selection.** "Refresh devices" runs exactly one `adb devices`
probe via a `WorkerCoordinator` slot (`refresh_devices`); overlapping refresh is refused
at the slot level and the button disables while pending, so the control itself cannot stack
two probes. Startup auto-runs the first refresh once (clearly labeled on the banner).
- Idle banner: "discovery has not run yet — nothing probed while idle; Refresh devices runs one probe."
- Rows render the raw parser output verbatim: serial, state token value, transport value, and the
  optional `model:` prop only when adb actually reported it (no fabricated fields). A mixed
  table keeps OFFLINE / UNAUTHORIZED / RECOVERY / ABSENT rows listed — never filtered silently.
- **Selection rules (Stage 06 parity):** auto-select ONLY when exactly one device is present;
  with 2+ devices nothing is auto-selected ("nothing is auto-switched" honesty, target controls
  disabled with the reason). Selection survives refresh across the same serial; a device that
  disappeared invalidates the selection with the truthful note "S1 is gone after the last
  refresh" style banner; a failed refresh keeps the LAST successful rows visible and marked
  stale ("do NOT prove the devices are still connected") with all target-dependent controls
  disabled until a later successful refresh re-validates them. OFFLINE targets are never
  auto-selected and cannot start listing.

**Details tab — honest full profile.** "Load full profile" (one worker slot, deduped) reads the
engine's basic profile + root evidence: `Model`, `SDK level` and every other field render the
engine value or "not reported" — nothing synthesized. Root status renders the verified tri-state
(RootStatus row, "not reported" where the probe evidence doesn't prove a verdict):
- `su -c id` returning `uid=0` → "ROOTED (verified)" — root access proven.
- Refusal chain (`su` fails, not on PATH, unmanaged package probe succeeds) → `NOT_ROOTED` —
  the analysis card explains the verdict was relayed, not verified by us.
- Any probe error/raise → `UNKNOWN` with the specific reason. **A failed details read never
  produces a root verdict** (details banner: "details read failed", tri-state preserved as
  "not reported").

**Apps tab — installed-app inventory.** `QAbstractTableModel` + `QTableView` fed by the real
`PackageInventoryService.list_app_rows` (no package parsing in the desktop layer):
- Search filter (substring over package AND label, non-mutating view over the row list), a
  system-apps toggle feeding the next listing (`include_system`), and page navigation.
- Pagination fixed at `PAGE_SIZE = 100` (Stage 06 documented contract), boundaries tested at
  150 rows (3 pages: 100 / 50 / 0; Prev disabled on page 0, Next disabled on the last page).
- Provenance badges: HEURISTIC → column shows "inferred (derived)" (kind column: "3rd party"
  or "system"); the banner states the labels are derived guesses, wording tested.
- Listing runs as a cancellable `APP_LISTING` job; Cancel is visible while running, hidden
  otherwise; a cancelled job leaves NO partial rows ("no partial rows" banner wording tested);
  a failed listing renders the typed engine message (never a crash, never fake rows); a timed
  drive surfaces "listing failed … timed out"; late events from superseded jobs (job-id no
  longer tracked) never touch state.
- Busy listing disables the start control (no second stacked submission; honest overlap
  prevention at the workspace surface — see §3 note).

### 1.4 Worker framework (`ui_desktop/workers.py`)

`CallWorker` (QRunnable-style object owning a daemon `threading.Thread`) + `WorkerCoordinator`
(QObject registry) with **named single-flight slots** (`refresh_devices`, `load_details`,
`check_adb`…): `run(slot, func, on_done, on_fail)` returns `False` when the slot is already
pending (refusal, never queuing). Delivery is a **two-hop queued bridge, mirroring the Stage 09
hub rule**: the worker thread emits `CallWorker`'s finish signal, the bridge handlers re-emit on
the coordinator's OWN signals, and Qt queues that emission to the coordinator's GUI-thread slot.
A plain lambda connection would be a DIRECT connection (no receiver QObject) and would run
page handlers on the worker thread — the hop is required, not cosmetic; a test proves the
callable runs off-GUI while the delivery lands on the GUI thread. Retired connections are
disconnected exactly once so repeated refreshes cannot accumulate signal connections;
`close(join_timeout)` returns the abandoned-slot names (daemon threads cannot block shutdown).
Used for: device discovery, details probes, ADB-check (settings + dashboard). Long-running
cancellable device work stays on the Stage 04 `JobManager` (no second executor framework).

### 1.5 Truthful dashboard (`ui_desktop/screens/dashboard.py`)

Rebuilt: real config state via `ConfigService` snapshot, real engine-package state via
`services.doctor`, and the ADB tool line answers **"not checked"** until an explicit
user-initiated probe ("Check ADB availability" button → one background `adb version` probe
through the engine's `check_adb_valid`, deduped slot; the probe never runs during
construction). The probe result is rendered as a real state (chip + textual status) —
failed probe is an honest ATTENTION state, never a crash and never a fabricated "OK".
Engine-unavailable environments run the dashboard with `adb_probe=None` and show the
"not checked" state permanently (honest, tested).

### 1.6 Settings validation (Stage 06 [T] item from Stage 09's deferral list)

`SettingsDialog` keeps its Stage 09 persistence contract untouched and adds a user-initiated
"Validate path now" control: one `adb version` probe of the TYPED path in a background
worker slot (deduped; second press refused honestly while pending), inline status label
with truthful wording ("validating — one adb version probe …", "adb is valid", the typed
error text, or "probe failed — it may not be an adb executable"). Never at construction,
never on save; save flow unchanged. Signature stays `(config_service, parent=None, *,
adb_probe=None)` — `adb_probe` swaps the engine's `check_adb_valid` for the deterministic
test hook; production default is the real engine probe.

### 1.7 Scope deviation: admin operations deferred

ROADMAP Stage 10 scope included "admin operations with confirmation dialogs". They are
**not started** in this stage: the admin ops require destructive device-side commands
(install/uninstall/clear/fustop/launch) and their R-13 + OperationConfirmation desktop
surface is a full feature of its own. No destructive device command exists in the desktop
layer; nothing about admin ops is faked. The devices registry row honestly says what Stage 10
delivers (discovery/selection/destination/inventory). Owner: Stage 12 parity pass (desktop
column), and the deferral is recorded in ROADMAP/AC/PROGRESS as the real clarification, not
silently dropped.

### 1.8 Shutdown and lifecycle

`MainWindow.__init__(..., backend: Optional[DesktopBackend] = None)` owns one
`QtJobEventBridge` attached to `backend.manager()` (when a backend exists — engine-only
tests without PySide6 keep working with `None`); `closeEvent` runs the strict order:
detach bridge → `activate()`-paired `shutdown()` on every cached section widget
(devices page disconnects its hub slot and closes the worker coordinator) →
`backend.shutdown_jobs()`. Double-close stays safe (detached bridge no-op; tested).
A devices section without a backend renders an honest `ErrorState`
("No engine configuration is wired") — never a blank widget.

## 2. Test harness facts (new `tests/unit/test_stage10_desktop.py`, 67 tests)

Offscreen harness (`QT_QPA_PLATFORM=offscreen` before import; session `qapp` reused via
`QApplication.instance()`; deterministic event pumping with `processEvents` — no blocking
waits). The engine is exercised for real: a `FakeAdbTransport` runs the actual
`DeviceDiscoveryService` / `DeviceInfoService` / `RootStatusService` /
`PackageInventoryService` / `app_listing_rows_plan` / `JobManager` /
`QtJobEventBridge` stack; only `ServiceRegistry` is swapped (instance-level injection).
Deterministic failure/hold knobs: `fail_devices_after`, `fail_listing`, `fail_listing`-timeout,
`root_mode` (not_rooted / rooted / unknown), a `list_gate` Event for hold-then-cancel tests.
The manager's real ThreadPoolExecutor is used — cancellation, terminalization and
pruning behavior are the production behavior, not a double.

Coverage classes (67): worker coordinator lifecycle (7), registry/backend seam (8
incl. timeout-failure, active-handle lifecycle, terminal→synthetic-rows), dashboard honesty
(6, module-level guard incl. idioms locked), discovery (7), selection (5),
details/root tri-state (7), inventory (18 incl. 150-row pagination / search / provenance /
cancel / late-event / busy-control / responsiveness), settings validation (5),
error+architecture (4, incl. no subprocess/adb/os.system in any Stage 10 module and no
RTFM-style device literal), hub delivery exactly-once-on-GUI-thread (1), window close
(1), repeated navigation/archive re-entry (2).

## 3. Design notes recorded for the future (engine truths learned)

- `JobTerminalEvent` carries `job_id` but **no `device_serial`** — terminal identity is the
  tracked job id (TUI workspace parity); page state supersedes by comparing against the
  current pending job id.
- `APP_LISTING` is **not** in the JobManager's `_MUTEX_GROUPS` and its default scope is
  PER_DEVICE *conflict checking* — so the manager does not typ refuse a second overlapping
  listing submit by itself. The TUI already prevents overlap at the workspace surface
  (loading state disables the control), and Stage 10 keeps exactly that honest UI-level
  discipline (`active_listing_handle` exists for ownership evidence; a test documents the
  manager behavior). Documented here and in TESTING_STRATEGY rather than silently.
- PySide6 pitfalls added to the Stage 09 list: `QItemSelectionModel` lives in
  `PySide6.QtCore` (not QtWidgets/QtGui as commonly assumed); `QAbstractTableModel`
  overrides must use `QModelIndex | QPersistentModelIndex` for mypy LSP-clean signatures;
  a per-session `qapp` fixture teardown that explicitly `deleteLater`s every remaining
  top-level widget before interpreter shutdown eliminates a nondeterministic PySide6
  static-teardown abort (0xC0000409/0xC0000005) at process exit.

## 4. Known limitations and deferred functionality (honest)

| Item | Status | Owner |
|---|---|---|
| Admin operations (install/uninstall/clear/force-stop/launch) with confirmation dialogs | Deferred — scope deviation recorded in §1.7; no destructive device command in the desktop layer | Stage 12 |
| Real-device [M] verification (C-F03/04/06/19 desktop rows) | This environment ran only the offscreen harness with faked ADB (documented transports); no device, no ADB binary, no network was involved. The [M] manual run remains optional-but-recorded-when-absent per AC Stage 06 wording | Stage 12/manual |
| Scan/reports/monitoring/forensics/mirroring/demo screens | Honest placeholders (Stage 11/12 scope) | Stages 11–12 |
| Windows real-window launch for the devices workspace | Offscreen-only here (same [M] caveat as Stage 09) | manual |
| `ui_desktop/__main__.py` coverage | Uncovered by design (thin launcher; smoke-run externally) | — |

## 5. Quality gates (exact results)

| Gate | Command | Result |
|---|---|---|
| Full suite ×2 | `QT_QPA_PLATFORM=offscreen python -m pytest -q` | **707 passed** (was 640 + 67 new), 0 failed/skipped — runs ≈ 62 s and ≈ 61 s, both with clean process exits |
| Stage 10 offscreen file | subset | **67 passed** (also ×5 consecutive single-file repeats, each clean-exit) |
| Desktop + jobs integration repeat | `test_stage09_desktop.py + test_stage10_desktop.py + test_jobs_integration.py` | **118 passed ×3 consecutive** (job/event determinism re-check) |
| Architecture/import guards | `test_import_architecture.py` + `test_jobs_integration.py` + Stage 10 module-layer guards | passing (included in the 707) |
| TUI/CLI/bridge regression | `test_tui_app.py`, `test_tui_entry.py`, `test_jobs_bridges.py` | **37 passed** (unchanged TUI runtime; Stage 04 stub contract untouched) |
| Lint | `python -m ruff check .` | All checks passed |
| Types | `python -m mypy` | Success: no issues found in **113 source files** (was 109; +4 Stage 10 modules) |
| Byte-compile | `python -m compileall ui_desktop ui_terminal vscanner tests` | exit 0 |
| Desktop startup smoke | `python -m ui_desktop --smoke` (offscreen) | `DESKTOP_SMOKE_OK`, exit 0 |
| Coverage (ui_desktop detail) | `coverage run -m pytest <desktop files>` + `coverage report --include=ui_desktop/*` | TOTAL **91%** — backend 98%, workers 95%, screens/devices **93%**, dashboard 94%, settings 98%, theme 98% |

**Platform honesty: every GUI test in this stage ran on the `offscreen` Qt platform; the
exercise recorded above was executed on Windows (Python 3.12.10, PySide6 6.12.0), but the
desktop devices workspace was NOT operated in a real interactive Windows window, and no
ADB/device/network was involved.**

No gate was skipped.

## 6. Git record

- Implementation commit: see `PROGRESS.md` Stage 10 record — `feat(desktop): add dashboard and device management` (policy: source/tests only; no `.gitignore`, no `cli/adb_config.json`, no `cli/python usb_charging_control.py`, no `android/**`, no binaries/secrets).
- Docs commit: `docs(progress): record Stage 10 completion`.
- Push: HTTPS-only `git push origin main`; `git fetch origin` + `git rev-parse main origin/main` equality verified after the docs commit.

## 7. Stage boundaries honored (mission compliance)

- Only dashboard/devices/worker-seam/settings-validation work shipped; scanning/findings,
  reports, monitoring, forensics, mirroring, demo screens and installer work are NOT
  started (placeholders remain honest).
- The engine consumes no Qt; the desktop layer consumes the engine through the seam with
  no subprocess/ADB literals; `ui_terminal` unchanged (37-test regression).
- Stage 04 job/event contracts are the only bridge model; `JobManager` is created lazily
  by the backend and shut down only by the shell.
- Unrelated user changes preserved untouched throughout.
