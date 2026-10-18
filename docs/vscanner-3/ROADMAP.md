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
**Acceptance criteria:** `docs/vscanner-3/ARCHITECTURE_SPEC.md` covering every named service and model; all Stage 00 "decision required" items resolved with rationale; spec reviewed against the actual import graph (no unresolved cycles); PROGRESS updated.

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

## Stage 04 — Job lifecycle and event system
**Scope:** Implement the job system (`Job`, `JobHandle`, typed events, cooperative cancellation, timeouts) and re-route scanning/reporting/provisioning/monitoring jobs through it.
**Dependencies:** Stage 03 services.
**Exclusions:** no UI.
**Acceptance criteria:** unit tests prove cancellation of a long scan a) stops between apps b) terminates ADB subprocesses c) leaves partial state consistent; event ordering test; benchmark: event overhead < 5 ms/finding in the suite.

## Stage 05 — TUI foundation and visual design
**Scope:** Textual app shell: startup doctor (provisioning + dependency status as commands, no auto-pip), device status bar, theme, keybindings, navigation, config storage in user directory (with legacy import).
**Dependencies:** Stage 04 job system.
**Exclusions:** no device mutating operations yet; legacy CLI remains available.
**Acceptance criteria:** TUI launches headless-tested (textual run/test harness) to a device dashboard with 0 device required; keymap documented; config round-trip test; no regression in legacy CLI.

## Stage 06 — TUI device workspace
**Scope:** Device discovery/selection/switching, device info panels (incl. full info, network, build), app inventory browser with search/pagination and improved honest app-name handling.
**Dependencies:** Stage 05 shell + Stage 03 device services.
**Exclusions:** scanning, forensics, mirroring (staged later).
**Acceptance criteria:** with a real device OR a replayed ADB fake: detect, select, switch, display info; app list renders ≥ 100 packages with search + page navigation; every action cancellable.

## Stage 07 — TUI scanning and findings
**Scope:** Single-app analysis, full-device scan with live progress, findings browsing (typed findings), SDK/permission drill-down, insecure URL surfacing, report export (HTML/JSON/text) from TUI.
**Dependencies:** Stage 06.
**Exclusions:** admin ops, forensics, sensors, mirroring.
**Acceptance criteria:** scan of a faked dataset produces typed findings matching Stage 03 golden data; export files byte-identical to legacy format for same input (regression) or documented improvements; cancel mid-scan works.

## Stage 08 — TUI feature parity and hardening
**Scope:** Remaining features: admin ops (uninstall/open/force-stop with confirmations), sensor monitoring (honest data), full device info, screen mirroring launcher, forensics cockpit (byte-safe extractors, case store, redaction default for WiFi PSK), demo/sample mode, error/edge-case hardening.
**Dependencies:** Stage 07.
**Exclusions:** no new scanner heuristics beyond legacy; Android app untouched.
**Acceptance criteria:** parity checklist against `FEATURE_PARITY_MATRIX.md` — every C-Fxx row implemented or explicitly excluded with recorded rationale; no feature regression vs legacy CLI contract; keyboard-only operability test; TUI has no blocking I/O on the event loop (latency check).

## Stage 09 — Desktop foundation and design system (PySide6)
**Scope:** Qt main window, design tokens shared with TUI vocab, layouts, navigation, settings dialog, notifications/status handling, packaging groundwork (app icon, metadata).
**Dependencies:** Stage 08 TUI parity complete.
**Exclusions:** feature logic (reuses services).
**Acceptance criteria:** desktop launches on Windows 10/11 from the dev environment; renders dashboard skeleton; runs job system correctly in Qt event loop (integration test); High-DPI correct.

## Stage 10 — Desktop dashboard and device management
**Scope:** Device discovery/switching UI, device info panes, app inventory browser, admin operations with confirmation dialogs.
**Dependencies:** Stage 09.
**Exclusions:** scanning/forensics/mirroring UIs.
**Acceptance criteria:** same acceptance set as Stage 06, executed in Qt harness + manual with device where available.

## Stage 11 — Desktop scanner and findings
**Scope:** Scan configuration, live job progress, findings tables/detail views, report export, scan history (local, optional).
**Dependencies:** Stage 10.
**Exclusions:** sensor/forensics/mirror.
**Acceptance criteria:** Stage 07 criteria re-verified in desktop; history round-trip test (`history/` JSON schema limited to local data).
 
## Stage 12 — Desktop remaining feature parity
**Scope:** Sensors, forensics cockpit, mirroring, demo mode, settings completeness.
**Dependencies:** Stage 11.
**Exclusions:** Android parity claims (A-F01).
**Acceptance criteria:** all C-Fxx rows supported-or-excluded with recorded rationale (same as Stage 08 checklist applied to desktop).

## Stage 13 — Motion, polish, accessibility and UX
**Scope:** TUI animations/hints polish; desktop motion restrained & purposeful; both UIs: focus order, contrast, reduced-motion setting, error copy pass, i18n-ready strings, empty/loading/error states.
**Dependencies:** Stage 12.
**Exclusions:** no functional changes.
**Acceptance criteria:** accessibility checklist pass recorded; UX walkthrough of all screens with screenshots archived in docs; reduced-motion honored in both UIs.

## Stage 14 — Windows executable and installer
**Scope:** Nuitka build pipeline (chosen mode from Stage 01), icon/splash/version metadata, optional bundled tools mode, installer (Inno/MSI), uninstaller, code-signing decision recorded.
**Dependencies:** Stage 13.
**Exclusions:** no feature changes; no macOS/Linux packaging in this stage.
**Acceptance criteria:** unsigned (or signed if keys provided) exe + installer build reproducibly on CI; installer passes install/launch/uninstall on a clean Windows VM profile; exe startup time and size recorded; launcher tests green.

## Stage 15 — Security, compatibility and release QA
**Scope:** Security review of packaged surfaces (no secrets in logs, artifact redaction, safe defaults), full regression matrix (legacy CLI vs TUI vs desktop on same fixtures), install matrix Windows versions, performance/memory baselines, documentation consistency pass.
**Dependencies:** Stage 14 artifacts.
**Exclusions:** new features.
**Acceptance criteria:** zero known security findings without owners; all parity rows consistent across 4 surfaces (legacy CLI, Click CLI, TUI, desktop); regression suite 100% pass; release notes drafted.

## Stage 16 — Final release and documentation
**Scope:** Tag, publish GitHub Release with installer artifacts, user documentation (TUI + desktop quickstart), README/MASTER_README consolidation, CHANGELOG, archive stale docs, final `PROGRESS.md` = all complete.
**Dependencies:** Stage 15 sign-off.
**Exclusions:** scope expansion.
**Acceptance criteria:** release tagged without force-push; artifacts downloadable; docs cross-checked against actual behavior by a reviewer not identical to implementation author; repo tree contains no tracked generated artifacts (per Stage 01 decision list); all 17 stages marked complete in PROGRESS.md.

---

## Cross-stage acceptance principles
1. Nothing is "complete" until its automated or manual verification result is recorded in `PROGRESS.md` with the executing stage.
2. The legacy CLI compatibility contract is measured after every stage (Stage 02 golden suite re-run).
3. Destructive device features may only be (re)introduced with explicit user approval recorded in the stage log.
4. Every stage pushes to `origin/main` via normal HTTPS git push; push failures stop the stage and require a report — never force-push.
