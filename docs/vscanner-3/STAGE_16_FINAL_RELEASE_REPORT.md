# V-Scanner 3.0 — Stage 16: Final Release Report

**Stage:** 16 of 16 (Final release and documentation) · **Date:** 2026-10-22 · **Baseline:** `main` == `origin/main` == `2bb7b80` (Stage 15 docs head, HTTPS-only origin `https://github.com/ToTheBlankWorld/V-Scanner.git`)

> **Read this first.** This document is the single source-of-truth release record for the
> V-Scanner 3.0 release candidate `3.0.0a0`. It consolidates the audited Stage 00–15 facts,
> resolves earlier contradictions, and states an honest release disposition.
>
> **Release disposition: NOT READY for distribution** — see §13. In particular:
> **no Git tag was created, no GitHub Release was published, no artifact was uploaded,
> and nothing was signed in this stage.** Those actions require a separate, explicit,
> maintainer authorization. This document is documentation, not an approval.

---

## 1. Executive summary

V-Scanner 3.0 (`3.0.0a0`) is a free, local-only Android security scanner for Windows
x64, delivered across Stages 00–15 as a rewritten, typed engine behind three user
surfaces (menu-driven CLI, terminal TUI, PySide6 desktop app) plus a Windows
packaging pipeline (Nuitka standalone executable + Inno Setup per-user installer).
Stages 14–15 produced and audited the release-candidate artifacts; Stage 16
consolidates the evidence into this record and the accompanying user documents
(`README.md`, `WINDOWS_INSTALLATION.md`, `RELEASE_CHECKLIST.md`, `CHANGELOG.md`).

Key facts in one place:

* **Version authority:** `pyproject.toml` `version = "3.0.0a0"` (single source; lockstep-tested against `ui_desktop.APP_VERSION`). Windows VERSIONINFO quadruple `3.0.0.0` is *derived* (`3.0.0a0 → 3.0.0.0`) for PE/Inno metadata; the verbatim `3.0.0a0` remains in `AppVerName`, the installer filename and user-visible strings.
* **Artifacts (independently rechecked during Stage 16, 2026-10-22):** `V-Scanner.exe` SHA-256 `1bf3eb42fa0fb5007e8c8b8f4b6c54db9cb76a4fcb7569cdabd1ebae2b27c637` (17,127,936 B, `FileVersion`/`ProductVersion` 3.0.0.0, `ProductName` V-Scanner) and `V-Scanner-3.0.0a0-Setup.exe` SHA-256 `ac9229aedb574ec052686779b864fb95d592b218133365f7b93bb2245dae25bc` (25,010,550 B). Both byte-identical to the Stage 14/15 records — no drift since the build. Distribution contents: 64 files (41 `.dll` + 22 `.pyd` + 1 `.exe` + 0 `.py`), ≈ 84.1 MiB closure. **Unsigned.**
* **Quality gates:** this stage executed **952 passed / 0 xfailed / 2 honest privilege skips** twice in fresh processes plus a coverage run (TOTAL **74%**, 13,854 statements, unchanged measurement), Ruff clean, mypy clean in **133 source files**, `compileall` green, desktop smoke green, packaging suite green (exact results + commands in §9.2).
* **Security:** two release-pipeline defects found and fixed in Stage 15 (**D1** staging link-follow leak; **D2** dist-closure weakness), both regression-locked; zero known security findings without owners; all artifacts and scans clean of secrets.
* **Disposition:** **NOT READY.** The build itself shows no reproducible defect, but the project's own mandatory Stage 16 acceptance criteria (release tagged without force-push, artifacts downloadable, documentation cross-checked by an independent non-author reviewer) are unmet, and they cannot be met without explicit authorization and human involvement outside this stage. §13 lists the exact conditions to reach CONDITIONALLY READY and ready.

---

## 2. Release identity, baselines and versioning authority

| Field | Value |
|---|---|
| Project | V-Scanner |
| Version | **3.0.0a0** (prerelease release candidate) |
| Versioning authority | `pyproject.toml` `[project] version` — single source; `packaging_windows` reads it at build time; nothing in the packaging tooling hardcodes a version |
| Derived quadruple | `3.0.0a0 → 3.0.0.0` via `versioning.derive_version_quad()` (Inno `VersionInfoVersion` requires a four-part numeric value; root-caused and test-locked in Stage 14) |
| Exe PE metadata | `FileVersion` = `ProductVersion` = **3.0.0.0** (rechecked Stage 16); `ProductName` V-Scanner |
| Installer name / `AppVerName` | `V-Scanner-3.0.0a0-Setup.exe` (verbatim prerelease suffix retained for humans and upgrade logic) |
| Baseline at Stage 16 start | `main` == `origin/main` == `2bb7b80` |
| Stage 15 code commit (latest product change) | `0a19b3c` (`test(release): harden security and compatibility validation`) |
| Release-candidate HEAD at Stage 16 close | Stage 16 documentation commits on top of `2bb7b80` (see `PROGRESS.md` commit record) |
| Runtime floor | Python ≥ 3.10 (engine); build host ran Python 3.12.10 |

---

## 3. What was delivered (features and architecture)

* **One audited engine, three surfaces.** `vscanner/` is a typed package (frozen core models/errors/redaction/paths/knowledge-base + service layer: ADB clients, config, doctor, registry, jobs/events, orchestration, scanning, app inventory, reports, history, tools provisioning). Every surface consumes the same services, so findings and legal-defensive redaction behave identically everywhere.
* **Surfaces:** legacy menu-driven CLI (`cli/`, rewritten as thin engine adapters where behavior changed); Click CLI command surface; terminal TUI (`ui_terminal`, Textual, `vscanner-tui` / `python -m ui_terminal`); Windows desktop app (`ui_desktop`, PySide6 6.12.0 Widgets, `vscanner-desktop` / `python -m ui_desktop`).
* **Feature set (desktop + TUI parity):** dashboard with honest "not checked until probed" state; device discovery/selection with exact verbatim parser rows and root tri-state; installed-app inventory browser; full-device and single-app scans with streamed honest progress and real cancellation; findings explorer with provenance; byte-parity report export (HTML/JSON/text); report history; live monitoring polls (never continuous, never fabricated); forensics case collection (byte-exact on-disk extraction with SHA-256 records, WiFi PSK redacted by default with an explicit typed `I ACCEPT CLEARTEXT PSK` gate); device administration (launch/force-stop/uninstall behind exact-package retype confirmations and a service-level gate); mirroring lifecycle with tool preflight and argv-only spawn; deterministic demo mode with zero device contact; Doctor self-check diagnostics; offline settings/config round-trip with legacy import.
* **Honesty-by-construction rules:** nothing is reported that was not observed; cancelled/failed/partial states are explicit; unknown values render `unknown`, not guesses; secret-matching findings never render their values (R-06 redaction); destructive operations are typed, revalidated, and cancellable-before-dispatch.
* **Windows packaging:** `packaging_windows/` (staging with allowlist + link-refusal policy, dist validation with single-exe + compiled-closure policy, Nuitka build, icon, version derivation, Inno installer contract) builds the standalone exe and the per-user installer. Tooling is build-time only and never ships inside the application.

---

## 4. Stage-by-stage completion summary (Stages 00–15)

All stages below are recorded **COMPLETE** in `docs/vscanner-3/PROGRESS.md`; test counts are the state at each stage's close.

| Stage | Name | Key commit(s) | Tests at close | One-line outcome |
|---|---|---|---|---|
| 00 | Repository audit and feature inventory | `39e54f8` | — | Full audit: feature inventory, defect classes R-01…R-13, remediation plan; safe checks (py_compile ×11, dependency audit) recorded |
| 01 | Architecture and migration specification | `796632d` | — | 7 architecture spec docs; import graph acyclic; service contracts / parity rows / acceptance criteria set |
| 02 | Regression tests and project foundation | `407ee31` | 106 passed / 7 xfail | `tests/` suite + `pyproject.toml` + `TESTING_STRATEGY.md`; golden byte-baselines for reports |
| 03 | Shared engine and service layer | `f60bee7` | 276 passed / 4 xfail | `vscanner/` engine + legacy re-wire; SC-9 three-format **byte-parity** proven; coverage 41% |
| 04 | Job lifecycle and event system | `2a9d548` | 363 passed / 4 xfail | Frozen events + JobManager (cancellation, watchdogs, mutex groups, redaction); latent `AppInfo.tolerant` defect found and fixed |
| 05 | TUI foundation and visual design | `55993a6` | 399 passed / 4 xfail | Textual shell + `vscanner-dark` theme + doctor/settings/dashboard/help; keymap doc locked to code |
| 06 | TUI device workspace | `8a513f3` | 446 passed / 4 xfail | Device workspace + honest tri-states/failure banners + app inventory browser over the job pipeline |
| 07 | TUI scanning and findings | `3e83103` | 505 passed / 4 xfail | Scan screen with honest streamed progress/cancellation + findings explorer + reports export through SC-9 |
| 08 | TUI feature parity and hardening | `0beff75` | 602 passed / 0 xfail | Monitoring, forensics, mirroring, demo, admin in TUI; R-03/04/05/06/07/12/13 remediations landed; xfails flipped |
| 09 | Desktop foundation and design system | `058de46` | 640 passed | PySide6 shell, token-generated theme, section registry, Qt job bridge with GUI-thread delivery proven |
| 10 | Desktop dashboard and device management | `3727f43` | 707 passed | Truthful dashboard, device workspace, inventory browser, settings with live ADB validation; admin deferred to Stage 12 (recorded) |
| 11 | Desktop scanner and findings | `d345dc9` | 765 passed | Scan/findings/reports desktop parity with legacy byte-schema export; recorded deviations (single-app not exportable; deep-scan UNVERIFIED path honesty) |
| 12 | Desktop remaining feature parity | `43e562d` | 827 passed | Monitoring/forensics/mirroring/demo/admin pages live; R-13 administration delivered; engine forensics-progress contract bug found via the desktop pipeline and fixed |
| 13 | Motion, polish, accessibility and UX | `4393df7` | 864 passed | Restrained motion policy (140 ms nav fade, reduced-motion), practical a11y pass, automated WCAG-AA contrast matrix with two token retunes, real-dialog Escape safety |
| 14 | Windows executable and installer | `fc67f6e` | 933 passed | Nuitka standalone + Inno per-user installer built and lifecycle-tested on the host; toolchain root-causes (VERSIONINFO quad, ISPP name collision) documented + test-locked; artifacts hashed; recorded decisions: **not bundled tools**, **unsigned** |
| 15 | Security, compatibility and release QA | `0a19b3c` | 951 passed / 2 honest skips | D1 (staging link-follow leak) and D2 (dist closure) found, fixed, regression-locked with empirical pre-fix proof; installerLifecycle executed (install/reinstall/ARP uninstall + retention); perf baselines recorded; secrets scans clean; release notes drafted |

Contradiction resolutions applied in this record (vs. earlier summary texts):

* Perf medians are the Stage 15 measured values (engine scan median **0.09 ms/app** standard, **0.10 ms/app** deep on a synthetic 60-app bundle; packaged smoke startup median **619.9 ms**; peak working set ≈ **77.8 MiB**). No earlier stage ever defined a numeric "≤ N ms" acceptance bound — that remains an owner note (§12), and no threshold was invented in Stage 15 or 16.
* Stage 10 admin deferral was retired in Stage 12, not forgotten; the desktop layer has no destructive command outside the confirmation gate.
* The installer uninstall path used by users is `unins000.exe` (Add/Remove Programs / Windows Settings → Apps). A `Setup.exe /UNINSTALL` no-op was observed once in Stage 14 on the build host; it is recorded and was not retested — user guidance points at the verified path only.

---

## 5. Packaging and artifact inventory

### 5.1 Toolchain (build host: Windows 11 Pro build 26200 x64)

| Component | Version | Role |
|---|---|---|
| Python | 3.12.10 | Build host runtime |
| Nuitka | 4.3.1 | Standalone executable compiler (PySide6 plugin, console disabled) |
| Inno Setup (ISCC) | 6.7.3 | Per-user installer/uninstaller compiler |
| PySide6 | 6.12.0 | Desktop layer (packaged into the exe) |
| Source of truth | `packaging_windows/build_windows.py`, `packaging_windows/installer.iss` | Pipeline + installer contract, both test-locked |

### 5.2 Standalone distribution contents (`V-Scanner.dist` — rechecked Stage 16)

* 64 files total: **41 `.dll`**, **22 `.pyd`**, **1 `.exe`** (V-Scanner.exe), **0 `.py`** — compiled closure only (the Stage 15 D2 rule).
* ≈ 84.1 MiB dist footprint; installed per-user tree ≈ 66 files under `%LOCALAPPDATA%\Programs\V-Scanner`.

### 5.3 Artifact hashes and verification labels

| Artifact | Size (B) | SHA-256 | Verification label |
|---|---:|---|---|
| `V-Scanner.exe` | 17,127,936 | `1bf3eb42fa0fb5007e8c8b8f4b6c54db9cb76a4fcb7569cdabd1ebae2b27c637` | **Independently rechecked in Stage 16 (2026-10-22)** — hash recomputed from the on-disk file, PE metadata re-read; matches Stage 14/15 records |
| `V-Scanner-3.0.0a0-Setup.exe` | 25,010,550 | `ac9229aedb574ec052686779b864fb95d592b218133365f7b93bb2245dae25bc` | **Independently rechecked in Stage 16 (2026-10-22)** — hash recomputed; matches Stage 14/15 records |

* Sign status: **unsigned** (no certificate exists; recorded Stage 14 decision `[D]`, SmartScreen consequences documented in `WINDOWS_INSTALLATION.md`).
* Determinism: Stage 15 recompiled the installer from the same dist with ISCC 6.7.3 → **bit-identical SHA-256** (deterministic same-machine output). Clean-runner reproducibility is **not claimable** (no CI runner exists in this repo) and is an owner item (§12).
* State at Stage 16 start: app **not installed**, `%LOCALAPPDATA%\vscanner` empty (0 files); ISCC 6.7.3 present.
* No rebuild was performed in Stage 16; the recorded artifacts remain the Stage 14 build.

---

## 6. Build reproduction (maintainer instructions)

Prerequisites: Windows 10/11 x64, Python ≥ 3.10 with the project installed plus `[desktop]` (PySide6) and Nuitka; an Inno Setup 6 ISCC.exe (the pipeline fetches/uses a pinned copy, or pass `--iscc PATH`).

```text
python -m packaging_windows.build_windows [--work-dir PATH] [--iscc PATH]
```

* Staging copies only the allowed production sources into a fresh stage dir (allowlist-only; any symlink/junction entry is refused — the D1 rule) and validates the resulting dist (exactly one executable; compiled-closure-only — the D2 rule) before and after the build.
* Outputs: `V-Scanner.exe` (standalone) and the Inno installer named from the `pyproject.toml` version.
* **Caution:** a rebuild replaces the working tree's build outputs. The recorded release-candidate artifacts live outside the repo tree; if a rebuild is ever performed for release comparison, record the new hashes and whether the binaries differ (see §9 of the mission record: no rebuild happened in Stage 16).
* Installer contract tests (`tests/unit/test_stage14_packaging.py`, extended in Stage 15) lock the ISS semantics (per-user, define-only versions, uninstall default-retain, silent-guard) without any toolchain.

---

## 7. Installation, upgrade, uninstall and user-data guarantees

All executed and recorded in Stage 14/15 on the build host (Windows 11 Pro build 26200):

| Behavior | Recorded result |
|---|---|
| Install (silent) | Exit 0; per-user install to `{localappdata}\Programs\V-Scanner`; Start-menu shortcut + per-user Start-menu uninstall shortcut; ARP registry key `{1AB0A622-DB19-4B71-88B9-1988011A281A}_is1`; **0 scheduled tasks / 0 services / 0 Run-key entries** |
| Launch | Installed-exe smoke under a foreign spaced CWD: `DESKTOP_SMOKE_OK`; standalone dist smoke boots from a spaced, repo-external path |
| Reinstall over existing | Exit 0; file inventory unchanged except Inno uninstaller bookkeeping (`unins000.dat/.exe`) regenerated by design; planted user-data marker intact |
| Uninstall (ARP path, silent) | `unins000.exe /VERYSILENT ...` completes without hidden modal (log: "Removed all? Yes", "Need to restart Windows? No"); install dir + shortcuts + registry key removed; **user data retained** |
| Uninstall (interactive) | NOT TESTED interactively (see checklist); the Inno `[Code]` offers the optional data-deletion question with retain as the default button (`MB_DEFBUTTON2`), and silent installs skip the question via the `UninstallSilent()` guard |
| `Setup.exe /UNINSTALL` | No-op observed once in Stage 14 on this host; not re-executed; users are guided to the verified path |
| User-data guarantee | `%LOCALAPPDATA%\vscanner` (config, reports, history, forensics cases, provisioned ADB/scrcpy) is **never silently deleted** by uninstall; deleting it is a manual, explicit act |
| Persistent footprint | No tasks, no services, no Run keys, no telemetry, no auto-update channel |

User-facing details and troubleshooting: `WINDOWS_INSTALLATION.md`.

---

## 8. Security findings and fixes

### 8.1 Release-pipeline findings (Stage 15, both fixed and regression-locked)

| ID | Severity | Finding | Fix | Proof |
|---|---|---|---|---|
| D1 | HIGH | `shutil.copytree(symlinks=False)` in staging **follows** NTFS junctions/symlinks, silently materializing foreign/possibly secret content into the release tree (allowlist bypass) | `staging.first_link_entry()` + junction-aware `_is_link()` (3.12+ `Path.is_junction` probed for the 3.10 floor); any link entry under `vscanner/`, `ui_desktop/` or the launcher raises a typed `ValueError` | Pre-fix leak **empirically demonstrated** against extracted `07a83bf` code (planted unprivileged junction made an injected secret appear in the staged tree); post-fix refusal verified; regression tests use a REAL junction (`mklink /J`, unprivileged); file-symlink variants skip honestly where the OS requires privilege (WinError 1314) |
| D2 | MEDIUM | `validate_distribution` accepted unexpected extra executables and stray `.py`/`.pyc` | Exactly-one-exe + compiled-closure-only policies with actionable typed errors | Strengthened rule instantly exposed and corrected a stale Stage 14 test fixture (`_fake_dist` modeled a stray `.py`; real dist has zero) — full Stage 14 packaging suite still green; no assertion weakened |

### 8.2 Earlier remediations carried to the release

R-01 (single admin-menu definition), R-02 (typed loader), R-03 (phantom extractor removal per A-06), R-04 (no fabricated sensor rows), R-05 (failed root detection never reports root), R-06 (secret patterns applied + value redaction), R-07 (byte-safe binary extraction), R-11 (path-traversal hardening), R-12 (job-boundary redaction), R-13 (admin operations gated behind exact-package retype + service validation). Full records: `docs/vscanner-3/SECURITY_AND_REMEDIATION_PLAN.md`, `docs/vscanner-3/qa/security_review.md`.

### 8.3 Hygiene verified this cycle

* External-command discipline: zero `shell=True`/`os.system` in engine/desktop; argv-only spawning at every ADB/scrcpy seam (spaced paths verified whole).
* Secrets scans (Stage 15): the app writes no log files by design; packaged-exe/pattern-name/user-data/pytest-artifact/ISCC-log scans all clean; `api_key` strings in the artifact are the R-06 redaction pattern names by construction; endpoint inventory = the two provisioning URLs (Google platform-tools, official Genymobile scrcpy) plus documentation citations only.
* Traversal protections (R-11 `_extraction`, forensics case-store rejection, provisioning cleanup, atomic config save) re-read and test-locked; export destinations are user-declared by design.
* Everything executed as a standard user — no elevation anywhere.

---

## 9. Testing and quality-gate evidence

### 9.1 Suite history

Stage counts (0 xfail after Stage 08): 02→106, 03→276, 04→363, 05→399, 06→446, 07→505, 08→602, 09→640, 10→707, 11→765, 12→827, 13→864, 14→933, 15→**951 passed + 2 honest privilege skips** (40 files). With the Stage 16 documentation-consistency test added (1 consolidated test), the suite stands at **952 passed / 2 skipped** (exact runs in §9.2).

The 2 permanent skips are honest privilege skips in the Stage 15 D1 regression class: OS policy requires privilege for file symlink creation (WinError 1314) on this host; the junction variants execute for real. No xfail remains suite-wide (`xfail_strict` on; Stage 08 flipped the last of them).

### 9.2 Stage 16 final gate results (exact, executed 2026-10-22)

| Gate | Command | Result |
|---|---|---|
| Full suite (fresh process, run 1) | `python -m pytest tests -q` | **952 passed, 2 skipped** in 167.12 s |
| Full suite (fresh process, run 2) | `python -m pytest tests -q` | **952 passed, 2 skipped** in 164.24 s |
| Coverage | `python -m pytest tests -q --cov=vscanner --cov=ui_terminal --cov=ui_desktop --cov=cli --cov-report=term` | **952 passed, 2 skipped** in 297.04 s; **TOTAL 74%** (13,854 statements — measurement unchanged) |
| Lint | `ruff check .` | **All checks passed** (exit 0) |
| Types | `mypy` (tests + engine + UI layers) | **Success: no issues found in 133 source files** (was 132; +1 for the new doc-test file) |
| Byte-compilation | `compileall -q vscanner cli ui_terminal tests ui_desktop packaging_windows` | **exit 0** |
| Desktop smoke | `python -m ui_desktop --smoke` | **DESKTOP_SMOKE_OK** |
| Packaging suite | `python -m pytest tests/unit/test_stage14_packaging.py tests/unit/test_stage15_release_qa.py -q` | **87 passed, 2 skipped** (both skips = honest privilege skips; 0.58 s isolated) |

The +1 test versus the Stage 15 count (951 → 952) is exactly the consolidated documentation-consistency test `tests/unit/test_stage16_release_docs.py::test_stage16_release_documentation_contract`; both skips remain the two honest WinError-1314 privilege skips from the Stage 15 D1 regression class. No code file changed in Stage 16.

### 9.3 Intermittent-test history (honest record)

* **Stage 07 export flake** (engine report export, observed once in Stage 11): deterministic re-ordering tests added; **never observed again across 7 subsequent full-suite runs** through Stage 15.
* **Stage 12 monitoring GUI-thread flake** (`test_poll_session_streams_snapshots_on_gui_thread`, 1-in-6 under one instrumented run in Stage 15): investigated, not masked. Both assertions are the Stage 13-real product invariants (GUI-thread delivery lane + bridge fan-out consistency); the exact failure text was not captured on the one occurrence and it never reproduced across 5 subsequent full instrumented runs plus standalone. Carried as a Stage 16 monitoring note → owner item (§12).
* The Stage 16 runs add no new flakes; their outcomes are part of the §9.2 record.

### 9.4 Coverage interpretation (do not flatten)

TOTAL 74% over 13,854 statements (measurement: `pytest --cov=vscanner --cov=ui_terminal --cov=ui_desktop --cov=cli`). The measured bulk's uncovered remainder is the legacy CLI interactive/print paths (uncovered by design decision); the engine anchors are surgery-grade (events 100%, orchestration 100%, models 99%, jobs 91%, reports 98%; desktop backend 94%, scan screen 90%, repo-quality anchors per stage in `TESTING_STRATEGY.md` §6). `packaging_windows/` is deliberately outside the measured source set (build tooling, not shipped code) and is covered by its own 100+ toolchain-free tests plus the executed real-artifact validations.

---

## 10. Compatibility matrix

Legend: **VERIFIED** = executed with recorded evidence; **NOT TESTED** = no evidence; **BLOCKED** = no environment available.

| Surface | Claim | Evidence | Status |
|---|---|---|---|
| Windows 11 (build 26200, x64) — build + install + launch + reinstall + uninstall + retention | Same-machine VERIFIED | Stage 14/15 lifecycle executions; Stage 16 preflight re-verified artifacts + clean state | VERIFIED (build host only) |
| Windows 10 x64 | "Windows 10 or 11 (x64)" in user docs is an unverified claim for Win10 | No Windows 10 environment was ever available | NOT TESTED / BLOCKED |
| Other Windows SKUs (Server/Home-scale differences) | Untested | No environment | NOT TESTED / BLOCKED |
| Clean-VM installation | Untested | No clean VM available in this project | NOT TESTED / BLOCKED |
| Interactive (GUI) uninstall | Implementation + silent-guard + default-retain verified by tests; interactive walkthrough never executed | Stage 14/15 records | PARTIAL — NOT TESTED interactively |
| Installed-app Doctor click-through (clicking through a real installed session) | Smoke launch of the installed exe verified; interactive page walkthrough not executed | Stage 14/15 | PARTIAL |
| HiDPI / display scaling / larger text on physical displays | Qt defaults + automated theme/contrast tests only | Stage 13 tokens; no physical-display matrix | NOT TESTED |
| Reduced-motion behavior on Windows | Implemented via Qt 6.12 OS hints + env override; unit-tested; live OS-toggle behavior on real hardware not verified | Stage 13 | PARTIAL |
| Keyboard-only / assistive technology (screen reader) | Automated accessible-name locks, focus policies, Escape safety; human AT walkthrough not performed | Stage 13 a11y locks | PARTIAL |
| Physical Android device operations (scan/inventory/monitor/forensics/admin/mirror) | All device-facing validation used the fake-transport harness and service-level seams; argv-level ADB/scrcpy handling verified (including spaced paths) | Stages 02–13 suites; Stage 15 seam checks | PARTIAL — no physical Android device was attached during Stage 15 |
| scrcpy mirroring window behavior with real scrcpy | `ScreenMirrorService` faked at the registry seam in Stage 12; real-window display UNVERIFIED | Stage 12 record | NOT TESTED (real display) |
| Provisioning downloads (ADB from `dl.google.com`, scrcpy from official Genymobile GitHub releases) | Code paths + failure honesty tested against fakes; only network activity the app can make, always explicit | Stages 04–08/12 | PARTIAL (real download not exercised this cycle) |
| Python floor (engine importability without PySide6) | Engine/UI tests run without `[desktop]` via `importorskip`; verified since Stage 09 | Suite design | VERIFIED |

---

## 11. Known limitations (carried, reassessed — none silently dropped)

1. Artifacts are **unsigned**; first-run SmartScreen warning is expected (user guidance is hash verification, not security-control bypass).
2. **Windows 10 / other SKU compatibility: never tested** (no environment). The user-facing claim "Windows 10 or 11 (x64)" is honest only as a requirement statement, not as tested behavior.
3. **Clean-VM installation: never tested.**
4. Interactive uninstall, installed-app Doctor click-through, HiDPI/larger-text, reduced-motion live changes, and keyboard/assitive-technology walkthroughs are incomplete (above).
5. **No physical Android device** was attached in Stages 14–15 validation; device-facing behaviors are fake-harness-verified with argv-seam checks.
6. Single-app scans are not exportable (legacy export schema needs a full-device bundle) — an honesty rule, not a defect; deep-scan host-side URL/secret extraction carries explicit `UNVERIFIED_CONDITION` outcomes.
7. **Dependency lockfile/reproducibility gap:** floors only (e.g., `rich>=13.0.0`), no lockfile; the same-machine ISCC recompile bit-identical result does not transfer to clean runners (no CI exists — ROADMAP/Stage 14 recorded deviation).
8. **Monitoring test flake** (1-in-6 under load) investigated but never root-caused because it never reproduced (§9.3).
9. No LICENSE file exists in the repository; no license is granted or claimed by the rewritten README (the old "MIT License" footer was factually wrong and has been removed).
10. The README's old 2.0-era flow ("auto-download ADB/scrcpy on first run") no longer describes the product; downloads are always explicit user actions through provisioning.
11. Legacy 2.0-era documents (`TOOLS_SYSTEM.md`, `QUICK_START.md`, `MASTER_README.md`, `docs/*` 2.0 files) remain in the tree as historical references; Stage 16 does not archive them (recorded deviation against the Stage 16 roadmap AC "archive stale docs" — out of this stage's authorized scope without a dedicated review).
12. No telemetry, no auto-updates: users obtain releases from the project page when one is actually published (none exists at the time of writing).
13. This release candidate has **never been distributed**: no tag, no GitHub Release, no artifact upload exists.

---

## 12. Risks, owners and follow-ups

No owner names are invented; only honest roles.

| # | Risk | Severity | Owner (role) | Required next action |
|---|---|---|---|---|
| 1 | Unsigned artifacts → SmartScreen warnings; integrity rests on hash comparison | MEDIUM | Release maintainer | Either (a) re-affirm the recorded `[D]` decision with maintainer acceptance and keep hash-based verification guidance, or (b) purchase/obtain a code-signing certificate and re-sign + re-verify artifacts (new hashes then become the record) |
| 2 | Windows 10 / clean-VM compatibility unverified | HIGH (per Stage 14 AC) | Release maintainer + QA maintainer | Execute the installer/lifecycle matrix on Windows 10 and a clean VM, or record an explicit scope decision excluding them from 3.0.0 |
| 3 | Interactive uninstall, Doctor click-through, HiDPI, reduced-motion, keyboard/AT checks incomplete | MEDIUM | QA maintainer | Execute the interactive walkthroughs on the installed build; record per-item PASS/FAIL in `RELEASE_CHECKLIST.md` |
| 4 | Publication never happened; Stage 16 AC items "tagged"/"downloadable" unmet | HIGH (mandatory AC) | Release maintainer | Explicitly authorize + perform: Git tag on the release-candidate commit, GitHub Release with the verified installer + SHA-256 + release notes (from `RELEASE_NOTES_DRAFT.md`, reconciled with this report) |
| 5 | No independent non-author review of the release documentation (AC) | MEDIUM (mandatory AC) | Release maintainer | Assign a reviewer not identical to the implementation author; record their cross-check sign-off |
| 6 | Dependency lockfile gap; no CI reproducibility proof | MEDIUM | Build/packaging maintainer | Produce a lockfile (pip-tools/uv) for the build environment; optionally add a CI runner for clean-runner reproducibility evidence |
| 7 | Monitoring GUI-thread test flake (never reproduced, never root-caused) | LOW | QA maintainer | Keep monitoring future instrumented runs; root-cause on first reproduction; do not mask |
| 8 | No numeric performance bound was ever defined ("≤ N ms" acceptance) | LOW | Release maintainer | Define the requirement numerically in a future stage or formally retire it; Stage 15/16 baselines remain recorded as observations |
| 9 | No LICENSE file; licensing undecided | MEDIUM | Project owner / Release maintainer | Decide and document the license (adding a LICENSE file + updating `pyproject.toml`), or keep the project's current "no license granted" wording explicit |
| 10 | Legacy 2.0-era docs left in-tree (archive-not-done deviation) | LOW | Docs maintainer | Move/mark `TOOLS_SYSTEM.md`, `QUICK_START.md`, `MASTER_README.md`, `docs/*` 2.0 files as historical in a separate, reviewed docs pass |

---

## 13. Release disposition

### 13.1 The decision rule applied

* **READY** — only when every required release criterion is satisfied by observed evidence.
* **CONDITIONALLY READY** — known limitations remain AND an authorized maintainer has **explicitly accepted** them and no mandatory criterion is unresolved.
* **NOT READY** — a mandatory release requirement remains unresolved.

Missing approval is not approval. No signed-off maintainer acceptance of the limitations exists; there is no independent reviewer record; and the project's own Stage 16 acceptance criteria contain mandatory items ("release tagged without force-push", "artifacts downloadable") that are unmet.

### 13.2 Disposition: **NOT READY for distribution**

Rationale (evidence-based, not about build quality — no reproducible defect exists in the release-candidate build or its artifacts):

1. **Publication ACs unmet:** the release is not tagged, no GitHub Release exists, no artifact is downloadable. These are the Stage 16 roadmap/AC *mandatory* conditions, and the Stage 16 execution scope explicitly excluded them pending separate authorization. Documentation completion is not permission to publish.
2. **No maintainer acceptance:** the CONDITIONALLY READY tier requires explicit documented acceptance of the known limitations; none exists in any stage record.
3. **No independent review:** the AC's documentation cross-check requires "a reviewer not identical to implementation author"; no such review has occurred.
4. **Unverified compatibility claims:** Windows 10 and clean-VM remain BLOCKED (no environment); interactive uninstall/Doctor/HiDPI/reduced-motion/keyboard-AT are incomplete. These do not automatically make the build defective, but none of them may be represented as verified.

### 13.3 Exact conditions to move forward

| To reach | Conditions |
|---|---|
| **CONDITIONALLY READY** | (a) an authorized maintainer explicitly accepts the §11 limitations in writing (Stage 16 ACs "tagged"/"downloadable" may be conditionally waived only by that acceptance); (b) risk rows 2 and 3 of §12 are either executed or explicitly accepted; (c) the independent-review condition is satisfied or explicitly waived by the same maintainer; (d) items 4/9 (publication plan + license decision) are scheduled with owners |
| **READY** | everything above **plus**: Git tag on the release-candidate commit (normal push, no force), GitHub Release published with the verified artifacts + SHA-256 values + final release notes, and a re-verified artifact hash set matching the published files |

While NOT READY / not-accepted: do not distribute any artifact outside a maintainer-verified channel; do not point users at any download URL (none legitimately exists).

### 13.4 Explicit boundary statement for this stage

Stage 16 delivered documentation, documentation tests, and tracker updates only. It created **no Git tag, no GitHub Release, no artifact upload, no signing certificate, no signature, and no announcement**. If any of those occurred, they happened outside this stage's record and must be audited separately.

---

## 14. Document map

| Document | Audience | Purpose |
|---|---|---|
| `README.md` (repo root) | New users + contributors | What the product is, how to get/install it (honestly), where to report problems |
| `docs/vscanner-3/WINDOWS_INSTALLATION.md` | Windows users | Prerequisites, install/SmartScreen/verify, ADB & scrcpy, data locations, upgrade/uninstall, troubleshooting |
| `docs/vscanner-3/RELEASE_CHECKLIST.md` | Release maintainer / QA | Per-check status grid with evidence + owners |
| `docs/vscanner-3/CHANGELOG.md` | Everyone | Version history (candidate-level; nothing published) |
| `docs/vscanner-3/RELEASE_NOTES_DRAFT.md` | Release maintainer | Draft notes for the future GitHub Release (pre-publication, Stage 15) |
| `docs/vscanner-3/PROGRESS.md` | Maintainers | Authoritative stage tracker + execution logs + commit records |
| `docs/vscanner-3/STAGE_14_IMPLEMENTATION_REPORT.md`, `STAGE_15_IMPLEMENTATION_REPORT.md`, `qa/security_review.md` | Maintainers/auditors | Primary evidence: toolchain, hashes, lifecycle, D1/D2, baselines, owner register |
| `docs/vscanner-3/ROADMAP.md`, `ACCEPTANCE_CRITERIA.md`, `TESTING_STRATEGY.md`, `FEATURE_PARITY_MATRIX.md` | Maintainers | Scope, ACs, test strategy incl. per-stage suite facts, parity matrix |
| `docs/vscanner-3/SECURITY_AND_REMEDIATION_PLAN.md` | Maintainers/auditors | R-01…R-13 remediation records and flip evidence |
