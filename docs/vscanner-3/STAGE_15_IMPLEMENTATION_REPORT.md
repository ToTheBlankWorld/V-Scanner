# Stage 15 — Security, compatibility & release QA — Implementation report

**Date:** 2026-10-22 · **Branch:** `main` · **Baseline commit:** `07a83bf`
(Stage 14 docs head) · **Transport:** HTTPS only
(`https://github.com/ToTheBlankWorld/V-Scanner.git`)

---

## 1. Scope and baseline

Stage 15 audited the packaged Windows release produced by Stage 14
(`packaging_windows/` + Inno installer), fixed reproducible defects within
the existing architecture, added regression tests, ran the full gate set,
and recorded the compatibility/performance evidence the stage acceptance
requires. No Stage 16 work (tagging, publishing, sign-off) was started;
the release-notes draft is the Stage 15 acceptance item and lives at
`docs/vscanner-3/RELEASE_NOTES_DRAFT.md`.

**Preflight (executed):** branch `main`; local `main` == `origin/main` ==
`07a83bf`; pre-existing unrelated user items preserved untouched
(modified `.gitignore`, untracked `cli/python usb_charging_control.py`).
`android/**` never touched; no SSH, no force-push, no history rewriting,
no reset/clean, nothing staged blindly.

**Test environment (recorded, no assumptions):** single Windows 11 Pro
build 26200 x64 build host (all runtime checks are **same-machine**),
Python 3.12.10, Nuitka 4.3.1, ISCC 6.7.3 at
`%LOCALAPPDATA%\vscanner-build\inno\`, Stage 14 artifacts intact on disk,
no clean VM or second Windows version available, no signing certificate,
app **not installed** at stage start, `%LOCALAPPDATA%\vscanner` empty
(0 files).

**Baseline suite before any product change:** `python -m pytest tests -q`
→ **933 passed**, 169.67 s (matches the Stage 14 record exactly).

## 2. Audit areas and method

| Area | Method | Class |
|---|---|---|
| Staging/validation policy | code reading + new tests + real-tree runs | EXECUTED |
| Artifact integrity | hash/PE/file-type/string audits on the real dist + installer | EXECUTED |
| Installer lifecycle | real silent install / reinstall / uninstall on host | EXECUTED |
| Runtime & filesystem paths | code reading + executed odd-path run | EXECUTED |
| Device/external-tool safety | bullet→test mapping + grep verification | SOURCE (+ fake-backed suite) |
| Supply chain / signing | inspection + scans | SOURCE (+ executed scans) |
| Windows compatibility | host exports only | EXECUTED (same-machine) |

## 3. Findings and fixes

Full detail (including the executed pre-fix reproduction) in
`qa/security_review.md`; summary:

* **D1 (HIGH, FIXED):** staging followed NTFS junctions/symlinks and
  materialized foreign content into the release tree — the pre-fix leak
  was **empirically demonstrated** against `07a83bf` code (a planted
  junction made `MACHINE_SECRET` appear inside the staged tree;
  `copied_files` 5 instead of 4). Fix: `stage_release_tree` now refuses
  any link entry (`first_link_entry()` + junction-aware `_is_link()`,
  Python-3.10-floor-safe) and requires the launcher to be a regular file,
  raising a `ValueError` naming the path. Post-fix: refusal tests pass
  (real NTFS junction, unprivileged), the **real repo stages identically**
  (64 files — zero behavior change on a clean tree).
* **D2 (MEDIUM, FIXED):** `validate_distribution` accepted unexpected
  extra executables and stray `.py`/`.pyc` files. Fix: exactly-one-exe +
  compiled-closure-only rules with actionable `ValidationError` text.
  The new rule immediately exposed a stale Stage 14 *test fixture*
  (`_fake_dist` modeled a stray `PySide6/__init__.py`; the real dist has
  zero `.py` — the fixture was corrected to `__init__.pyd`; the full
  Stage 14 suite still passes).
* **No other reproducible defect found.** Reviewed-not-defect rationale
  (export destination by design, `find_iscc` discovery, `iscc.log`
  build-machine paths): see `qa/security_review.md` §2.

## 4. Artifact integrity (executed)

Release-record facts (Stage 14 artifacts on disk, byte-verified):

| Artifact | Size | SHA-256 | vs Stage 14 record |
|---|---|---|---|
| `V-Scanner.dist` (dist closure) | 64 files, 84.1 MiB | — | unchanged |
| `dist\V-Scanner.exe` | 17,127,936 B | `1bf3eb42fa0fb5007e8c8b8f4b6c54db9cb76a4fcb7569cdabd1ebae2b27c637` | **match** (no drift) |
| `V-Scanner-3.0.0a0-Setup.exe` | 25,010,550 B | `ac9229aedb574ec052686779b864fb95d592b218133365f7b93bb2245dae25bc` | **match** |

* File-type closure: **1** `.exe` (only `V-Scanner.exe`), **41** `.dll`,
  **22** `.pyd`, **0** `.py`/`.pyc`, **0** extra executables — now also
  enforced by the D2 validator rules (real dist passes).
* PE metadata re-verified this session: exe `FileVersion=ProductVersion=
  3.0.0.0`, `ProductName=V-Scanner`; installer `FileVersion=ProductVersion=
  3.0.0.0`. Both derive from the `pyproject.toml` authority `3.0.0a0`
  via the recorded quad derivation (test-locked in the Stage 15 file).
* String scans of the exe: no repository path, no username, no
  `vscanner-build` path; URL inventory = provisioning endpoints +
  citations only (`qa/security_review.md` §6).
* **Recompile validation (executed):** ISCC 6.7.3 compiled the committed
  `installer.iss` against the same dist into a throwaway output dir →
  `V-Scanner-3.0.0a0-Setup.exe`, 25,010,550 bytes, sha256
  **byte-identical to the Stage 14 record** (deterministic same-machine
  build for identical inputs; throwaway cleaned up afterwards; the
  release record remains the Stage 14 hash).
* Staging exclusion policy re-verified: fresh real-repo staging passes the new
  link check + staged-tree contract, copies exactly 64 files; forbidden
  inputs (`cli/adb_config.json`, user data, caches, VCS, `android/**`,
  tests) remain excluded by the tested allowlist.

## 5. Installer lifecycle (executed, same-machine)

Silent per-user installer artifact
`V-Scanner-3.0.0a0-Setup.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART`:

1. **Pre-state:** no install dir, no registry key, 0 user-data files.
2. **Fresh install:** exit 0; 66 files at
   `%LOCALAPPDATA%\Programs\V-Scanner`; Start-menu
   `V-Scanner.lnk` + `Uninstall V-Scanner.lnk`; registry
   `HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\{1AB0A622-DB19-4B71-88B9-1988011A281A}_is1`
   (`DisplayName=V-Scanner`, `DisplayVersion=3.0.0a0`,
   `InstallLocation` correct). Per-user location; **no elevation, no
   service, no scheduled task, no HKCU/HKLM Run-key entry** (enumerated:
   0/0/0).
3. **Launch smoke from the installed exe** under a foreign working
   directory containing a space (`%TEMP%\launch qa dir with space`):
   exit 0, `DESKTOP_SMOKE_OK`.
4. **Reinstall over the existing install** (supported upgrade smoke):
   exit 0; file inventory of the install directory identical except
   `unins000.dat/.exe` regenerated (Inno bookkeeping, by design); all
   64 application files timestamps identical; planted user-data marker
   intact (§6).
5. **Silent uninstall — ARP path** `unins000.exe /VERYSILENT
   /SUPPRESSMSGBOXES /NORESTART /LOG=` (exactly the `UninstallString`
   Add/Remove Programs executes): completed within seconds — no hang, no
   hidden modal; registry key removed (completion signal), install dir
   and both shortcuts removed, user data retained; log tail: `Removed
   all?  Yes`, `Need to restart Windows?  No`, `Log closed.` No residual
   `V-Scanner`/uninstaller processes.
6. Post-verification cleanup: the retention marker was removed; the
   app is uninstalled and the user-data dir ends this stage at 0 files.

Not executed: interactive (GUI) uninstall [M]; `Setup.exe /UNINSTALL`
(Stage 14's recorded no-op quirk stands, not re-attempted; the shipped
ARP path is unaffected); install-failure diagnostic UX (no safe, honest
way to force a real installer failure on this host — the pipeline's
fail-early error contracts are test-locked instead).

## 6. User-data retention (executed)

A marker file (`retention-marker.txt`, content `stage15-retention-check`)
was planted in `%LOCALAPPDATA%\vscanner` and survived **both** the
reinstall-over-existing and the ARP-path silent uninstall (silent
uninstalls retain user data unconditionally via the `UninstallSilent()`
guard recorded at Stage 14). Empirically: marker present + content
verified after each step; removed only by the QA cleanup afterwards.

## 7. Runtime and filesystem (executed)

**Spaced + non-ASCII directories:** a real engine run (config
read/write round trip through `sub dir ∙ config.json` and a real
scan→`ReportService.export` of all three formats) executed inside
`%TEMP%\stage15 paths …​\outputs with spaces – ünïcødé ✓` — config
88 bytes, `security_report_…​.html` 12,220 B / `.json` 2,481 B /
`.text` 2,739 B, all verified present and non-empty. Path resolution in
services uses `Path` objects throughout; no shell-string paths.
**Traversal protection** (source-level, test-locked): R-11 extraction
(`_extraction.py`: member validation before any write, PEP 706 filter
bonus), `forensics.py` traversal-component rejection for case stores,
provisioning temp-dir cleanup (`rmtree` in `finally`), config save is
atomic (`tempfile` + `os.replace`). Export destinations are
user-declared by design (see `qa/security_review.md` §2).
**No admin required:** installer and app ran entirely as a standard
user; no elevation anywhere in the lifecycle.
**Foreign-CWD launches:** both dist and installed exe boot under
unrelated working directories (stage 14 + re-verified here). Resources
are loaded from the installed layout; repo-root assumptions
(`vscanner/core/paths.py` repo-mode) activate only via explicit
`VSCANNER_LOCAL` dev override, by test and code.

## 8. Windows compatibility matrix

| Check | Status | Evidence (this stage unless noted) |
|---|---|---|
| Windows 11 Pro build 26200 x64 — fresh install | PASS | executed (§5.1–2) |
| Reinstall/upgrade over existing install | PASS | executed (§5.4) |
| Silent uninstall via ARP path | PASS | executed (§5.5) |
| Interactive (GUI) uninstall | **NOT TESTED** | manual GUI step [M] |
| Start-menu launch (shortcut click) | PARTIAL | shortcuts verified correct; actual GUI click not automated [M] |
| Packaged exe boot (foreign spaced CWD) | PASS | `DESKTOP_SMOKE_OK` exit 0 |
| Doctor page rendered inside packaged exe | **NOT TESTED** | human GUI check [M] |
| Full page navigation (dashboard…help) | **NOT TESTED** | human GUI check [M] |
| Missing-ADB behavior | PASS | engine honesty tests (typed error, no fabrication) |
| Missing-scrcpy behavior | PASS | mirroring typed-refusal tests (`ToolNotValidated`) |
| Malformed/absent optional config | PASS | typed `ConfigError` tests incl. legacy import isolation |
| User-data retention across reinstall/uninstall | PASS | §6 executed |
| Paths with spaces / non-ASCII | PASS | §7 executed |
| No admin/elevation required | PASS | §5/§7 (standard-user processes only) |
| Display scaling / larger text | **NOT TESTED** | physical-display check [M] |
| Reduced-motion setting | **NOT TESTED** | interactive OS setting [M]; the a11y motion layer itself is test-covered (Stage 13) |
| Accessibility/keyboard navigation | PARTIAL | automated offscreen a11y/name tests pass; real keyboard session [M] |
| Windows 10 / other SKUs / clean VM | **BLOCKED** | no VM or second host available (exact blocker, remains pending) |
| Error logs for DLL/plugin failures | PASS | no file logs by design; smoke stderr empty; qwindows plugin closure validated |
| Secrets-scan over logs/reports | PASS (N/A-positive) | app writes no log files by design; scans clean (`qa/security_review.md` §3) |

Classification rule enforced: PASS means actually executed; anything
inferred from code is SOURCE-CLASS in the audit sections, never PASS in
this matrix.

## 9. Performance / memory baselines (same-machine, recorded)

No earlier stage ever defined a numeric bound for the "scan of golden
bundle ≤ N ms per app; memory ceilings" acceptance text
(documentation gap → owner note for Stage 16; see §13). Recorded
measurements (build host, fake transport, real parse/KB/analysis path;
finding generation verified — 5 findings standard, 6 with the honest
deep-scan unverified-condition note):

* **Engine scan, synthetic 60-app bundle:** standard — mean 0.13 ms/app,
  median 0.09, max 2.81; deep — mean 0.10, median 0.09, max 0.24
  (JSON/HTML/text export excluded; scan-service path only).
* **Packaged `--smoke` startup:** 624.5 / 612.0 / 619.9 ms (median
  619.9 ms) — the ≤ 4 s acceptance bound holds with ≈ 6.5× headroom
  (Stage 14 recorded 1012–1107 ms on the same measures; both well under).
* **Packaged `--smoke` peak working set:** 77.6 / 77.7 / 77.8 MiB
  (ctypes psapi `PeakWorkingSetSize`, polled during run; measured from
  a foreign spaced CWD).

## 10. Security-sensitive workflows (fake-backed suite, all green)

| Contract bullet | Evidence class | Live-test anchor (grep-verified) |
|---|---|---|
| ADB argv-only, no shell | code + tests | `test_commands_by_argument_list_with_serial` — 0 `shell=True` engine-wide |
| Spaced ADB/scrcpy paths kept whole | tests (NEW Stage 15) | `TestSpacedToolPaths` (client argv, mirroring spawn) |
| Missing ADB honest (`AdbNotAvailable`) | tests | 12 matching lines |
| Missing/invalidated scrcpy typed refusal | tests | `test_launch_without_validated_tool_is_typed_refusal` |
| Stale/ambiguous selection never retargets | tests | 31 matching lines |
| Root truthful-unknown (R-05) | tests | 115 matching lines |
| Cancellation ≠ success | tests | 202 matching lines |
| Late/foreign events cannot clobber | tests | 42 matching lines |
| Findings carry explicit unverified evidence | tests | 18 matching lines |
| Redaction by default (R-06/R-12) | tests | 48 matching lines |
| Cleartext forensics gate exact-phrase | tests | 60 matching lines |
| Destructive admin: confirmation + fresh validation (R-13) | tests | 156 matching lines |
| Demo mode zero live contact | tests | 183 matching lines |
| Shutdown leaves no mirror procs/workers | tests | 7 matching lines + Stage 12 page-shutdown suite |

No physical device was available; per stage policy nothing destructive
was attempted, and demo/wifi-cleartext/admin flows were validated in
their fake-driven harnesses only.

## 11. Docs consistency pass (Stage 15 roadmap scope)

Executed + test-locked (`TestDocumentationConsistency`): every
`STAGE_xx_IMPLEMENTATION_REPORT.md` referenced by the five tracker docs
exists (no ghost references); Stage 09–14 reports present and
substantial; ROADMAP Stage 15 acceptance language present; version
authority chain (`pyproject.toml` → quad → exe metadata → installer
output name) consistent and collision-name-free. `FEATURE_PARITY_MATRIX`
re-checked: Stage 15 is QA/tooling — **no requirement cells move**;
parity-row consistency is backed by the same suite covering all four
surfaces (§12).

## 12. Four-surface regression matrix (all green in every full-suite run)

| Surface | Test files (representative) | Test functions |
|---|---|---:|
| Legacy CLI compatibility | `test_legacy_module_structure.py`, `test_report_generator.py`, `test_known_defects.py` | 38 |
| Click CLI | `tests/integration/test_cli_click.py`, `test_services_scanning.py`, `test_permission_analysis.py` | 43 |
| Engine + services | `test_core_*`, `test_services_*`, `test_stage06/07/08_engine.py`, `test_jobs_*`, `test_tool_provisioning_urls.py` | 288 |
| TUI | `test_tui_app.py`, `test_tui_entry.py`, `test_tui_services_screens.py` | 13 |
| Desktop | `test_stage08_ui/09–13_desktop.py`, `test_device_workspace.py`, `test_inventory_ui.py`, `test_reports_ui.py`, `test_scan_screen.py` | 263 |
| Packaging & QA | `test_stage14_packaging.py`, `test_stage15_release_qa.py`, `test_import_architecture.py` | 100 |

(Function definitions; parametrized cases expand the collected 951.
Identical fixtures are shared across surfaces by the Stage 03+ parity
architecture — legacy facades delegate to the same engine services —
so each green full-suite run exercises all four surfaces against the
same fixtures.)

## 13. Defects, tests, gates (exact record)

**New tests:** `tests/unit/test_stage15_release_qa.py` — 20 cases
(18 passing, 2 honest privilege skips: file-symlink creation needs
dev-mode/privilege on this host — WinError 1314; the junction cases, the
real Windows vector, pass unprivileged). Changed: `packaging_windows/
staging.py` (D1), `packaging_windows/validation.py` (D2),
`tests/unit/test_stage14_packaging.py` (fixture realism). No assertion
was weakened, no xfail added, coverage thresholds untouched.

**Gate runs (all fresh processes; 951 = 933 baseline + 18 new):**

| # | Command | Result |
|---|---|---|
| G0 | `pytest tests -q` (pre-change baseline) | 933 passed, 169.67 s |
| G1 | `pytest tests -q -p no:cacheprovider` | **951 passed, 2 skipped**, 169.29 s |
| G2 | `pytest tests -q --cov` | 1 failed (see below), 950 passed, 2 skipped, 291.47 s |
| G2r | `pytest "…::test_poll_session_streams_snapshots_on_gui_thread" -q [--cov]` | passed 0.55 s / 2.15 s |
| G3 | `pytest tests -q --cov` | **951 passed, 2 skipped**, 295.37 s |
| G4–G6 | `pytest tests -q --cov` (flake-hunt, background) | **951 passed, 2 skipped** ×3 (294.10 / 285.94 / 297.00 s) |
| S1 | `ruff check .` | clean |
| S2 | `mypy` | **132 source files** clean |
| S3 | `compileall -q vscanner cli ui_terminal tests ui_desktop packaging_windows` | exit 0 |
| S4 | `python -m ui_desktop --smoke` | `DESKTOP_SMOKE_OK` |
| P1 | legacy parity slice (`test_legacy_module_structure.py` + `tests/integration`) | 57 passed |
| P2 | `tests/integration` (incl. Click CLI + syntax baseline) | 48 passed |
| B1 | real dist + staging revalidation under new rules | 64 files OK, pass |
| B2 | ISCC recompile → throwaway dir | byte-identical, cleaned up |

**Coverage (established config, unchanged from Stage 14):** G3-class run
TOTAL **74%**, 13,854 statements (`packaging_windows/` is deliberately
not in the measured source set — build tooling; its correctness is owned
by the now-100 packaging policy tests + the executed real-build
validations).

**Stage 07 export flake:** not observed in any of the seven full-suite
runs this stage.

**The one G2 failure — investigation record:** `test_stage12_desktop.py
:: TestMonitoringPage :: test_poll_session_streams_snapshots_on_gui_thread`
failed once under the first instrumented (coverage) run and never again:
the exact assertion text was not captured (that run's output was
collected through a truncating filter — recorded honestly). Standalone
runs (plain + instrumented) pass; the following five full instrumented
runs all pass (G3–G6). Both of this test's assertions are *real*
invariants since the Stage 13 fix (every snapshot delivery on the GUI
thread; fan-out count consistency) — the Stage 13 "timing coincidence"
class no longer exists in this test. Code audit of the delivery path:
monitoring snapshots are emitted by the JobManager worker thread through
`QtJobEventBridge`; page slots are QObject-affine (queued AutoConnection
→ GUI thread) and the test's plain-callable listener resolves its lane
against the hub owner (GUI thread), so a violation would be a genuine
A5 delivery-contract anomaly, not an artifact of the test. Because the
failure never reproduced (5 consecutive instrumented full runs), it is
recorded as an observed-once stability item with a monitoring note for
the Stage 16 gate runs — masked by nothing: no retry, no skip, no xfail.

## 14. Remaining risks and honest limits

* **Single-host evidence:** every runtime conclusion above was reached on
  this Windows 11 build host. Windows 10 and other SKUs are untested;
  clean-VM isolation is BLOCKED (no VM available) and stays pending.
* **Unsigned artifacts:** the exe and installer carry no signature; no
  SmartScreen/MOTW reputation claim is made; first-run SmartScreen
  warnings on other machines are expected behavior until Stage 16
  decides on a certificate.
* **[M] items:** interactive uninstall; doctor click-through and full
  page navigation inside the packaged exe; HiDPI/larger-text;
  reduced-motion; keyboard session. None can be honestly automated with
  the available environment.
* **Device-facing surfaces:** validated fake-backed; no real device this
  stage (as Stage 14).
* **Supply-chain gaps:** dependency ranges are not exact pins (no
  lockfile); CI-runner reproducibility and artifact attestation do not
  exist. Both are Stage 16/owner follow-ups (`qa/security_review.md` §8).

## 15. Git record (to be finalized at commit time)

* Implementation commit: `test(release): harden security and
  compatibility validation` — `packaging_windows/staging.py`,
  `packaging_windows/validation.py`, `tests/unit/test_stage15_release_qa.py`,
  `tests/unit/test_stage14_packaging.py` (fixture fix).
* Documentation commit: `docs(progress): record Stage 15 completion` —
  `docs/vscanner-3/` (PROGRESS, ROADMAP, ACCEPTANCE_CRITERIA,
  TESTING_STRATEGY, FEATURE_PARITY_MATRIX, STAGE_15 report,
  `qa/security_review.md`, `RELEASE_NOTES_DRAFT.md`).
* Followed by an HTTPS-only `git push origin main` + fetch/verify
  (local == origin, both commits remote, user items untouched).
