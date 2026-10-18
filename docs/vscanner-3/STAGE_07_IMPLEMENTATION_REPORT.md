# Stage 07 - TUI Scanning and Findings - Implementation Report

Status: **COMPLETE** (2026-10-18; code commit 3e83103 - feat(tui): add scanning and findings workflows). Scope: scan screen (`f`), reports & history
screen (`h`), the T-08 local scan-history store, and the Stage 04 §5
cancel-vs-success race follow-up. No Stage 08 work (admin ops, sensors,
monitoring, forensics) is included.

## 1. Deliverables

### 1.1 Engine additions (narrow, contract-compatible)

- `vscanner/services/history.py` — new **T-08 ScanHistoryStore**: one plain
  JSON file per scan in `paths.history_dir()` (new `core/paths.py` accessor),
  capped retention (`CAP = 30`, oldest evicted), `HISTORY_SCHEMA_VERSION = 1`,
  `created_by = "vscanner/3.0"`. Entries are `HistoryEntry` frozen dataclasses
  and carry **counters only** — severity counts (all five keys, zero-padded),
  app totals, status word. No findings text, no evidence excerpts, no secret
  material ever reaches the store (test-locked). Reads are tolerant: a
  corrupt or truncated entry file is skipped and counted as unread, never
  crashing `recent()`; unreadable directory raises the typed
  `HistoryStoreError`.
- No scanner, job-manager, risk-engine, or orchestration changes: the scan
  screen runs the existing `ScanService` through the Stage 04
  `full_device_scan_plan` / `scan_single_app_plan` factories, export runs the
  existing `ReportService` through the `report_export_plan` (SC-9). The TUI
  reimplements zero analysis or serialization logic.

### 1.2 UI seam (`ui_terminal/backend.py`)

`DeviceBackend` Protocol and `WorkspaceBackend` gained the Stage 07 surface:

- `start_scan_job(serial, include_system, deep, package)` — builds the typed
  `ScanRequest`, submits through the plan factory; scan jobs share the
  per-device `"scan"` mutex group with listing, so a conflict is impossible
  to double-book silently (`JobConflictError` surfaces as a typed failure).
- `cancel_scan_job(serial)`, `active_scan_handle(serial)`.
- `remember_scan(bundle, status, serial)` / `last_scan()` — in-memory
  last-terminal-scan slot. **Only completed bundles are remembered**;
  cancelled/failed scans get a status word without a bundle, which is what
  makes "not exportable" honest.
- `start_export_job(bundle, output_dir, serial)` — runs the SC-9 export plan
  in a job; empty directory string means the legacy `reports` default.
- `history_entry(entry)` / `history_recent()` — the store is injected via an
  optional `history:` constructor parameter (tests inject a tmp-path store;
  production default resolves `paths.history_dir()`).

### 1.3 Screens

- `ui_terminal/screens/scan.py` (`ScanScreen`, SECTION_ID `"scan"`, binding
  `f`): own device discovery (same honesty rules as the workspace — one
  auto-discovery per open, explicit refresh, offline/unauthorized refused),
  **preflight revalidation worker** (the selected device is re-checked
  immediately before every scan start; a stale target produces a failed scan
  request, never a silent target switch), scope toggles `t` (system) and `u`
  (deep), `n` single-app input validated via `validate_package_name` before
  any work starts, `a` full-device scan, streaming findings via
  `JobFindingEvent`, honest progress text (real event counts only — skipped
  apps are named), `c` cancel (explicitly a cancel *request*, not an ack —
  the terminal state decides what is shown), away-reconciliation
  (`_reconcile_scan_after_away` — a terminal that arrived while the screen
  was hidden is surfaced as "results could not be streamed here", never
  fabricated), and the findings explorer: `v` severity-threshold cycle,
  `g` category cycle, `o` deterministic sort cycle, text filter input,
  `[`/`]` pagination (100/page), `enter` detail panel with kind, severity,
  evidence sources (redacted per R-12), remediation, and provenance.
  Terminal scans append one T-08 history entry (worker thread; a write
  failure notifies honestly and never alters the reported outcome).
- `ui_terminal/screens/reports.py` (`ReportsScreen`, SECTION_ID `"reports"`,
  binding `h`): export via `start_export_job` — only the last *completed*
  bundle; cancelled/failed scans display "not exportable" instead of a
  button that would pretend. Success lists exactly the paths from
  `ExportResult.formats_written`; service-reported failure or a failed
  terminal job renders "nothing is claimed as saved". The T-08 history table
  (`r` refresh) renders the store's entries and says
  "scan history unavailable: …" when the store cannot be read — it never
  shows a fake empty state for a read failure.

### 1.4 Wiring

`sections.py` scan/reports now live; app bindings `f`/`h`;
`_dispatch_job_event` fans out to the current screen among
workspace/scan/reports (job-id filtered); theme adds `SCAN_TCSS` and
`REPORTS_TCSS` fragments (no raw colors; detail panel visibility is toggled
via Python `display`, since an id rule would beat a class rule in Textual).

## 2. Honesty behaviors (test-locked)

- Progress and counts come only from real engine events; nothing is
  estimated. Skipped apps are named, not hidden.
- Unknown ≠ safe, unavailable ≠ passed: a finding the engine did not report
  is never invented; a zero-findings screen states it is **not thereby
  certified secure**.
- Cancelled/failed scans keep whatever findings actually streamed, labeled
  PARTIAL; they are not exportable and do not overwrite the last completed
  bundle.
- History write failure never fakes the scan outcome — the scan result stays
  authoritative and a warning names the history problem.

## 3. Stage 04 §5 follow-up: wait-vs-delivery race (closed test-side)

**Root cause (empirically confirmed):** `JobHandle.wait()` returns at
terminal-*state* claim — `terminal_event.set()` fires under the state lock
inside the state transition — before `_dispatch` delivers the terminal
*event* to subscribers. A stress harness (`stress_race.py`, 4000 iterations
of subscribe-then-start-then-wait) reproduced the window **9/4000 runs**,
always `state=JobState.SUCCEEDED, terminal count 0`.

**Disposition:** a redesign that blocks `wait()` on delivery was rejected —
`JOB_AND_EVENT_CONTRACTS.md` §6 already forbids calling `wait()` from
event-loop/subscriber threads, and making delivery a precondition of `wait()`
would deadlock exactly those callers. The jobs.py exactly-one-terminal
invariant is intact; the fix is **test-side only** (`vscanner/services/jobs.py`
unchanged): the test `_Recorder` gained Condition-based
`wait_delivered(predicate, timeout)` / `wait_terminal(minimum, timeout)`, the
two TestConcurrency tests and two TestCancellation tests were hardened with
`events.wait_terminal()`, and six new deterministic ordering tests were added
inside `TestConcurrency` (queued-cancel via a `max_workers=1` blocker,
RUNNING-cancel honest success, cancel-request checkpoint acknowledgement,
cancel-vs-failure first-terminal-wins, late-cancel no-op, and a
blocker-subscriber semantics pin). `test_services_jobs.py` passes 44/44 on
three consecutive runs. **This contract subtlety is documented for Stage 08
subscribers** (real pump threads must consume events, not infer outcomes
from `wait()`).

## 4. Test additions (+51 → 505 total, all headless)

- `tests/unit/test_stage07_engine.py` (15): demo scan through the real job
  pipeline (streamed finding ids == bundle ids; Stage 03 golden anchors
  READ_SMS/CRITICAL + sdk_compat), progress events, deterministic mid-scan
  cancellation gate (CANCELLED terminal; the partial stream pins
  `["a0af51ee…", "1256caf8…", "ea90175a…", "a0af51ee…", "c848e8e8…"]` — the
  duplicated INTERNET id is the documented Stage 03 parser quirk), overlap
  conflict refused, single-app typed result, bad package → FAILED terminal,
  history roundtrip/cap/corrupt-tolerance/typed-error/no-secrets, export via
  plan (3 formats, ok=True), export byte-identity with direct
  `ReportService.export`, unwritable destination → FAILED + `ExportError`.
- `tests/unit/test_scan_screen.py` (24): discovery/preselect, multi-device
  no-auto-select, start requires selection, successful scan fills findings +
  history, honest failure terminals, stale-device preflight block, no
  overlap, typed conflict failure, single-app validation, scope toggles,
  cancel routing, cancelled-keeps-PARTIAL, failed-after-streaming, history
  write failure, away reconciliation, active-job survival, foreign-event
  filtering, and the explorer suite (filters never mutate results, text
  filter, deterministic sorts, 150-finding pagination, detail provenance,
  unknown row never fabricated, zero findings never claim security).
- `tests/unit/test_reports_ui.py` (12): history rows + refresh, honest read
  failure, empty state, export gating (no bundle / cancelled bundle),
  success shows only service paths, service-reported failure, failed
  terminal, output-dir passthrough, foreign terminal ignored, double-export
  refused.
- Doc-consistency: `test_tui_entry.py` gained scan/reports keymap guards;
  `test_tui_app.py` placeholder test retargeted to the remaining future
  section ("monitoring"). No Stage 02–06 test weakened; the 4 strict xfails
  (R-04…R-07) are unchanged.

## 5. Verification results (exact)

- `python -m pytest -q` → **505 passed, 4 xfailed, 0 skipped** (~107 s;
  no device, network, or root).
- `python -m ruff check .` → All checks passed.
- `python -m mypy vscanner ui_terminal` → Success: no issues in 49 files.
- `python -m compileall -q vscanner ui_terminal tests` → clean.
- `test_services_jobs.py` → 44 passed ×3 consecutive runs.
- Non-interactive `python -m ui_terminal` → exit 0, honest guidance.
- Scan-screen suite re-run stable (24 passed twice in a row).

## 6. Honest limitations (this stage does NOT claim these)

- **Synthesized scan_id at cancel time:** when a scan is cancelled or fails,
  the screen synthesizes the history `scan_id` from the TUI-side job handle,
  because the engine request id is not observable from the cancel seam. The
  id is stable within the session but is not the engine's request id. This
  is a T-08 schema note, not a correctness claim.
- **Away-loss limitation:** findings streamed while the screen was hidden
  are not retro-displayed; the away-reconciliation banner says so and asks
  for a re-scan. The bundle itself is complete once remembered; only the
  live stream is lost.
- **Export scope:** one bundle at a time, last completed scan only, no
  format subselection (all three formats, matching SC-9), no format
  customization UI; legacy timestamped naming prevents overwrite.
- **Single parser source:** the duplicate stable-id parser quirk (Stage 03)
  is preserved — the findings table keys rows by view position, so a
  duplicate id can never collide or crash; the quirk itself is engine-owned
  and documented there.
- **No real-device verification:** everything is proven against the scripted
  transport and the Stage 03 golden fixture, matching the Stage 06
  methodology.

## 7. Follow-ups for later stages

- Stage 08 pump subscribers must treat `wait()` as state-claim only (§3
  above) — event consumption is the only honest terminal signal.
- T-08 severity-count aggregation across runs is available
  (`severity_counts_complete()`) but deliberately unrendered until a
  consumer needs it.
- Real-hardware verification of the deep-scan URL path remains Stage 08
  (C-F11, unchanged from the parity matrix).
