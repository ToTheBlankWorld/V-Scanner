# Stage 04 — Job Lifecycle and Event System — Implementation Report

**Stage status: implementation complete, verification green (see §6). Commit + push recorded in PROGRESS.md.**

This stage implemented the framework-free job system (`vscanner/core/events.py`, `vscanner/services/jobs.py`), the orchestration plan factories that route Stage 03 services through it, cooperative-cancellation seams inside `ScanService` and `ToolProvisioningService`, the two headless UI bridge stubs, and the disposal/monitoring-facing APIs — with the legacy CLI untouched (adoption is a Stage 05+ UI decision, backward compatibility preserved).

---

## 1. Deliverables

### 1.1 Engine package additions (all `from __future__ import annotations`, Python ≥ 3.10, stdlib only)

| Module | Contract | Notes |
|---|---|---|
| `core/events.py` | `JobState`/`JobKind`/`JobConflictScope` enums, `OperationConfirmation`, frozen event dataclasses (`JobStartedEvent`, `JobProgressEvent`, `JobLogChunkEvent`, `JobFindingEvent`, `JobSnapshotStreamEvent`, `JobTerminalEvent`) + `event_category()` shared by both bridges | Identity fields (`job_id/kind/seq/ts`) have defaults; `JobContext.emit` fills them via `dataclasses.replace` so plans never hand-craft IDs. Event payload validation in `__post_init__`: negative/over-total progress refused; finding events carry only immutable `Finding`. |
| `services/jobs.py` | `JobManager`, `JobHandle`, `JobContext`, `CancellationToken`, `JobId`, mutex-group conflict policy, `_redact_params` | One-way dependency `services → core` (no cycle). No internal event bus: delivery is synchronous, per-job serialized, subscriber exceptions contained + logged type-only. |
| `services/orchestration.py` | Plan factories: `full_device_scan_plan`, `single_app_scan_plan`, `app_listing_plan`, `export_reports_plan`, `tool_provisioning_plan` | Turn SC-3/SC-2/SC-7/SC-9 service calls into `Callable[[JobContext], Result]` plans; checkpoint labels per lifecycle table. |

### 1.2 Service seams (backward-compatible — every existing call signature unchanged)

- `ScanService.scan_full_device(request, context=None)`: optional `JobContext`; checkpoints `between_apps` (before each app's analysis) and `after_progress_emit` (after each app's progress event); emits the same `Finding` objects it returns; default path (context=None) is byte-identical to the Stage 03 service behavior.
- `ToolProvisioningService.provision_tool(tool, version, progress, context=None)`: checkpoints `during_download` (per chunk), `before_extract`, `before_install_move`; per-chunk byte progress forwarded both to the classic `progress` callback and the job context.

### 1.3 UI bridge stubs (Stage 04 AC deliverables — headless, framework-free)

| Module | Contract | Notes |
|---|---|---|
| `ui_terminal/jobs_bridge_async.py` | `AsyncJobBridge.attach/stop/pump/drain` | Worker-thread → asyncio-loop marshalling via `call_soon_threadsafe`; `Sentinel` ends the stream; no Textual import. |
| `ui_desktop/jobs_bridge_qt.py` | `QtJobBridge(dispatcher)` + `event_category()` | Injected callable `(category, event)` stands in for the future Qt signal forwarder; no PySide6 import. |
| `ui_terminal/__init__.py`, `ui_desktop/__init__.py` | package markers | Empty; no GUI code until Stages 05/09. |

### 1.4 Packaging

- `pyproject.toml`: mypy `files` now `["tests", "vscanner", "ui_terminal", "ui_desktop"]` (57 source files, zero issues); coverage `source` now `["cli", "vscanner", "ui_terminal", "ui_desktop"]`.

---

## 2. Scope discipline

- Android app (`android/**`): zero modifications.
- Legacy CLI: zero modifications — AST-locked (`test_jobs_integration.py::TestLayering::test_legacy_cli_never_imports_the_job_layer`); legacy keeps its direct service APIs.
- Layering locked by tests: `vscanner/**` may not import `ui_terminal`/`ui_desktop`; bridge stubs may not import any GUI framework (`textual`/`PySide6`/`rich`/`tkinter`); the generic engine framework-independence suite auto-parametrized over the three new engine modules (+3 tests).
- Pre-existing user items remain unstaged and untouched: modified `.gitignore` (trailing-whitespace hunk) and untracked `cli/python usb_charging_control.py`.
- Explicitly deferred per mission: No service routes itself through `JobManager` implicitly yet (UI adoption in Stages 05/09); SC-5/SC-8 confirmation-consuming plans (Stage 08); R-04…R-07 (Stage 08).

---

## 3. Lifecycle semantics (as implemented, contract-aligned)

### 3.1 State machine and terminal invariants

- `QUEUED → RUNNING → {SUCCEEDED | FAILED | CANCELLED}`; terminal states are final (first transition wins; post-terminal state changes impossible).
- Exactly one `JobTerminalEvent` per job (`terminal_emitted` flag + event drop-check in the dispatch path); a queued job cancelled before the worker claims it transitions directly `QUEUED → CANCELLED` atomically, and its plan later returns without executing.
- Cancellation is cooperative: `handle.cancel()` on a QUEUED job cancels it immediately; on a RUNNING job it only arms the token — the job reaches CANCELLED at its next `checkpoint()`. A plan with no checkpoints honestly finishes (e.g. SUCCEEDED) even after a cancel request; request ≠ acknowledgement (tested + documented contract §5).

### 3.2 Failure mapping at the plan boundary

| Plan outcome | Terminal |
|---|---|
| returns `Result` | `SUCCEEDED` (result carried on terminal event) |
| raises `JobCancelRequested` | `CANCELLED`, `at_cancellation_point` = checkpoint label |
| raises `VScannerError` | `FAILED` with the typed error; `retriable=True` only for `AdbCommandError(timeout=True)` |
| raises unexpected exception | `FAILED` with type-only summary (`exception_type` detail); the raw exception is preserved on the internal job record for diagnosis, never serialized into events |
| raises `KeyboardInterrupt`/`SystemExit` | terminal `FAILED` recorded, then the exception is re-raised (bounded test seam proves it) |
| defense-in-depth | plan returning with state still RUNNING (impossible by construction) would fail honestly via a `finally` guard |

### 3.3 Timeouts

- Per-job watchdog (`threading.Timer`, daemon): `timeout_s` from `submit`; on expiry the token is requested and the next checkpoint fails the job with `AdbCommandError(timeout=True)` semantics (`FAILED`, retriable, details `timeout_s`/`stopped_at`).
- Documented race resolution: an uncooperative plan (no checkpoints) that finishes after the deadline reports SUCCEEDED — the honest outcome, matching the "request ≠ acknowledgement" rule.
- Subprocess kill-on-timeout itself remains in the ADB adapter (contract §6, single authority); the job-level timer complements it rather than duplicating it.

### 3.4 Conflicts (contract §7 as implemented)

- Identity keys: `(None, group)` for GLOBAL scope, `(device_serial, group)` for PER_DEVICE.
- Mutex groups: `scan` (FULL_DEVICE_SCAN ↔ SINGLE_APP_SCAN), `admin_op`, `mirroring`, `forensics_write`, `tool_provisioning`.
- Scope defaults from `JobKind` (`TOOL_PROVISIONING` → GLOBAL; scans/admin/mirroring/forensics → PER_DEVICE; others coexist); explicit `scope=` overrides accepted.
- Conflict → `JobConflictError(active_job_id=…)` raised by `submit` without starting anything.

### 3.5 Redaction and log boundaries (R-12 groundwork)

- `params_summary` (documented `submit` addition): sensitive keys (`psk|password|secret|token|authorization|api_key`, case-insensitive) wholly replaced by `<redacted>`; every value passes `redact_text` and a 120-char cap; keys capped at 60 chars; log messages capped at 2000 chars with `redact_text`; progress `context` capped at 120 chars.
- Progress monotonicity enforced: a backwards progress emission raises `InputValidationError` inside the plan (loud job failure by design).
- Per-job log channel: `vscanner.jobs.<job_id[:8]>`.

### 3.6 Shutdown (contract §8)

- `shutdown(grace_s=10.0)`: rejects further submits, `cancel_all()`, waits up to grace, logs `JOB_ABANDONED` per straggler, releases the executor, returns the abandoned `JobId` tuple.

---

## 4. Discovered defect remediated (out of the Stage 04 contract, same-commit discipline)

**`AppInfo.tolerant` crashed before producing the honest-skip record.** The placeholder construction (`package_name="_legitimate_placeholder"`) failed its own `_PACKAGE_RE` validation (no dotted segment), so any per-app scan failure (`_scan_one_package`'s documented skip path) raised `ValueError` — turning a single failed app into a whole-job crash instead of a recorded skip with reason. Surfaced by the new job-level integration tests (`test_transport_timeout_mid_scan_is_honest_skips_not_success_lies`); it had zero prior coverage and no defect-row owner. Fixed by constructing via `__new__` with declared field defaults and enforcing only the non-empty invariant (+ unknown-field `TypeError` guard). Locked by 3 unit tests in `test_core_models.py::TestAppInfo` + the integration test. No Stage 03 assertion touched.

---

## 5. Test inventory (new files; suite 276 → 363)

| File | Count | Focus |
|---|---:|---|
| `tests/unit/test_core_events.py` | 22 | frozen-event immutability, payload validation, `event_category`, terminal shapes |
| `tests/unit/test_services_jobs.py` | 39 | lifecycle, cancellation (incl. re-entrant cancel from a subscriber), conflicts, redaction, retention pruning, shutdown, timeout watchdog, per-job event ordering under concurrent emitters, bounded KeyboardInterrupt seam |
| `tests/unit/test_jobs_integration.py` | 13 | scans/listing/single-app/export/provisioning through the job system; result parity vs direct service calls; deterministic mid-scan cancel; mid-download cancel discards staging; transport-timeout honest skips; **layering guards (legacy CLI untouched, engine ⊬ UI, bridges framework-free)** |
| `tests/unit/test_jobs_bridges.py` | 7 | async bridge drain/pump/stop semantics with a live loop; Qt bridge category/dispatch contract, detach, dispatcher-failure containment |
| *(updated)* `tests/unit/test_core_models.py` | +3 | `AppInfo.tolerant` fix regression locks |

Framework-independence suite auto-parametrizes over the new engine modules (+3 tests).

## 6. Verification record (exact commands, Python 3.12.10, Windows)

| # | Command | Result |
|---|---|---|
| 1 | `python -m pytest -q --no-header` | **363 passed, 4 xfailed** (≈3.5 s); xfails unchanged: R-04/R-05/R-06/R-07 (Stage 08) |
| 2 | `python -m ruff check .` | **All checks passed** |
| 3 | `python -m mypy` | **Success: no issues found in 57 source files** |
| 4 | `python -m compileall -q vscanner cli ui_terminal ui_desktop` | clean |
| 5 | coverage (`cli`+`vscanner`+`ui`) | **TOTAL 47%**; new-code anchors: `core/events.py` 100%, `services/orchestration.py` 100%, `services/jobs.py` 91%, `jobs_bridge_qt.py` 100%, `jobs_bridge_async.py` 86% |
| 6 | engine lean-budget | 5570 engine lines < 6000 guard (in-suite) |
| 7 | event-overhead benchmark (Stage 04 AC): 2000 findings end-to-end through `emit_finding` → frozen event → synchronous delivery | **≈4 µs/finding** (budget < 5 ms) |
| 8 | device/network/root freedom | suite unchanged on this promise: fake transports, generated archives, `tmp_path` only |

## 7. Documented decisions & deviations (contract clarifications)

1. **Synchronous delivery, no internal bus.** Events are delivered synchronously on the emitting thread, serialized per job (`emit_lock`); bridges own their own pumps (`call_soon_threadsafe` / future Qt queued connections). Rationale: zero internal queues to drain on shutdown, trivial ordering guarantees, and Stage 05/09 own their threading model.
2. **`seq` ordering per job.** Sequence numbers are assigned per job under the manager lock; delivery order equals seq order per job (suite-proven under concurrent emitters).
3. **`params_summary` added to `submit`** (contract named `params_summary` only on the event): required to redact parameters at the boundary before any event exists; recorded as the single source the `JobStartedEvent` consumes.
4. **Queued-cancel semantics.** `cancel()` on a QUEUED job claims CANCELLED atomically; the plan later returns without executing. `cancel_device_work`/`cancel_all` rely on this — in-flight (RUNNING) jobs behave per §3.1.
5. **Uncooperative-job honesty.** Cancellation requests against plans without checkpoints do not fabricate a CANCELLED terminal; the job finishes with its real outcome. Shutdown's grace period reports such jobs as `JOB_ABANDONED` (they are never "lost" — the strand completes and its terminal state lands).
6. **`handle_for` returns a fresh view wrapper** each call (never stored state; tests assert id/kind/state, not object identity).
7. **Retention bound.** Terminal job records are pruned oldest-first, keeping the last 256 (`retained_terminal` constructor parameter); pruning happens inside `submit` after starting the new job.
8. **Checkpoint label policy.** Scan seam: `between_apps`, `after_progress_emit`; orchestration wraps single-app/listing with `before_app_analysis`/`after_app_analysis`/`before_package_listing`; provisioning: `during_download`, `before_extract`, `before_install_move`; EXPORT exempt (fast/atomic write — contract §5).

## 8. Out of scope (explicit)

UI adoption of the bridges (Stages 05/09), SC-5/SC-8 confirmation-consuming plans and forensics/list label checkpoints (Stage 06+ ownership of label resolution, Stage 08 for those services), file-logging wiring into `%LOCALAPPDATA%` (Stage 05 shell), i18n, Android app.
