# V-Scanner 3.0 — 17-Stage Roadmap

**Baseline:** Stage 00 audit committed to `main`. Every stage below lists scope, dependencies, exclusions, and measurable acceptance criteria. Stage order is mandatory; no stage may start until its dependencies are verified complete (see `PROGRESS.md`).

Ground rules for all stages:
- Branch `main`, HTTPS-only remote, no force-push, no history rewrite.
- Android code (android/**) is never modified in any stage.
- Scoped commits; unrelated user changes never staged; secrets/binaries never committed.
- Every stage ends with: updated `PROGRESS.md`, stage-specific deliverables committed, CI-required validation results recorded.

---

## Stage 00 — Repository audit and feature inventory *(COMPLETE)*
**Scope:** Audit Python CLI modules, Android app, project health; produce audit docs, feature parity matrix, target architecture proposal, roadmap, progress tracker; push a docs-only checkpoint.
**Dependencies:** none.
**Exclusions:** no code changes, no Android changes, no test fixes.
**Acceptance criteria:** `STAGE_00_REPOSITORY_AUDIT.md`, `FEATURE_PARITY_MATRIX.md`, `TARGET_ARCHITECTURE.md`, `ROADMAP.md`, `PROGRESS.md` present on `origin/main`; working tree clean of Stage 00 residue; all 12 CLI menu options + 8 forensics entries + 7 hidden Click commands inventoried; safe checks executed and recorded (py_compile, pure-layer functional check); commit hash published.

## Stage 01 — Architecture and migration specification
**Scope:** Convert the Stage 00 proposal into a binding spec: package layout, typed model schemas, job/event API signatures, config schema + storage paths, error taxonomy, legacy-CLI compatibility contract, byte-safe ADB command modes, dead-code disposition decisions (device_unlock, broken extractors, duplicates), tool-provisioning policy (versions/checksums), Nuitka/onefile vs standalone decision, installer technology choice.
**Dependencies:** Stage 00 accepted.
**Exclusions:** no implementation.
**Acceptance criteria:** `docs/vscanner-3/ARCHITECTURE_SPEC.md` covering every named service and model; all Stage 00 "decision required" items resolved with rationale; spec reviewed against the actual import graph (no unresolved cycles); PROGRESS updated. *(Stage 01 execution note: the binding spec is delivered as the seven documents named in the Stage 01 mission — ARCHITECTURE_DECISIONS, MODULE_MIGRATION_MAP, DATA_MODELS, SERVICE_CONTRACTS, JOB_AND_EVENT_CONTRACTS, SECURITY_AND_REMEDIATION_PLAN, ACCEPTANCE_CRITERIA — which together supersede the single `ARCHITECTURE_SPEC.md` name here, mirroring how Stage 00's five-deliverable set superseded the "four files" wording.)*

## Stage 02 — Regression tests and project foundation
**Scope:** Create the pytest foundation + faked ADB client; capture/record golden data for the pure analysis layer; add repository hygiene fixes that were **sanctioned** (e.g., stop tracking `android/build/reports/...`, machine-local `cli/adb_config.json` handled per Stage 01 decision); add CI workflow if approved.
**Dependencies:** Stage 01 spec accepted.
**Exclusions:** no behavior changes in legacy CLI; no new features.
**Acceptance criteria:** `pytest` suite green covering `permissions.analyze_permissions`, `get_sdk_risk`, report generation (3 formats, golden files), config load/save; zero test-related commits to `android/**`; baseline test run recorded in PROGRESS.

## Stage 03 — Shared engine and service layer
**Scope:** Implement `vscanner.core` models + services: adb client (byte-safe), devices, device_info, scanning (permission/sdk/apk), reports (ported templates), config (versioned), tools provisioning (ported, validated fallbacks).
**Dependencies:** Stage 02 suite green.
**Exclusions:** no UI layer yet; legacy CLI still the operating interface.
**Acceptance criteria:** legacy `main.py`/`scanner.py` call paths reproduced through services for at least: app listing, single-app analysis, full scan, all 3 report formats; parity evidence recorded (identical scores/fixtures vs legacy); new unit tests for services green.

## Stage 04 - Job lifecycle and event system *(COMPLETE)*
**Scope:** Implement the job system (`Job`, `JobHandle`, typed events, cooperative cancellation, timeouts) and re-route scanning/reporting/provisioning/monitoring jobs through it.
**Dependencies:** Stage 03 services.
**Exclusions:** no UI.
**Acceptance criteria:** unit tests prove cancellation of a long scan a) stops between apps b) terminates ADB subprocesses c) leaves partial state consistent; event ordering test; benchmark: event overhead < 5 ms/finding in the suite.

## Stage 05 - TUI foundation and visual design *(COMPLETE)*
**Scope:** Textual app shell: startup doctor (provisioning + dependency status as commands, no auto-pip), device status bar, theme, keybindings, navigation, config storage in user directory (with legacy import).
**Dependencies:** Stage 04 job system.
**Exclusions:** no device mutating operations yet; legacy CLI remains available.
**Acceptance criteria:** TUI launches headless-tested (textual run/test harness) to a device dashboard with 0 device required; keymap documented; config round-trip test; no regression in legacy CLI.

## Stage 06 — TUI device workspace *(COMPLETE)*
**Scope:** Device discovery/selection/switching, device info panels (incl. full info, network, build), app inventory browser with search/pagination and improved honest app-name handling.
**Dependencies:** Stage 05 shell + Stage 03 device services.
**Exclusions:** scanning, forensics, mirroring (staged later).
**Acceptance criteria:** with a real device OR a replayed ADB fake: detect, select, switch, display info; app list renders ≥ 100 packages with search + page navigation; every action cancellable.

## Stage 07 — TUI scanning and findings *(COMPLETE)*
**Scope:** Single-app analysis, full-device scan with live progress, findings browsing (typed findings), SDK/permission drill-down, insecure URL surfacing, report export (HTML/JSON/text) from TUI.
**Dependencies:** Stage 06.
**Exclusions:** admin ops, forensics, sensors, mirroring.
**Acceptance criteria:** scan of a faked dataset produces typed findings matching Stage 03 golden data; export files byte-identical to legacy format for same input (regression) or documented improvements; cancel mid-scan works.
**Delivered (2026-10-18):** scan screen (f) with own discovery/preselect + preflight target revalidation, scope toggles (t system / u deep), single-app input validation (n), honest streamed progress, cancellation (c) with PARTIAL-stream honesty, findings explorer (v/g/o filters+sorts, text filter, [ / ] pagination, per-finding provenance detail); reports screen (h) exporting the last completed bundle through the SC-9 plan (byte-identity regression-tested) + T-08 scan-history table; vscanner/services/history.py counters-only capped JSON store; Stage 04 sec5 wait-vs-delivery race closed test-side (deterministic ordering tests; stress-reproduced 9/4000, no production change). Details in STAGE_07_IMPLEMENTATION_REPORT.md.

## Stage 08 — TUI feature parity and hardening *(COMPLETE)*
**Scope:** Remaining features: admin ops (uninstall/open/force-stop with confirmations), sensor monitoring (honest data), full device info, screen mirroring launcher, forensics cockpit (byte-safe extractors, case store, redaction default for WiFi PSK), demo/sample mode, error/edge-case hardening.
**Dependencies:** Stage 07.
**Exclusions:** no new scanner heuristics beyond legacy; Android app untouched.
**Acceptance criteria:** parity checklist against `FEATURE_PARITY_MATRIX.md` — every C-Fxx row implemented or explicitly excluded with recorded rationale; no feature regression vs legacy CLI contract; keyboard-only operability test; TUI has no blocking I/O on the event loop (latency check).
**Delivered (2026-10-18):** live monitoring (m), forensics cockpit (o), mirroring (i), demo data (b), full device info (workspace f), admin ops (workspace u/l/k with re-type confirmation modal), all-engine-reachable screens registry (no placeholders); R-03..R-07 + R-12/R-13 remediations landed (detection-only sensor honesty, deep-scan URL/credential extraction with redacted presentation, verified root tri-state, byte-safe data extraction, WiFi redaction default, service-side confirmation gate); legacy `scanner.py`/`digital_forensics.py` became thin adapters over the engine; engine test volume 66 new cases; TUI smoke + concurrency gates recorded. Details in STAGE_08_IMPLEMENTATION_REPORT.md.

## Stage 09 - Desktop foundation and design system (PySide6) *(COMPLETE)*
**Scope:** Qt main window, design tokens shared with TUI vocab, layouts, navigation, settings dialog, notifications/status handling, packaging groundwork (app icon, metadata).
**Dependencies:** Stage 08 TUI parity complete.
**Exclusions:** feature logic (reuses services).
**Acceptance criteria:** desktop launches on Windows 10/11 from the dev environment; renders dashboard skeleton; runs job system correctly in Qt event loop (integration test); High-DPI correct.
**Delivered (2026-10-18, commit `058de46` + docs commit):** `ui_desktop/` shell (Fusion + generated theme QSS, single token source), 11-section registry (3 live + 7 honest placeholders + settings dialog), cached `QStackedWidget` navigation, `SettingsDialog` through ConfigService [T], Qt job bridge wired with GUI-thread delivery proven [T]; PySide6 as optional `[desktop]` extra; 640-test suite ×2 green, mypy 109 files clean; full evidence and [M] limitations in `STAGE_09_IMPLEMENTATION_REPORT.md`.

## Stage 10 - Desktop dashboard and device management
**Scope:** Device discovery/switching UI, device info panes, app inventory browser, admin operations with confirmation dialogs.
**Dependencies:** Stage 09.
**Exclusions:** scanning/forensics/mirroring UIs.
**Acceptance criteria:** same acceptance set as Stage 06, executed in Qt harness + manual with device where available.
**Delivered (2026-10-18):** truthful dashboard (config + doctor + explicit user-initiated ADB probe, "not checked" until probed), device discovery/selection with stale-safe and single-device-only auto-selection, honest root tri-state details, installed-app inventory (search/system filter/100-row pagination/provenance "inferred (derived)") on cancellable Stage 04 APP_LISTING jobs, worker-seam (`DesktopBackend`/`WorkerCoordinator`) with queued GUI-thread delivery, settings ADB "Validate path now". **Scope deviation (recorded): admin operations with confirmation dialogs deferred to the Stage 12 parity pass — no destructive device command exists in the desktop layer.** 707-test suite ×2 green (67 new offscreen tests), mypy 113 files clean; full evidence, engine truths (APP_LISTING is not mutex-grouped — overlap prevention stays at the workspace surface; `JobTerminalEvent` carries no device_serial) and [M] limitations in `STAGE_10_IMPLEMENTATION_REPORT.md`.

## Stage 11 — Desktop scanner and findings
**Scope:** Scan configuration, live job progress, findings tables/detail views, report export, scan history (local, optional).
**Dependencies:** Stage 10.
**Exclusions:** sensor/forensics/mirror.
**Acceptance criteria:** Stage 07 criteria re-verified in desktop; history round-trip test (`history/` JSON schema limited to local data).
**Delivered (2026-10-19):** scan workspace (device target/preflight + engine-supported scan types `FULL_DEVICE`/`SINGLE_APP` only, honest streamed progress, request≠acknowledgement cancellation incl. queued-cancel, stale-target revalidation, single-app "not exportable" honesty) + findings explorer (search/severity/category/provenance filters, deterministic sorts, 100-row pagination, redaction-honest detail; malformed rows cannot crash the view) + reports screen (real SC-9 export of the last completed full-device bundle with native dialogs and explicit overwrite confirm, honest refused/running/ok/failed states) + real T-08 history reader. **Scope deviations (recorded): single-app scans are not exportable (legacy export schema requires a full-device `ScanResultBundle` — honest UI copy, nothing fabricated); deep-scan URL/secret host-side path remains [UNVERIFIED] (no byte-safe transport surface in the fake; engine's `UNVERIFIED_CONDITION` honesty surfaced instead); fakes-not-hardware [M] items remain recorded-when-absent.** 765-test full suite green ×4 runs (58 new offscreen tests; one pre-existing engine export test flaked once, unreproducible — 25/25 isolated + full-suite passes); mypy 116 files clean, Ruff clean, compileall green, `DESKTOP_SMOKE_OK`. Details, engine truths and [M] limitations in `STAGE_11_IMPLEMENTATION_REPORT.md`.

## Stage 12 — Desktop remaining feature parity
**Scope:** Sensors, forensics cockpit, mirroring, demo mode, settings completeness.
**Dependencies:** Stage 11.
**Exclusions:** Android parity claims (A-F01).
**Acceptance criteria:** all C-Fxx rows supported-or-excluded with recorded rationale (same as Stage 08 checklist applied to desktop).

**Delivered (2026-10-21):** live monitoring page (real `MonitoringService` snapshot stream with honest `not-observed`/`unknown (probe failed)`/`unavailable` wordings — host-side explicit polling, NOT continuous monitoring, late/foreign events never clobber the current target), forensics cockpit (case-first over the real `ForensicsService`: create/open with verbatim duplicate refusal, byte-exact app-data extraction with sha256/byte-count records and honest gap notes, system logs/installed packages/running processes one-shots, WiFi REDACTED by default with the cleartext variant gated behind the exact typed `I ACCEPT CLEARTEXT PSK` phrase and the service-side confirmation gate, legacy-field `report.json`), mirroring page (real `ScreenMirrorService` lifecycle with tool-preflight refusal of unvalidated tools, duplicate-launch prevention, `turn_screen_off` NOT offered, launch≠verified-window honesty), demo mode (deterministic `DemoService` fixture with unmissable `[DEMO]` labeling, ZERO device contact and ZERO scan-history/selection impact, obvious return to live data), and the R-13 double-gated administration operations (launch/force-stop/uninstall with operation-specific exact-package-retype dialogs, freshly revalidated explicit targets, cancel dispatches nothing, dispatched-vs-verified wording; the engine's SERVICE-level `validate_confirmation` gate is never bypassed). All C-Fxx desktop rows are supported-or-excluded per the matrix note. Staged only as a real bug fix surfaced by the desktop pipeline: the engine forensics progress emission now satisfies the typed progress contract (§3 of the report). **Scope deviations (recorded): real scrcpy window display behavior [UNVERIFIED] (tested through a registry-seam fake; the [M] item stands); fakes-not-hardware [M] items remain recorded-when-absent.** 827-test full suite green ×2 fresh-process + ×2 instrumented runs (62 new offscreen tests); mypy 121 files clean, Ruff clean, compileall green, `DESKTOP_SMOKE_OK`. Details, fixed defects and [M] limitations in `STAGE_12_IMPLEMENTATION_REPORT.md`.

## Stage 13 — Motion, polish, accessibility and UX
**Scope:** TUI animations/hints polish; desktop motion restrained & purposeful; both UIs: focus order, contrast, reduced-motion setting, error copy pass, i18n-ready strings, empty/loading/error states.
**Dependencies:** Stage 12.
**Exclusions:** no functional changes.
**Acceptance criteria:** accessibility checklist pass recorded; UX walkthrough of all screens with screenshots archived in docs; reduced-motion honored in both UIs.

**Delivered (2026-10-21, desktop scope):** restrained motion shipped as a policy module (`ui_desktop/motion.py`): one 140 ms content fade on genuine user navigation only (never on the initial switch, never for a same-section re-selection, never fabricated progress, never the sole state signal, no GUI-thread blocking, effect removed on completion, restart-safe) and honest reduced-motion detection via Qt 6.12 `QAccessibilityHints.motionPreference` (OS settings on Windows/macOS/GNOME, runtime-verified against PySide6 6.12.0) with a documented `VSCANNER_REDUCED_MOTION` override. Accessibility pass (practical, no WCAG claim recorded): every `widgets.button` exposes an accessible name; dynamic state banners across monitoring/mirroring/demo/reports/dashboard/settings named; destructive-dialog buttons carry honest names ("Cancel — dispatches nothing"); REAL-dialog Escape tests prove admin/cleartext/settings Escape paths never accept/save/dispatch; initial focus reaches the nav rail; WCAG-AA contrast matrix computed over the theme tokens — `TEXT_MUTED` and the primary-button fill were the two AA failures and were retuned (same hue families; automated contrast tests lock the fix). Design-system refinement from a fact-based audit: QCombo/QPlainTextEdit/QTextEdit/QPlainTextEdit popup/default-button/horizontal-scrollbar QSS added (native arrow/indicator rendering deliberately preserved), `theme.feedback_qss(kind)` centralizes inline feedback colors, palette placeholder text token-driven, dialog widths audited vs the 960×640 minimum. 864-test full suite green ×2 fresh-process + ×2 instrumented runs (37 new offscreen tests); mypy 123 files clean, Ruff clean, compileall green, `DESKTOP_SMOKE_OK`. One pre-existing intermittently-failing Stage 12 monitoring-stream assertion was investigated (not masked) and repaired to assert the real product guarantee; see `STAGE_13_IMPLEMENTATION_REPORT.md` §7. **Scope deviations (recorded): the TUI animations/hints clause is descoped (this stage's binding brief is the desktop experience; TUI copy/UX delivery completed in Stages 05–08); manual Windows real-window visual walkthrough and assistive-technology checks remain [M] with no screenshots archived in this environment; screenshots-under-qa/ item [M].**

## Stage 14 — Windows executable and installer
**Scope:** Nuitka build pipeline (chosen mode from Stage 01), icon/splash/version metadata, optional bundled tools mode, installer (Inno/MSI), uninstaller, code-signing decision recorded.
**Dependencies:** Stage 13.
**Exclusions:** no feature changes; no macOS/Linux packaging in this stage.
**Acceptance criteria:** unsigned (or signed if keys provided) exe + installer build reproducibly on CI; installer passes install/launch/uninstall on a clean Windows VM profile; exe startup time and size recorded; launcher tests green.

**Delivered (2026-10-22):** T-05 strategy executed end to end — `packaging_windows/` package (version/staging/validation/build/icon/launcher modules + `installer.iss` + committed generated `assets/vscanner.ico`) builds a Nuitka **standalone** `V-Scanner.exe` (console disabled, PySide6 plugin, version metadata from the `pyproject.toml` authority via the quad derivation `3.0.0a0 → 3.0.0.0`) and a per-user Inno Setup 6.7.3 installer `V-Scanner-3.0.0a0-Setup.exe` (sha256 in `STAGE_14_IMPLEMENTATION_REPORT.md`). Dist closure 64 files / 84.1 MiB, exe 17,127,936 bytes; packaged `--smoke` boots from a spaced, repo-external path and from the installed location under a foreign CWD; startup recorded at **1012–1107 ms** (acceptance ≤ 4 s). Install/launch/uninstall smoke executed on this host: silent per-user install to `{localappdata}\Programs\V-Scanner`, Start-menu shortcuts + uninstall registry key `{1AB0A622-DB19-4B71-88B9-1988011A281A}_is1` verified, uninstall via `unins000.exe /VERYSILENT` (the Add/Remove-Programs path) succeeded and **user data in `%LOCALAPPDATA%\vscanner` was empirically retained**; silent uninstalls skip the optional data-deletion question via the `UninstallSilent()` guard (Inno shows `[Code]` MsgBoxes even in `/VERYSILENT` — root-caused, sources + docs cited). Recorded decisions [D]: bundled ADB/scrcpy variant = NOT bundled (provisioning flow instead, T-05); code signing = unsigned (no certificate; SmartScreen implications documented). Two toolchain root-causes are documented with reproducers: Inno's `VersionInfoVersion` needs a 4-part value (quad added) and `/DPRODUCT_VERSION` silently loses to an ISPP built-in name (renamed to the locked `VSCANNER_*` define scheme). Suite 933 passed ×2 fresh + coverage run (74% TOTAL, 13,854 stmts), ruff/mypy (131 files)/compileall/`--smoke` gates green; 69 packaging tests added. Honest deviations: CI-runner reproducibility and clean-Windows-VM matrix remain [M] (no `.github/` CI exists in the repo; build reproducibility from a clean staging tree with recorded inputs proven instead); doctor-page click-through inside the installed exe, real-display HiDPI checks and `Setup.exe /UNINSTALL` behavior on other hosts are [M] follow-ups recorded in `STAGE_14_IMPLEMENTATION_REPORT.md` §13.

## Stage 15 — Security, compatibility and release QA
**Scope:** Security review of packaged surfaces (no secrets in logs, artifact redaction, safe defaults), full regression matrix (legacy CLI vs TUI vs desktop on same fixtures), install matrix Windows versions, performance/memory baselines, documentation consistency pass.
**Dependencies:** Stage 14 artifacts.
**Exclusions:** new features.
**Acceptance criteria:** zero known security findings without owners; all parity rows consistent across 4 surfaces (legacy CLI, Click CLI, TUI, desktop); regression suite 100% pass; release notes drafted.

**Delivered (2026-10-22):** Stage 15 executed against the real Stage 14 artifacts (still byte-intact: exe sha256 `1bf3eb42…27c637`, installer `ac9229ae…25bc` — no drift; PE metadata 3.0.0.0 re-verified). Two reproducible defects found, minimally fixed, and regression-locked: **D1** staging silently followed NTFS junction/symlinks and materialized foreign content into the release tree (pre-fix leak empirically demonstrated against `07a83bf`; post-fix `staging.py` refuses any link entry with a typed error — junction-aware on Python 3.12+, floor-safe) and **D2** dist validation accepted unexpected extra executables and stray `.py`/`.pyc` (now: exactly one exe, compiled-closure-only; the rule instantly exposed a stale Stage 14 test fixture, corrected). 20 new toolchain-free QA tests (`test_stage15_release_qa.py`, 18 pass + 2 honest privilege skips); real dist + fresh staging re-validated under the strengthened rules (64 files). Installer lifecycle executed on the host: fresh silent install (66 files, no tasks/services/Run keys), install-exe launch smoke under a foreign spaced CWD (`DESKTOP_SMOKE_OK`), **reinstall-over-existing** (file inventory unchanged except Inno uninstaller-bookkeeping regeneration, planted user-data marker intact), ARP-path `unins000.exe /VERYSILENT /LOG=` uninstall (dir + shortcuts + registry removed, user data **retained**, no hidden modal). Spaced-plus-non-ASCII path run executed through the real engine (config round trip + all three report formats in `…ünïcødé ✓` dirs). Performance baselines recorded (no earlier numeric bound was ever defined; owner note for Stage 16): engine scan 0.13 ms/app mean on a synthetic 60-app bundle, packaged smoke startup median 619.9 ms (≤ 4 s met), peak WS ≈ 77.8 MiB. ISCC 6.7.3 recompile of the committed ISS from the same dist produced a **bit-identical installer** (same sha256) — deterministic same-machine output; clean-runner reproducibility still not claimable (no CI). Secrets-scan over logs/reports: app writes no log files by design; packaged-exe/pattern/user-data/pytest-artifact scans all clean; `api_key` strings are the R-06 redaction pattern names by construction. Artifacts remain **unsigned**. Suite: **951 passed** (+2 honest skips) across one plain + five instrumented full runs; one documented 1-in-6 under-load monitoring-test flake investigated and recorded (Stage 16 monitor note); Stage 07 export flake not observed. Honest status: Windows 10/other-SKU and clean-VM checks BLOCKED (no VM available); interactive uninstall + doctor click-through + HiDPI/reduced-motion [M]. Detail: `STAGE_15_IMPLEMENTATION_REPORT.md` + `qa/security_review.md` (required report) + `RELEASE_NOTES_DRAFT.md` (drafted, pre-publication).

## Stage 16 — Final release and documentation
**Scope:** Tag, publish GitHub Release with installer artifacts, user documentation (TUI + desktop quickstart), README/MASTER_README consolidation, CHANGELOG, archive stale docs, final `PROGRESS.md` = all complete.
**Dependencies:** Stage 15 sign-off.
**Exclusions:** scope expansion.
**Acceptance criteria:** release tagged without force-push; artifacts downloadable; docs cross-checked against actual behavior by a reviewer not identical to implementation author; repo tree contains no tracked generated artifacts (per Stage 01 decision list); all 17 stages marked complete in PROGRESS.md.

**Executed (2026-10-22, documentation within authorized scope — deviations recorded):** Stage 16 reconciled the Stage 00–15 evidence into `STAGE_16_FINAL_RELEASE_REPORT.md` (single source-of-truth release record: stage-by-stage completion, packaging/artifact inventory with **independently rechecked** hashes `1bf3eb42…27c637` / `ac9229ae…25bc` byte-identical to the records, build reproduction, installer lifecycle + user-data guarantees, D1/D2 security record, exact gate results, compatibility matrix, risk/owner register, and the disposition) and shipped the user/development documentation: `WINDOWS_INSTALLATION.md`, `RELEASE_CHECKLIST.md` (22-check status grid with owner roles), `CHANGELOG.md`, and a full `README.md` rewrite (stale 2.0-era content replaced; no download URL invented; the false "MIT License - See LICENSE file" footer removed because **no LICENSE file exists**; 2.0-era docs demoted to historical references). Documentation contract locked by exactly 1 consolidated test (`tests/unit/test_stage16_release_docs.py`). Gates ×2 fresh: **952 passed / 2 honest skips**, coverage TOTAL 74% (13,854 stmts), ruff clean, mypy 133 files clean, compileall green, `DESKTOP_SMOKE_OK`, packaging suite green. Commits `2ebc4fa` + tracker commit on `origin/main`. **AC deviations (honest):** "release tagged without force-push" and "artifacts downloadable" NOT DONE — creating them was outside this stage's authorized boundary and requires separate explicit maintainer authorization (no tag, release, upload or signature exists); "reviewer not identical to implementation author" NOT DONE; stale docs not archived (legacy docs remain, demoted); "all 17 stages marked complete" satisfied in PROGRESS. Disposition recorded: **NOT READY for distribution** with exact conditions (report §13). No tag was created and nothing was published — documentation completion is not permission to publish.

---

## Cross-stage acceptance principles
1. Nothing is "complete" until its automated or manual verification result is recorded in `PROGRESS.md` with the executing stage.
2. The legacy CLI compatibility contract is measured after every stage (Stage 02 golden suite re-run).
3. Destructive device features may only be (re)introduced with explicit user approval recorded in the stage log.
4. Every stage pushes to `origin/main` via normal HTTPS git push; push failures stop the stage and require a report — never force-push.
