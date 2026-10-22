# V-Scanner 3.0 — Release Readiness Assessment (2026-10-22)

Post–Stage 16 phase: **release readiness, final QA and publication preparation**.
Verdict first, evidence trail after. This report adds to — and does not replace —
`STAGE_16_FINAL_RELEASE_REPORT.md` (all Stage 16 statements remain in force).

## 1. Verdict

**NOT READY for publication.** Every engineering quality gate passed, but the
unmet conditions are authorization and acceptance, not engineering:

| Condition for CONDITIONALLY READY | State |
|---|---|
| Project LICENSE file exists and is accepted by the maintainer | **Absent** — owner decision, nothing invented for them |
| Independent, non-author review of user-facing documents | **Not performed** — no reviewer available (BLOCKED, owner: release maintainer) |
| Windows 10 compatibility executed or explicitly scoped out | **BLOCKED** — no Win10 environment (unchanged from Stage 16) |
| Clean-VM installation walkthrough | **BLOCKED** — no clean VM (unchanged from Stage 16) |
| Physical Android device pass | **BLOCKED** — no device available (unchanged from Stage 16) |

CONDITIONALLY READY additionally requires explicit maintainer acceptance of the
known limitations recorded in §8 (F-1, F-2) and of the unsigned distribution
(checklist #12). READY additionally requires interactive HiDPI / reduced-motion
/ keyboard-AT passes and the publication items (tag + GitHub Release + upload)
under separate authorization. **Documentation completion is not permission to
publish** — no tag, release, upload, or signature was created in this phase.

## 2. Scope, baseline, environment

- Branch `main`, baseline `45cb0b7` — verified equal to `origin/main` before
  work began; push target is the HTTPS remote only.
- Host: Windows 11 Pro (build 26200) x64, single machine, no CI, no signing
  certificate, no VM, no physical device, no assistive technology.
- Toolchain: Python 3.12.10 · PySide6 6.12.0 · Nuitka standalone dist (Stage 14) ·
  Inno Setup 6.7.3.
- Constraint honored throughout: two pre-existing unrelated user items (a
  whitespace-only modified `.gitignore` and an untracked `cli/` Python file)
  were preserved, never staged, never altered; `android/**` untouched.

## 3. Artifact identity and provenance

Both artifacts were re-checked byte-for-byte at phase start and remain exactly
the Stage 14 outputs (no rebuild performed):

| Artifact | SHA-256 | Size |
|---|---|---|
| `V-Scanner.exe` (packaged dist) | `1bf3eb42fa0fb5007e8c8b8f4b6c54db9cb76a4fcb7569cdabd1ebae2b27c637` | 17,127,936 B |
| `V-Scanner-3.0.0a0-Setup.exe` | `ac9229aedb574ec052686779b864fb95d592b218133365f7b93bb2245dae25bc` | 25,010,550 B |

**Installer bit-identity revalidated this phase.** The recompile of the
committed `installer.iss` with ISCC 6.7.3 reproduced the installer
**byte-identical** to the Stage 14 artifact (`BIDENTICAL: True`, same size and
SHA-256). Root-cause transparency for the verification path itself:

1. The first recompile attempt differed from the verified artifact by one byte,
   with a byte-diff map showing 8 localized regions: scattered flip bytes in
   the setup header area (offsets ~850008–851412) plus single-point spillover
   into the compressed stream (~23.8M/25.0M offsets) — not a data change.
2. Two *fresh* compiles back-to-back were byte-identical to each other, so the
   toolchain is deterministic; the divergence had to be a compile input.
3. The byte-diff localized it precisely: a UTF-16 version field read
   `3.0.0.0` in the Stage 14 artifact vs `3.0.0` in the recompile — the
   throwaway driver had passed `derive_numeric_version("3.0.0a0")`
   (`3.0.0`) as `VSCANNER_RESOURCE_VERSION`, while the real pipeline passes
   `derive_version_quad("3.0.0a0")` (`3.0.0.0`) to ISCC.
4. With the pipeline's actual values, the recompile is byte-identical.

Confirmed claims thereby: same-machine Installer determinism
(checklist #21) **PASS**; clean-runner reproducibility remains **unclaimed**
(no non-identical runner exists to test it on).

## 4. Requirements lockfile (new)

Checklist #11 was **FAIL** ("floors only, no lockfile"). It is now addressed
with new artifacts, committed with this report:

- `requirements-lock.txt` — 18 exact-pin rows for the full installed runtime
  closure on the build host: click 8.4.2, colorama 0.4.6, jinja2 3.1.6,
  markdown-it-py 4.2.0, markupsafe 3.0.3, mdit-py-plugins 0.6.1, mdurl 0.1.2,
  platformdirs 4.13.4, pygments 2.20.0, PySide6 6.12.0 (plus the
  `pySide6-addons / -essentials / -pdf / -webengine` companion pins), rich
  15.0.0, shiboken6 6.12.0, textual 8.2.8, typing-extensions 4.15.0.
- `tools/gen_requirements_lock.py` — the generator that produced it from the
  installed environment (exact versions, transitive closure).
- `tests/unit/test_requirements_lock.py` — 21 checks: 3 closure tests (every
  declared direct dependency is locked; lock matches the installed closure;
  declared set consistency) plus 18 parametrized pin-vs-installed checks.

Honest limits, unchanged in substance: the pins describe the *verified build
environment*; no CI runner exists, so "build a clean environment strictly from
these pins and get the bit-identical artifact" is recorded as a recommended
follow-up, not a verified property (clean-runner reproducibility unclaimed).

## 5. Quality gates (exact, fresh processes, serial)

| Gate | Command | Result |
|---|---|---|
| Suite, first run (A) | `pytest tests -q` | 971 passed, 2 honest skips — **2 failed: the two new lockfile closure tests**, due to a quote-stripping bug in their TOML parsing helper (declared-dependency names picked up a stray quote). Self-inflicted by the new tests, not a product regression; fixed and re-proven the same phase |
| Suite, plain rerun (A2) | `pytest tests -q` | **973 passed / 2 skipped** (169.29 s). The 2 skips are the pre-existing WinError-1314 symlink-privilege skips |
| Suite + coverage (B) | `pytest tests -q --cov --cov-report=term` | **973 passed / 2 skipped**, coverage **TOTAL 74%** (13,854 statements, 3,559 missed; config unchanged) (297.05 s) |
| Lint | `ruff check .` | exit 0 — "All checks passed!" |
| Types | `mypy` | exit 0 — "Success: no issues found in 134 source files" |
| Syntax | `compileall -q vscanner cli ui_terminal tests ui_desktop packaging_windows` | exit 0 |
| Desktop smoke | `python -m ui_desktop --smoke` | exit 0 — `DESKTOP_SMOKE_OK` |
| Packaging suite | stage 14 + stage 15 test files | **87 passed / 2 skipped** (2 honest privilege skips) |
| Lockfile tests | `pytest tests/unit/test_requirements_lock.py` | **21 passed** (0.07 s) after the fix |
| Installer recompile | ISCC 6.7.3, throwaway output dir | byte-identical (§3) |

Suite delta vs Stage 16 (952 passed): **+21** exactly the new lockfile tests;
no other movement anywhere.

## 6. Intermittent test — full root-cause ledger (F-3)

The Stage 11/16-era observation (1-in-6 under load, never reproduced, recorded
unmasked in checklist #16) was **finally reproduced and investigated during
this phase, without touching any assertion**:

- `tests/unit/test_stage12_desktop.py::TestMonitoringPage::test_poll_session_streams_snapshots_on_gui_thread`
  asserts that every snapshot the monitoring session emits is delivered to hub
  observers **on the GUI thread only** (Stage 13 real invariant).
- **Battery run #1 (bare-lambda observer, unchanged app):** 30 serial isolated
  runs, quiet machine → **29 pass / 1 FAIL** (run 14). The page counted the
  snapshot (`poll_count == 1`) but the test's observer list stayed empty.
- **Under load:** 5 concurrent pytest workers × 5 runs each, on the unchanged
  test → **25/25 pass**. Combined unchanged-code tally: **54/55**.
- **Instrumented reproduction** (exact test body, 20 trials, standalone):
  race at trial 20 — and the decisive observation: the bridge's own
  delivery trace shows exactly one `('snapshot', <worker thread id>)`
  emission, the page's production-shaped internal receiver received it
  (`poll_count == 1`), and **even two extra event-pumps afterward never
  delivered anything to the test's observer**. The event was lost, not delayed,
  and not delivered on a wrong thread.
- **Variant matrix** (20 trials each, fresh page per trial, strict teardown):
  A plain-lambda/AutoConnection (the test's original shape), B bound method of
  a `QObject`/AutoConnection (the production receiver shape used by every
  shipped screen), C lambda/QueuedConnection, D lambda/DirectConnection —
  **80/80 clean** (D confirmed the emission happens on the worker thread, as
  designed). A survey of the shipped screens confirms **every production hub
  observer is a bound method of a GUI-thread `QObject`**; no plain-callable
  observer exists in app code.

**Classification:** a test-harness observer-shape artifact, not an app
event-flow defect. The bare Python lambda path under PySide6 (a
`GlobalReceiver`-style plain-callable receiver) lost its queued delivery in
roughly 1 in ~55 cross-thread deliveries on this host; the Qt-level internals
of that loss are beyond what could be proven locally (a PySide6 upstream issue
report is the recommended follow-up). The emitted-once, production-receiver-
delivered evidence rules out hub fan-out loss or cross-thread delivery of the
snapshot itself.

**Fix (no assertion changed):** the test's observer is now
`_SnapshotReceiver`, a small `QObject` with a bound-method slot — the exact
receiver shape every shipped screen uses — recording the same thread ids into
the same list. Every assertion is identical (`idents` non-empty, all ids equal
to the GUI thread id, one delivery per counted snapshot). The docstring in the
test records the whole story.

**Re-battery on the fixed observer:** 30 serial isolated runs, quiet machine →
**30/30 PASS**. The one failing observed run of the old no-teardown repro and
the 1/55 rate remain honestly recorded above; the residual uncertainty is only
the unproven PySide6-internal mechanism, not any unverified app behavior.

## 7. Interactive packaged-app QA (real clicks, real installer, real GUI)

Executed non-invasively on the *installed* packaged app (the verified
artifacts, default per-user install directory), while the user was actively
using the machine: driving used posted mouse click pairs at UIA element
rectangles (with the empirically confirmed row-off-by-one rule), synthetic
keyboard was never used, and a running-app screenshot record was captured via
window-image capture plus UIA element dumps. Evidence files (screenshots 13,
14, 15, 16, 17, 18, 19, 20, 21, 26, 27 + `.dump.txt` transcripts) are machine
temp artifacts, listed verbatim in §10.

Static verification:

- **Fresh launch → Dashboard verified** (title, banner, controls).
- **Rail walk, 8 of 9 sections verified deterministically**, each with its
  section title + screenshot + UIA dump: Devices (tabs `Installed apps` /
  `Administration`), Scan (honesty guidance), Reports, Monitoring, Forensics,
  Mirroring — including the honest "scrcpy tool state: not found — launches
  are REFUSED" state — Demo (`[DEMO]` labels throughout), Doctor.
- **Settings dialog:** opened, fields verified, Cancel invoked, verified gone.
- **Help & keys** (last rail row): could not be selected non-invasively — the
  row is virtualized out of the visible viewport, wheel posts were ineffective
  and synthetic keyboard is refused on an inactive window. **PARTIAL,
  recorded as such.**
- **Dashboard adb check click-through:** invoked the real control; the app
  rendered its honest FAILING verdict for the saved path (finding F-2 below).
  Control test: the same path launches fine from a plain shell (exit 0,
  version 36.0.2) — the defect is app-side spawn, not the path.
- **Graceful shutdown:** window-manager close pattern → clean process exit,
  repeated.

Installer lifecycle (silent + interactive):

- Silent reinstall over an existing install: retention sentinel intact after.
- Silent uninstall: install directory, uninstall registry entry and Start-menu
  shortcuts all removed; user data retained.
- Spaced-path silent install: **quoting is mandatory** — an unquoted
    `/DIR=...`-style argument truncates at the first space (a mangled
  `...\Programs\V` install happened and was cleaned up; with quotes the
  install lands correctly). Launch from a spaced install directory + clean
  close both worked.
- **Interactive uninstall via the real GUI:** the uninstaller's confirmation
  dialog ("Are you sure you want to completely remove V-Scanner and all of
  its components?") was driven through its real button and completed; user
  data retained. Screenshot evidence recorded. Finding F-4 (quirk): while an
  uninstaller instance runs, Inno renames its launcher to `_unins.tmp` under
  its temp dir; a second launch then fails with the File-in-use error
  (WinError 32) while the first holds its data file — process detection for
  installers must match the `_unins*` process name, not the launcher name.
- Final state restored: clean silent install back at the default directory,
  packaged exe hash identical to the artifact record.

Data protection through all of the above churn (install/reinstall/uninstall/
reinstall + app launches): the user-saved configuration file
(`%LOCALAPPDATA%\vscanner\config\config.json`, user-created through the app's
own settings flow) remained **byte-stable** (SHA-256 recorded before/after:
prefix `D343B546387170C3…`) with stable content including the saved `adb_path`.

## 8. Findings (with owners)

- **F-1 — Doctor's frozen-runtime dependency honesty is misleading.** In the
  packaged exe, the rich/click dependencies report "installed" but the Doctor
  view reports rich/click as "NOT INSTALLED" while the same page shows jinja2
  as installed — frozen executables expose no package metadata, so the Doctor
  check's importlib-metadata probe blind-spots. Its "pip install -e ."
  instruction is also meaningless inside a packaged exe (there is no project
  to install). Cosmetic honesty defect of a diagnostics screen; no functional
  impact on scanning/monitoring. Owner: packaging maintainer (make the
  packaged build embed the truth, or detect the frozen state and say so).
- **F-2 — Packaged app cannot spawn adb on this host.** The Dashboard's
  availability check on the saved path reports "the saved path did not launch
  a working adb", and device discovery cannot spawn it either — both fail
  with a WinError 5 (access denied) spawn failure, while the identical launch
  from a plain shell exits 0. Host-environment-bound in nature (process-
  creation differences of the packaged app on this machine — e.g. an active
  security agent or launch-environment difference — are the standing
  hypothesis, unproven). Consequence: on affected hosts the packaged app
  cannot drive any adb-based workflow. Owner: packaging maintainer; **must be
  re-verified on other hosts (clean VM / physical machine) before relying on
  it**, since it contradicts the Stage 14/15 spawn test-locks (fake-process
  harness there, real spawn here).
- **F-3 — Intermittent GUI-thread delivery test flake.** Reproduced, ledgered
  and fixed at the observer-shape level; residual uncertainty is only the
  unproven PySide6-internal mechanism (§6). Owner: QA maintainer; recommended
  upstream report.
- **F-4 — Uninstaller second-launch quirk (documented, not changed).** The
  `_unins.tmp` Rename + WinError-32 behavior is standard Inno behavior; the
  finding is the operational lesson (process matching by launcher name fails).
  Owner: QA maintainer (documentation only).

## 9. Compatibility matrix (honest)

| Environment | Status |
|---|---|
| Windows 11 Pro x64 (this build host, physical) | **PASS** — full lifecycle + interactive QA |
| Windows 10 x64 | **BLOCKED** — never available at any stage; the user-facing "Windows 10 or 11" claim stays unverified for Win10 |
| Clean VM (no host-state residue) | **BLOCKED** — never available |
| Physical Android device (real adb workflows, mirroring, forensics targets) | **BLOCKED** — no device; fake-transport harness only |
| HiDPI / display scaling (100/125/150/200%) | **NOT TESTED** (automation theme locks only) |
| Reduced-motion OS toggle | **PARTIAL** (implemented + unit-locked; live OS toggle never toggled) |
| Keyboard-only / screen readers | **PARTIAL** (focus/accessible-name/Escape automation locks; no human pass) |

## 10. Licensing and attribution

Dependencies re-verified this phase by reading the installed distributions:

| Package (installed) | License |
|---|---|
| rich 15.0.0 | MIT |
| click 8.4.2 | BSD-3-Clause (Pallets) |
| jinja2 3.1.6 | BSD-3-Clause (Pallets) |
| markupsafe 3.0.3 | BSD-3-Clause (Pallets) |
| textual 8.2.8 | MIT |
| PySide6 / shiboken6 6.12.0 | LGPL-3.0-only (alternatively GPL-3.0-only / GPL-2.0-only under the Qt dual-license terms); dynamically linked, and the application does not re-export or statically bind Qt — the LGPL separation conditions are satisfied by the packaging as built |

Not individually re-verified this pass: the transitive set (colorama,
markdown-it-py, mdit-py-plugins, mdurl, platformdirs, pygments,
typing-extensions). Recommended before publication: a complete license
inventory table with install-time third-party notices. **The project itself
still has no LICENSE file — that absence is exactly as recorded in Stage 16
(and is why the README states no license is granted); it is an owner decision,
not something to invent here.**

## 11. Remaining risks (top of register)

1. F-2 (adb spawn in the packaged app) — potentially user-blocking for adb
   workflows on unknown hosts; unverified anywhere except this host.
2. No independent reviewer — every document, including this one, is
   author-verified only.
3. Windows 10 / clean-VM — unverified user claims, unchanged since Stage 14.
4. Unsigned distribution — every user sees SmartScreen unknown-publisher
   friction, documented honestly in `WINDOWS_INSTALLATION.md`.
5. No CI — gates are machine-local; bit-identity is same-machine provenance
   only.

## 12. Shortest safe path to a real release

In dependency order: (1) maintainer decisions — LICENSE file, acceptance of
the unsigned/staged pre-release semantics, Win10 in-or-out of scope, F-2
treatment; (2) F-2 re-verification cross-host and either a fix or a documented
limitation; (3) one independent review pass over
`WINDOWS_INSTALLATION.md` + release notes draft + `RELEASE_CHECKLIST.md`;
(4) optional hardening: CI + clean-runner recompile from
`requirements-lock.txt` + license inventory; (5) tag + GitHub Release + upload
under explicit authorization, with hashes re-checked at publication time
against the published files, checklist items #12–#14 flipped to their final
statuses by the release owner. Until then, the Stage 16 boundary statement
stands: **no publication assets may be created without separate authorization.**

## 13. Evidence index (this phase)

Written evidence artifacts (machine temp directory, retained at assessment
time): quality-gate outputs `readiness_gateA.txt`, `readiness_locktest.txt`,
`readiness_gateB.txt`, `readiness_ruff.txt`, `readiness_mypy.txt`,
`readiness_compileall.txt`, `readiness_smoke.txt`, `readiness_pkg.txt`,
`readiness_gateA2.txt`; flake ledger `readiness_battery.txt` (30-run ledger
with the run 14 failure quoted in full), `readiness_load` (5 worker logs),
`readiness_matrix.txt`, `readiness_repro1.txt`; interactive QA screenshots
`13_dashboard_fresh.png` through `21_doctor.png`, `26_dashboard_adbcheck.png`,
`27_interactive_uninstall_confirm.png`, `.dump.txt` UIA transcripts per walked
section; installer-recompile verification logs
(`recomp-throwaway` / `recomp-twice` throwaway build directories with their
ISCC logs — reproducibility throwaways, safe to delete). Repo-tracked evidence
gain: `requirements-lock.txt`, `tools/gen_requirements_lock.py`,
`tests/unit/test_requirements_lock.py`, the `_SnapshotReceiver` test fix, and
this document set.
