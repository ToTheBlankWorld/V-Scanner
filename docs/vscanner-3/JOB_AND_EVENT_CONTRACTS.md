# V-Scanner 3.0 — Job & Event Contracts

**Stage 01 deliverable.** Implementation lands in Stage 04 (`vscanner/services/jobs.py`, `vscanner/core/events.py`). Both UIs consume these contracts without framework bleed (ARCHITECTURE_DECISIONS A-03/A-04).

## 1. Job model

```python
JobId = str                       # uuid4 hex, unique for the process lifetime (also persisted in history)
JobState(Enum)                    # QUEUED, RUNNING, SUCCEEDED, FAILED, CANCELLED   (last 3 terminal)
JobKind(Enum)                     # DEVICE_DISCOVERY, APP_LISTING, SINGLE_APP_SCAN, FULL_DEVICE_SCAN,
                                  # DEVICE_INFO, ADMIN_OP, MONITORING_SESSION, TOOL_PROVISIONING,
                                  # MIRRORING, FORENSICS_OP, EXPORT, DEMO, OTHER
JobConflictScope(Enum)            # GLOBAL (e.g. provisioning), PER_DEVICE (scans, admin, mirroring)
JobHandle                         # id: JobId (RO); kind; device_serial: str | None;
                                  # state: RO JobState; cancel(): None (safe to call many times, idempotent)
                                  # wait(timeout) -> JobState (UIs never await from event-loop thread; see §6)
JobManager                        # submit(kind, device_serial, plan: Callable[[JobContext], Result],
                                  #         scope: JobConflictScope, timeout_s: float | None,
                                  #         confirmations,) -> JobHandle
                                  #   - see job_manager_foreground port in Stage 05; submit never runs user code inline
                                  # handle_for(job_id) -> JobHandle | None
                                  # active_for_device(serial) -> tuple[JobHandle, ...]
                                  # cancel_device_work(serial) -> None   (called on device-switch & app shutdown)
```

- Validation at `submit`: same-device conflicting op → raise `JobConflictError` **without** starting (identity check: `(device_serial, mutually_exclusive_kind_group)`), mapping in §7.
- `OperationConfirmation` objects consumed at submit-time atomicity where required (SC-5/Forensics) — stale/expired confirmation → `ConfirmationInvalid`.

## 2. Event objects (frozen dataclasses — never carry UI/framework objects)

```python
JobEvent                          # base: job_id: JobId; kind: JobKind; ts: float (monotonic)
JobStartedEvent                   # device_serial; params_summary: Mapping[str, str] (small, redacted)
JobProgressEvent                  # current: int; total: int | None; unit: str ("apps"/"files"/"bytes");
                                  # context: str (e.g. package name) — must be ≤ 120 chars, redaction applied
JobLogChunkEvent                  # level: ("debug","info","warning","error"); message: str (redacted)
JobFindingEvent                   # finding: Finding (immutable, already-evidence-resolved)
JobSnapshotStreamEvent            # used by monitoring: payload: HardwareUsageSnapshot | SensorReadingSet
JobTerminalEvent (SUCCEEDED)      # result: Any (typed model defined by JobKind), duration_ms: int
JobTerminalEvent (FAILED)         # error: VScannerError (typed), retriable: bool
JobTerminalEvent (CANCELLED)      # at_cancellation_point: str | None (where it stopped: "between_apps", …)
```
- Delivery rule: events are immutable snapshots; UI framework objects NEVER travel inside events; events never call back into services. Mutation impossible post-emit.
- Barriers: UI thread only ever sees `JobEvent`s; services only ever see `JobContext` (cancel_token, emit(event), logger proxy).

## 3. Progress reporting

- Every long op defines progress units explicitly (docs of SC contracts); services emit ≥ 1 event per second-ish granularity when applicable, otherwise heartbeat `JobLogChunkEvent(level="info")` every 10 s ("still working: <current step>").
- `total=None` allowed until enumeration completes (e.g. forensics extraction count unknown until list ready).

## 4. Error propagation and cleanup

- Service exceptions are converted at `plan` boundary into `JobTerminalEvent(FAILED)`; the exception object is preserved and also logged (with redaction) into the job's log lane.
- Cleanup contract: every `plan` uses try/finally: temp files deleted (archives, pulled temp paths); partially-updated case manifests get explicit `"status": "partial"`; partial scan states leave `ScanRun(state=FAILED|CANCELLED, used_partial=True)` so UIs can display "results before cancellation retained".
- No bare exceptions leak: wrapping forbidden only if it would hide `KeyboardInterrupt`-class signals; SystemExit/KeyboardInterrupt re-raised.

## 5. Cancellation semantics (cooperative)

- `JobContext.cancel_token` = `CancellationToken` with `request()` (sets flag + wakes waits), `token.is_cancelled` boolean property, `checkpoint(label: str)` raising `JobCancelRequested` if set.
- Cancellation points table (where a service MUST `checkpoint()`):
  | Service loop | Points |
  |---|---|
  | FULL_DEVICE_SCAN | between apps; between stages within an app (dumpsys-parse → deep-string-extract); progress emit boundary |
  | APP_LISTING | between per-package label lookups |
  | DEVICE_INFO | between property collection groups (props → RAM/df → net/fingerprint) |
  | TOOL_PROVISIONING | between download chunks; before extract; before replace-move of tools dir |
  | FORENSICS | between files; between case-suboperations |
  | MONITORING | every poll interval boundary |
  | EXPORT | none needed (fast, atomic write) — exempt |
  | ADMIN_OP | not cancellable after adb call submitted (single fast command); pre-call only |
- First `checkpoint()` after cancel → `JobTerminalEvent(CANCELLED)`.

## 6. Timeouts & subprocess termination

| Work | Default timeout | On timeout | On cancel |
|---|---|---|---|
| ADB one-shot (`adb <cmd>`) | 30 s (per-command override, legacy values preserved; `logcat -d` retained at 10 s, deep-scan grep 60 s) | kill child process (`terminate()`→ grace 3 s → `kill()`), raise `AdbCommandError(timeout=True)` | same as timeout, but result marked cancelled |
| `adb devices` | 10 s | kill, error | n/a |
| tool download | none (bounded by progress; transport read timeout 30 s of inactivity) | socket closed; archive discarded | socket closed; archive discarded |
| extraction jobs | no global timeout (files vary) | — | step-wise abort, temp buffers dropped |
| scrcpy | none (interactive window); max-fps/log-file managed via options | — | `stop()` → terminate grace 3 s → kill |

- Timeout enforcement lives in the `AdbClientProtocol` adapter (infrastructure), not per-service (single place to change).

## 7. Duplicate-operation prevention on the same device

Mutually exclusive groups (`JobConflictScope=PER_DEVICE`):
1. `FULL_DEVICE_SCAN` ↔ `SINGLE_APP_SCAN` (same device) — one scan pipeline at a time.
2. `ADMIN_OP` (all three ops serialized per device) — second admin op queues by failing fast with `JobConflictError` naming the active job id (UI shows queue/choice).
3. `MIRRORING` — one scrcpy session per device (a second raise instead of double-start like legacy).
4. `FORENSICS_OP` writes — one mutating forensics op at a time per case dir.
- `TOOL_PROVISIONING` is `GLOBAL` (one provisioning at any time); `MONITORING_SESSION` coexists with scans (read-only).
- `active_for_device()` lets UIs show "busy" states instead of dead-ends.

## 8. UI shutdown while work is running

- Both UIs subscribe to close events → `JobManager.cancel_device_work(serial)` for each running job + global cancel of `TOOL_PROVISIONING` unless user checked "keep downloading".
- Grace period: 10 s for all jobs to reach terminal state; after that the manager records `JOB_ABANDONED` warnings in the log and the app exits (no zombie thread blocking more than the grace; leak-safe due to try/finally in plans).
- Legacy-CLI freeze rule: not applicable (legacy blocks directly) — legacy is unchanged in this respect until Stage 16.

## 9. Logging & redaction requirements

- Log channel per job: `vscanner.jobs.<job_id[:8]>` + service loggers; all messages rendered through redaction filter (R-12): WiFi psk, IMEI/IMSI, phone numbers, OTP-ish bodies masked by default.
- File logging: rotating file in `%LOCALAPPDATA%\vscanner\logs\` (dev-repo mode: `./logs/`), max size/retention per config; console logging is a UI concern.
- Reports never automatically embed raw sensor dumps or WiFi secrets — content-wise their payloads are findings/summaries (evidence excerpts max 2 KB, already redacted).

## 10. Frontend consumption bridges

- **Textual (async):** app installs an event pump (Single `asyncio` task listening on the manager's `event_queue`), dispatches to widget-level message handlers; widgets never call services directly — parent screens hold `JobHandle`.
- **Qt:** a small adapter `QtJobBridge(QObject)` owns the forwarder; on the manager's queue it emits Qt signal per typed event category (`started/progress/log/finding/terminal`), marshalled with `QMetaObject.invokeMethod(..., Qt.QueuedConnection)` so handlers run on the GUI thread.
- Both bridges convert identical event objects — no event type is UI-only.
- Framework leakage guard: import-lint (Stage 02 configuration) asserting `services/` and `core/` never import `textual`, `PySide6`/`Qt`, `rich` (and reporting constants) — exceptions None.

## 11. What cannot be cancelled safely (documented)

- In-flight ADB child process kill is safe (stateless commands; stateful effects of admin ops complete atomically with the command; no partial uninstall semantics observed in ADB).
- Tool replace-move inside tools dir during provisioning is transactional: only after full extraction into stage dir + validation, then atomic move; cancelling never leaves half-replaced binaries.
- Forensics files already fully written to disk remain (manifest marks partial run status); nothing silently deleted.
- scrcpy is a user-facing process: stopping is graceful-stop-first; forced kill only after grace.

## 12. Stage 04 implementation notes (authoritative clarifications as built)

These paragraphs pin the exact semantics the Stage 04 implementation chose where the contract left latitude; they are binding for the UI stages.

1. **Delivery is synchronous and bus-free.** Events are frozen snapshots delivered synchronously on the emitting thread, serialized per job (`emit_lock`); there is NO internal event queue. UI bridges own their pumps: Textual marshals via `call_soon_threadsafe` (single loop task); Qt will marshal via queued connections around an injected dispatcher (stub: `ui_desktop/jobs_bridge_qt.py`, dispatcher callable `(category, event)`; categories from `event_category()`: started/progress/log/finding/snapshot/terminal).
2. **Ordering.** `seq` numbers are assigned per job under the manager lock; per-job delivery order always equals `seq` order (suite-proven under concurrent emitters). `ts` is `time.monotonic()`.
3. **Plan-boundary failure mapping.** `JobCancelRequested` → CANCELLED (`at_cancellation_point` = checkpoint label); `VScannerError` → FAILED (retriable only for `AdbCommandError(timeout=True)`); unexpected exceptions → FAILED with a type-only summary (raw exception kept on the internal record, never serialized into events); `KeyboardInterrupt`/`SystemExit` → FAILED recorded, then re-raised.
4. **`JobStartedEvent.params_summary` sourcing.** `submit` gained a documented `params_summary` mapping parameter (contract-level addition); sensitive keys (`psk/password/secret/token/authorization/api_key`, case-insensitive) become `<redacted>`, all values pass `redact_text` + 120-char cap, keys capped 60, log messages capped 2000, progress context 120.
5. **Progress rules.** Progress must be monotonic per job (backwards → `InputValidationError` → job FAILED — loud, by design); `total=None` allowed; negative or exceeding-total emissions refused by event validation.
6. **Terminal exactly-once.** First (state) transition wins; post-terminal events are dropped and logged (`vscanner.jobs.<id[:8]>`); the `JobTerminalEvent` itself bypasses the post-terminal drop check — exactly-once is enforced by the terminal-claim logic, and subscriber exceptions never break terminal delivery.
7. **Caveat on request-vs-acknowledgement.** `cancel()` on QUEUED cancels atomically; on RUNNING it only arms the token. Plans may keep running to honest completion (see §11) — drivers that need bounded stop must schedule checkpoints. Timeout watchdog firing ⇒ next checkpoint fails the job; an uncooperative plan finishing after the deadline reports SUCCEEDED honestly.
8. **Retention.** Terminal records kept = last 256 (`JobManager(retained_terminal=256)`); pruning runs inside `submit`.
9. **Checkpoint labels implemented in Stage 04 seams.** Scan: `between_apps`, `after_progress_emit`; single-app wrapper: `before_app_analysis` / `after_app_analysis`; listing: `before_package_listing`; provisioning: `during_download`, `before_extract`, `before_install_move`; EXPORT exempt (fast/atomic). App-label-resolution checkpoints land with Stage 06 label work; per-stage in-app points stay queued for Stage 08 (deep-scan) — the app-analysis stage is indivisible until then (documented).
10. **`handle_for` returns a fresh read-only view object** per call (comparisons on id/kind/state, not identity).
