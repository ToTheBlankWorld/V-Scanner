# V-Scanner 3.0 — Measurable Acceptance Criteria (Stages 02–16)

**Stage 01 deliverable.** Defines measurable, verifiable completion rules per stage, consistent with `ROADMAP.md` and the contracts (D, E). Each stage records its evidence in `PROGRESS.md` at closure — a stage cannot be marked complete while any criterion is unverified. Common pre-commit rules from the mission statement apply in every stage (HTTPS-only Git, no force-push, no Android changes, no unrelated user changes staged).

Verification category codes: **[T]** automated test suite, **[M]** manual verification with recorded evidence (screenshot/log), **[R]** repo/state inspection, **[D]** documented decision recorded in the stage log.

---

## Stage 02 — Regression tests & project foundation

**Scope/prereq:** Stage 01 accepted; spec docs available; no production behavior changes.
**Required outputs:** pytest + coverage setup; `vscanner/` package skeleton (models-only where drafted); Ruff + mypy configuration (strict on `core/`, exempt list for legacy `cli/**`); golden baseline captures: `permissions.analyze_permissions` fixtures, `get_sdk_risk` fixtures, 3 report formats from a fixed sample bundle, legacy Click `demo` report outputs; public CI workflow (if approved: GitHub Actions on `ubuntu-latest` + `windows-latest`, Python 3.11–3.13 matrix) [T]; repo hygiene R-09 + R-08 untracking portion (`git rm --cached android/build/... ` and `cli/adb_config.json`, both in a normal commit) [R].
**Test/validation evidence:** `pytest` exit 0 with ≥ 15 tests covering permissions scoring thresholds, SDK risk branches, report golden files byte-stable across two runs, config (legacy) round-trip; Ruff clean on new code; mypy clean on `core/`.
**Compatibility:** `python cli/main.py` and `python cli/scanner.py list-apps/analyze/demo` still launch ([M] launch log).
**Security:** lint gate blocks `shell=True` and bare `except:` in `vscanner/` [T]; no secrets in committed fixtures [R].
**Definition of completion:** all above evidence recorded in PROGRESS; suite runs green locally and in CI.
**Explicit exclusions:** no service-layer implementation, no UI, no dependency upgrades beyond adding dev-only tools, no Android modifications, no fixing of legacy defects (except the sanctioned R-09/R-08 hygiene untracking).

## Stage 03 — Shared engine & service layer

**Scope/prereq:** Stage 02 suite green and CI-enabled.
**Required outputs:** `vscanner/core/{models,errors,config}` per DATA_MODELS; `services/{adb,scanning,reports,tools,config}` implementing contracts SC-1,2,3,4,7,9 (monitoring, forensics, admin live later-stage; SC-5,8 allowed early with confirmation tokens); legacy `cli/main.py`/`cli/scanner.py` re-wired through services *without user-visible change* (frozen shims); `pyproject.toml` with thin `requirements.txt` shim; config service first-run import of legacy `cli/adb_config.json` (R-08 migration portion) [R].
**Test/validation evidence:** new unit tests for services with faked ADB client (record/replay transports): device listing, package listing, single-app analysis, full-device scan flow, report export equality vs Stage 02 golden files (byte-identical filenames and JSON keys) [T]; parity property: permission-derived scores equal legacy for all golden fixtures [T]; provisioning fake-HTTP tests (R-11 partial: checksum verify + zip-slip rejection) [T].
**Compatibility:** every legacy CLI surface still launches and produces identical stdout formats for golden fixtures ([T] + [M] logs); recorded outcome notes for SC-11 doctor reporting.
**Security:** R-01/R-02/R-15 executed in shared modules as they're ported (per stage log [D]); binaries never shipped in repo [R]; private repo data untouched.
**Definition of completion:** service layer verified by running the legacy shims against it; all tests green; no startup download or pip side-effects in the new engine (doctor is report-only per R-14).
**Explicit exclusions:** TUI/desktop screens; forensics/monitoring/admin service full ports (unless early-wired as above); any user-visible legacy change; Android.

## Stage 04 — Job lifecycle & event system

**Scope/prereq:** Stage 03 service layer tests-verified.
**Required outputs:** `services/jobs.py` + `core/events.py` per JOB_AND_EVENT_CONTRACTS; Scanning/Listing/Provisioning/Export re-routed through jobs; Qt-bridge prototype module `ui_desktop/jobs_bridge_qt.py` stub (non-UI-binding testable) and asyncio bridge `ui_terminal/jobs_bridge_async.py`; import-leakage lint asserting no `textual`/`PySide6`/`rich` in `services|core` [T].
**Test/validation evidence:** cancellation tests kill in-flight adb subprocess (fake) mid-scan and yield consistent events ([T]); timeout enforcement tests [T]; conflict-prevention tests (same-device admin op and second scan rejected with `JobConflictError`) [T]; event-order invariants (no post-terminal events) [T]; redaction filtered into the event stream (R-12 log-boundary groundwork) [T].
**Compatibility:** legacy CLI untouched behavior ([T] re-run Stage 03 suite), job layer optional for legacy shims.
**Security:** event payloads contain no unredacted device identifiers (per model redaction rules) [T].
**Definition of completion:** benchmark overhead measurement documented (< 5 ms per finding event in suite); bridges smoke-tested without GUI frameworks installed.
**Explicit exclusions:** front-end runnables; UI event visuals.

## Stage 05 — TUI foundation

**Scope/prereq:** Stage 04 job contracts stable.
**Required outputs:** Textual app shell (doctor screen, device status, command palette, settings screen with config service + legacy import; theme; keybindings doc page); repo-dir dev mode via `VSCANNER_LOCAL`.
**Test/validation evidence:** headless Textual render tests [T]; settings round-trip [T]; doctor output equivalent to SC-11 contract; no-device launch completes in ≤ 2 s on a clean profile [M]; startup does no network access unless user initiates provisioning [T].
**Compatibility:** legacy CLI unchanged ([T] re-run).
**Security:** no identifiers printed to logs at info level (redaction assertions) [T].
**Definition of completion:** shell walks through: launch → settings read/write → exit; PROGRESS evidence recorded.
**Exclusions:** any scanning/forensics screens; reports; destructive UI actions.

## Stage 06 — TUI device workspace

**Required outputs:** device discovery/selection/switch UI; device info panels incl. full profile; app inventory browser (search, paginate, label-source badge).
**Evidence:** [T] UI-integration with faked ADB: detect 3 devices, switch, list ≥ 150 apps w/ pagination; [M] real-device manual run recorded if hardware available (optional but recorded when absent); cancellations in listing ([T]).
**Compatibility:** matrix rows C-F03/04/06/19 reach "implemented" only when [T]+[M] evidence attached; C-F19 REMEDIATION (phone number row honest) verified.
**Security:** R-12 boundary in device panels verified.
**Exclusions:** scanning screens; admin screens; analytics overlays.

## Stage 07 — TUI scanning & findings

**Required outputs:** single-app + full-device scan screens w/ live progress, streaming findings, report export entry points; scan history list (T-08 JSON store).
**Evidence:** [T] deterministic demo scan produces typed Findings identical to Stage 03 fixtures through job pipeline; cancel mid-scan retains partial bundle cursor; [T] export produces three legacy-format reports on golden data; [M] deep-scan with toybox-less replay produces UNVERIFIED_CONDITION note (R-06 groundwork behavior).
**Compatibility:** output naming/directory default matches legacy unless user configured otherwise.
**Security:** findings evidence excerpts redacted by default [T]; history stores no secret material [T].
**Exclusions:** admin/forensics/sensors screens (Stage 08).

## Stage 08 — TUI parity & hardening

**Required outputs:** admin ops (confirmation flow), sensor monitoring (honest rows), screen-mirroring launcher (SC-8), demo mode screen, forensics cockpit (byte-safe ops, redaction-double-confirm for WiFi), full legacy menu parity or per-item exclusion approval, doctor finalization.
**Evidence:** full C-Fxx checklist table appended to PROGRESS with per-row status backed by test or manual evidence ([T]/[M] per row); R-03–R-07, R-12 artifacts completed and tested; keyboard-only navigation of every screen [M].
**Compatibility:** legacy CLI feature parity confirmed with parity matrix re-audit ([R] + test).
**Security:** destructive flows all gated through OperationConfirmation service-side even when reached via legacy shim ([T]).
**Exclusions:** desktop features; Android.

## Stage 09 - Desktop foundation

**Required outputs:** Qt app shell, design tokens, main window, settings dialog, Qt job bridge wired, packaging groundwork (icons/metadata).
**Evidence:** [T] Qt bridge event integration (fires on GUI thread); high-DPI screenshots; [M] launch on Windows 10 + 11 profiles; settings persistence through ConfigService [T].
**Compatibility:** parity with Stage 08 shell features that make sense on desktop; legacy CLI untouched.
**Exclusions:** scanner views.

**Stage 09 execution clarification (2026-10-18):** "packaging groundwork" is delivered as (a) package/entry-point metadata (`vscanner-desktop`, `[desktop]` extra, setuptools packages) and (b) a themed programmatic brand mark in the shell; the binary app icon asset is a Stage 14 packaging deliverable (no generated binaries are committed from source stages). "High-DPI correct" relies on Qt 6 default scaling; DPI/visual verification on real Windows 10+11 displays plus screen-reader conformance remain [M] items not claimable from the offscreen test harness (recorded in STAGE_09_IMPLEMENTATION_REPORT.md §4).

## Stage 10 - Desktop device management
**Evidence:** same checklist as Stage 06 executed in Qt harness [T] (+[M] real device where available); destructive-op confirmations [T] (R-13 repeats).
**Required outputs:** device discovery/selection/switch UI; device info panels incl. full profile; app inventory browser (search, paginate, label-source badge).
**Clarification (2026-10-18, recorded):** the destructive-op confirmation line (R-13 repeats) belongs to the desktop **admin operations**; admin ops were deferred to the Stage 12 parity pass (ROADMAP deviation note in `STAGE_10_IMPLEMENTATION_REPORT.md` §1.7) — no destructive device command exists in the desktop layer, so there is nothing to gate yet. Stage 10 [T] evidence delivered: discovery/selection (single-device auto-select only, stale-safe invalidation), root tri-state details, inventory browser (search/system filter/pagination/provenance/cancel), cancellable APP_LISTING on the Stage 04 manager, settings ADB validation — all offscreen Qt harness, no device available (recorded when absent per Stage 06 wording).
## Stage 11 — Desktop scanner & findings
**Required outputs:** desktop scan workspace driving the SC-2 pipeline (target + preflight + scope toggles + validated single-app input; honest streamed progress; cancellation with request ≠ acknowledgement; stale-target revalidation); findings explorer (text search, severity/category/provenance filters, deterministic sorts, 100-row pagination, per-finding detail with redacted evidence); reports screen exporting the last completed full-device bundle through the real SC-9 service (native dialogs, explicit overwrite confirm, honest refusal/running/success/failure states); T-08 scan-history reader (counters-only local JSON, honest empty/failed states); Stage 07 criteria re-verified offscreen [T].
**Evidence:** `STAGE_11_IMPLEMENTATION_REPORT.md`; `test_stage11_desktop.py` — 58 offscreen tests over the REAL engine services (`ScanService` via dumpsys-capable fake transport, stage 04 `JobManager`, real `ReportService` byte-schema writes, real T-08 store): scan lifecycle (stale/queued-cancel/late-event/foreign-event/zero-findings/duplicate honesty), findings models at 220 rows incl. malformed-row safety and redaction, export success-only-after-write + legacy JSON parity + overwrite gates, history round-trip; history round-trip schema limited to local counters (schema_version'd, secrets-free). Full suite 765 green; mypy 116 files; [M] real-device items remain recorded-when-absent.
**Deviations (recorded):** single-app scans not exportable (engine schema truth, honest UI copy); deep-scan URL path [UNVERIFIED] (engine `UNVERIFIED_CONDITION` honesty surfaced); fakes-not-hardware.
## Stage 12 — Desktop remaining parity
**Required outputs:** desktop pages driving the REAL engine services for the TUI Stage 08 surface: live monitoring (typed snapshot events, explicit start/stop, honest not-observed/unknown/unavailable semantics — never "not in use"), forensics cockpit (case-first create/open/extract/report with byte-exact records, path-traversal defenses, WiFi redacted by default + exact-phrase-gated cleartext through the SERVICE confirmation gate), screen-mirroring lifecycle (tool-preflight refusal, duplicate-launch prevention, argv-only spawn, NO screen-off offer), demo mode (deterministic fixture, zero device contact, no scan-history/selection impact), and the deferred Stage 10 administration operations (uninstall/launch/force-stop) with the R-13 double gate: operation-specific exact-package-retype dialogs, freshly revalidated explicit targets, cancel dispatches nothing, service-side `validate_confirmation` never bypassed. Navigation/status parity: the last placeholder registry rows become live with honest descriptions.
**Evidence:** `STAGE_12_IMPLEMENTATION_REPORT.md`; `test_stage12_desktop.py` — 62 offscreen tests over the REAL engine services (Stage 08 fake transport extended to the dumpsys/logcat/ps/su-wpa/exec-out byte surface → real `MonitoringService`/`ForensicsService`/`AdministrationService`/`DemoService`/Stage 04 `JobManager`/queued bridge; `ScreenMirrorService` faked at the registry seam). Real-pipeline GUI-thread delivery asserted; demo zero-contact/zero-history asserted by call counting; byte-exact extraction verified on disk; report.json legacy fields verified; duplicate-launch and control-enablement regressions (§3 of the report) locked. Full suite 827 green ×2 fresh-process + ×2 instrumented; mypy 121 files; [M] real-device items remain recorded-when-absent.
**Deviations (recorded):** real scrcpy window display behavior [UNVERIFIED]; the backend caches one `ScreenMirrorService` per serial per session (per-serial duplicates guard is desktop-visible only; recorded layering difference vs the TUI); monitoring is host-side polling, never continuous and never "not in use" for not-observed; fakes-not-hardware.
**Engine fix delivered with this stage:** the forensics service's per-file progress emission violated the typed progress contract (`total must be > 0 or None`) — surfaced by the desktop's real-pipeline tests and fixed to honest per-entry progress; Stage 07 engine tests re-run green.

## Stage 13 — Motion, polish, accessibility & UX
**Required outputs:** animation restraint policy documented + honored (both UIs); focus ordering, contrast checks (WCAG-AA on text), reduced-motion setting, empty/loading/error states, unified error copy from error taxonomy, i18n-ready strings (per ROADMAP Stage 13).
**Evidence:** [M] manual checklist screenshots archived under `docs/vscanner-3/qa/`; [T] contrast assertions on token pair matrix where automatable; reduced-motion honored in UI test mode.
**Exclusions:** functional changes.

## Stage 14 — Windows executable & installer
**Required outputs:** Nuitka build (mode decided T-05), version metadata, optional bundled-tools variant decision [D], installer (Inno Setup or MSI [D]), uninstaller, code signing decision [D].
**Evidence:** [R] reproducible build from clean clone on CI Windows runner; [M] installer on clean Windows VM: install → launch → scan demo → uninstall, no leftovers; startup time ≤ 4 s cold, size recorded; `doctor` self-check runs inside packaged binary; no pip/Python dependency needed.
**Security:** binaries scanned for unexpected network endpoints; no secrets embedded; R-10 closure (setup.py gone or unshipped).
**Exclusions:** macOS/Linux artifacts; feature additions.

## Stage 15 — Security, compatibility & release QA
**Required outputs:** security review report `(docs/vscanner-3/qa/security_review.md)`; regression matrix across 4 surfaces (legacy CLI, Click CLI, TUI, desktop) on identical fixtures; performance baselines (scan of golden bundle ≤ N ms per app; memory ceilings); docs consistency pass; secrets-scan over logs/reports.
**Evidence:** all logged; unsolved security findings → block release with owner assignment.
**Exclusions:** new features.

## Stage 16 — Final release & documentation
**Required outputs:** tag + GitHub Release with installer + notes; user docs (TUI + Desktop quickstarts) matching real behavior (reviewed by non-implementer); CHANGELOG; stale docs archived; PROGRESS all COMPLETE; repo hygiene final (no tracked generated artifacts, no `cli/adb_config.json` tracked).
**Evidence:** release URL live; docs cross-check sign-off recorded; all 16 stages marked complete in PROGRESS.
**Exclusions:** scope expansion; Android.

---

## Consistency verification (§5 checklist fulfillment)

1. Every proposed target module has a single responsibility → see MODULE_MIGRATION_MAP §"Target location" column. [checked Stage 01]
2. Service contracts ↔ CLI capabilities ↔ parity rows: cross table in SERVICE_CONTRACTS end. [checked Stage 01]
3. All known defects assigned: remediation ownership matrix above. [checked Stage 01]
4. Every CLI feature covered by a contract or explicitly classified drop/deprecated (C-F29, C-F30). [checked Stage 01]
5. Android-only features never conflated (A-§ Guardian distinct; A-F01 in parity). [checked Stage 01]
6. Stage 02 test-first; Stage 03 explicit compat checks. [above]
7. TUI = 05–08 and desktop = 09–13 coverage matched. [above]
8. Packaging and release QA = Stages 14–16. [above]
9. No production code or dependency files changed in Stage 01 — enforced by the final Git diff inspection before commit. [to verify at commit time]
