# V-Scanner 3.0 — QA security review (Stage 15)

**Date:** 2026-10-22 · **Scope:** Windows release (packaged standalone
`V-Scanner.exe` + Inno Setup installer, Stage 14 artifacts) ·
**Reviewer:** Stage 15 QA automation (same build host)
**Baseline:** `07a83bf` (Stage 14 docs head)

Status legend used throughout: EXECUTED (actually run on the Stage 15 build
host), SOURCE-LEVEL (code reading, no execution), [M] remaining manual
verification.

---

## 1. Verdict

**Two reproducible defects were found and fixed in Stage 15 scope
(D1, D2 below); no other reproducible security defect was found.**
Every audit area below carries the evidence class it was evaluated with
(executed vs source-level), and every remaining risk has an owner or an
explicit [M] follow-up. Findings are classified against
`SECURITY_AND_REMEDIATION_PLAN.md` (R-numbering continues there for
cross-stage retirements; D-numbers are Stage 15-local fix records).

## 2. Findings

### D1 (FIXED, HIGH) — Release staging silently followed links

* **Severity:** HIGH (privilege of the finding: silent inclusion of
  foreign, possibly secret material into a release artifact).
* **Original behavior:** `packaging_windows/staging.py` copied the release
  allowlist with `shutil.copytree(symlinks=False)` (the `copytree` default).
  In that mode each symlink/junction inside a staged package tree is
  *followed* and its **target's content is materialized as a regular file**
  in the release tree. A link planted in `vscanner/` or `ui_desktop/`
  (e.g. an NTFS junction pointing at a machine-local directory) therefore
  smuggled that content past the entire allowlist + forbidden-pattern
  policy, and Nuitka would compile it into the shipped binary.
* **Reproduction (executed, pre-fix `07a83bf`):** synthetic repo fixture +
  real NTFS junction created unprivileged via `cmd /c mklink /J` pointing
  at an outside directory holding `MACHINE_SECRET`; the original
  `stage_release_tree` copied **5 files** and the staged tree contained
  `vscanner/core/vendor_link/secret.txt` with content `'MACHINE_SECRET'`
  (probe output recorded in `STAGE_15_IMPLEMENTATION_REPORT.md` §5).
* **Fix:** staging now refuses links at the source with a `ValueError`
  naming the offending path: new `first_link_entry(source_root)` walks each
  staged package tree (and the thin launcher is checked to be a regular
  file) using `_is_link()` — `Path.is_symlink()` plus NTFS-junction-aware
  `Path.is_junction()` when the interpreter provides it (Python ≥ 3.12;
  the 3.10/3.11 project floor sees symlinks only, which is the exact
  runtime behavior those versions have). Copy-escape in the reverse
  direction was re-verified by construction: staging destinations are
  built from the *real* tree's relative parts, so no relative path can
  leave the staging root; the link rule closes the remaining
  follow-the-link direction.
* **Regression tests:** `tests/unit/test_stage15_release_qa.py`
  (`TestStagingLinkPolicy`) — real-junction case (unprivileged on Windows)
  asserts refusal and that no foreign filename ever reaches the stage;
  symlink-detector positive/negative cases (symlink creation skips
  honestly when the OS requires privilege — WinError 1314 on this host);
  launcher-link refusal; plain-tree pass-through.
* **Impact:** a distribution can no longer silently carry content that the
  allowlist policy says it cannot contain.

### D2 (FIXED, MEDIUM) — Dist validation accepted unexpected executables / stray Python files

* **Severity:** MEDIUM (an unexpected `.exe` in a shipped folder is a
  classic supply-chain/lurking-binary risk; the old validator only checked
  *presence* of the required closure, never exclusivity).
* **Original behavior:** `packaging_windows/validation.py`
  `validate_distribution` verified required files but imposed no
  "exactly one executable" or "no Python source/bytecode in the dist"
  rule; an extra `nested.exe` or a stray `.py`/`.pyc` in the dist passed
  validation unchallenged.
* **Reproduction:** unit level — `TestDistributionContentPolicy::
  test_extra_executable_is_rejected` documents the pre-fix acceptance
  (a dist containing `mystery.exe` passed the old validator; recorded as
  code-inspection evidence of the absent rule, not an executed pre-fix
  run against the real artifact: no real release artifact of ours ever
  contained an extra exe — the 64-file dist audit below is clean).
* **Fix:** the validator now rejects (a) any `.exe` other than the single
  expected `V-Scanner.exe`, and (b) any `.py`/`.pyc`/`.pyo` inside the
  dist (a Nuitka standalone build is a compiled closure; stray Python
  files indicate a staging or packaging fault). Fixing this rule exposed a
  stale Stage 14 *fixture* (the `_fake_dist` helper modeled
  `PySide6/__init__.py`, while the real dist contains **zero** `.py`
  files — verified against the actual 64-file dist); the fixture was
  corrected to `PySide6/__init__.pyd`, and the full Stage 14 packaging
  suite still passes.
* **Regression tests:** `TestDistributionContentPolicy` (minimal valid
  dist passes; extra exe rejected by name; stray `.py` rejected; stray
  `.pyc` rejected) + real-dist revalidation executed (below).

### Reviewed, judged not-a-defect (with rationale)

| Area | Observation | Rationale for no fix |
|---|---|---|
| Report export destination | `ReportService.export` writes to a caller-chosen directory honored verbatim | The destination is a user-declared save location (same trust level as the user; equivalent to a Save-As dialog). Engine-*managed* stores (case store, extraction destinations, tool staging) are traversal-guarded (`forensics.py` rejects path-traversal components; `_extraction.py` R-11). |
| `build_windows.find_iscc` | Locates `ISCC.exe` via a sanctioned search order | Operator-machine tool discovery; explicit path/provenance guidance recorded; never shipped into artifacts. |
| `iscc.log` build log | Contains build-machine paths (Inno's own input-file diagnostics) | The log is build-owned state under `%LOCALAPPDATA%\vscanner-build\`, never committed, never shipped; the packaged *binaries* themselves were string-scanned path-clean (see §6). |

## 3. Secrets in logs, reports and outputs (AC item)

**App behavior (source-level + executed):** the engine and desktop build
no file-based logs — job logs are in-memory typed event contexts
(`vscanner/services/orchestration.py` `context.log(...)` into job events;
`logging.Logger` use is job-scoped and console-bound, and the packaged
GUI app attaches no handler). There is no default log file to scan; this
is the "no secrets in logs" asset by construction.

Scans executed this stage (pattern set:
`api[_-]?key`, `apikey`, `token=`, `api-secret`, `BEGIN RSA PRIVATE`,
`BEGIN PRIVATE`, `password`):

| Surface | Method | Result |
|---|---|---|
| Packaged `V-Scanner.exe` (17,127,936 B) | Latin-1 full-text decode + pattern search | `api_key` hit is the R-06 redaction **pattern-name tuple** (`api_key/password/secret/token/aws_key/firebase` registered names) — data, not a key. `token=` hits are stdlib `shlex` module strings. **No secret material.** |
| `%LOCALAPPDATA%\vscanner` user data | filesystem scan after full lifecycle testing | **0 files** (the app writes nothing unless a feature is used; the Stage 15 lifecycle marker was cleaned up after the retention proof). |
| `iscc.log` (build log) | 133 lines, pattern scan | **0 secret-pattern hits**; the only machine-specific content is Inno's own input-path diagnostics (never shipped, never committed — see §2). |
| Suite-produced report files | 88 leftover `security_report_*` under pytest temp roots across suite runs, 30 sampled | **0 hits**; all content is synthetic fixtures (com.example.wallet et al.). |
| Session odd-path exports | HTML/JSON/TEXT written into a spaced non-ASCII temp dir during the §7 check | Synthetic content (scan fixture), cleaned up afterwards. |

## 4. Device-facing / external-tool safety (§6 map)

Every contract below is enforced by live tests (no fake-only reasoning):
argument-vector discipline R-10 (argv, never a shell string; the ADB path
containing spaces is proven whole at the `build_adb_command`, client-argv
and mirroring-spawn seams — new Stage 15 tests), missing-ADB honesty
(`AdbNotAvailable`, never a fabricated device), stale/ambiguous selection
guards, root truthful-unknown (R-05 tri-state), cancellation never
reported as success, late/foreign events cannot clobber another device's
or session's results, unverified findings carry explicit
`UNVERIFIED_CONDITION` evidence, secret values redacted by default
(R-06/R-12), cleartext PSK forensics behind the exact typed
acknowledgement, destructive administration behind operation-specific
confirmation + freshly validated target (R-13), demo mode with zero live
contact, and mirroring processes tracked and terminated at page shutdown.
Keyword-density references: cancel 202, demo 183, admin confirm 156,
root 115, spaced paths 142, redaction 48, cleartext 60, late/foreign 42,
stale 31, unverified 18, missing-ADB 12, mirror-shutdown 7 matching test
lines (see `STAGE_15_IMPLEMENTATION_REPORT.md` §6 for the pass/fail
table). No physical test device was available this stage; all
device-adjacent validation remains fake-backed by design.

## 5. Installer & lifecycle findings (executed, same host)

* Per-user install (`{localappdata}\Programs\V-Scanner`), no elevation, no
  service, no scheduled task, no Run-key entry (HKCU/HKLM enumerated after
  install: 0/0/0). Shortcuts correct; registry entry carries
  `DisplayName=V-Scanner`, `DisplayVersion=3.0.0a0`.
* Fresh install → launch (`DESKTOP_SMOKE_OK`) → **reinstall over the
  existing install** → file inventory unchanged except the Inno
  uninstaller bookkeeping pair (`unins000.dat/.exe`, regenerated by
  design); a planted user-data marker survived both the reinstall and the
  uninstall; ARP-path silent uninstall (`unins000.exe /VERYSILENT /LOG=`)
  removed the app dir, both shortcuts and the registry key, retained user
  data, and completed in seconds with no hidden modal (log: `Removed all?
  Yes`, `Need to restart Windows? No`).
* `Setup.exe /UNINSTALL` no-op quirk recorded at Stage 14 stands as an
  observation (not re-executed this stage; the shipped/ARP path is the
  `UninstallString` implementation).
* Interactive (GUI) uninstall and doctor-page click-through inside the
  packaged exe remain **[M] NOT TESTED** (human-GUI steps).

## 6. Supply chain / signing (§9)

* **Artifacts are unsigned.** No signing certificate exists on this host;
  no publisher identity, no SmartScreen-reputation claim, no
  warning-bypass is made anywhere. Cert acquisition stays a Stage 16
  decision.
* **Provenance:** PySide6 6.12.0, Nuitka 4.3.1 (pip, user site), winlibs
  MinGW64 gcc 15.2.0 (fetched by Nuitka into its user cache at Stage 14),
  Inno Setup 6.7.3 installed per-user only after the release-published
  sha256 `9c73c3ba…97b732` was verified (recorded Stage 14). Downloaded
  tools live under `%LOCALAPPDATA%\vscanner-build\` and are never
  committed; the repo carries no vendored binaries.
* **Pinning state (honest):** runtime dependencies are floor-pinned
  *ranges*, not exact pins (`rich>=13.0.0`, `click>=8.0.0`,
  `textual>=8.2.8,<9`, `PySide6>=6.12,<7`). No lockfile exists. Recorded
  as a documented gap: full dependency pinning/lockfile remains an owner
  follows-up task for Stage 16 release finalization (does not gate the
  Stage 15 audit, whose artifacts were built from recorded exact versions
  — see the build record).
* **Network endpoints:** a full-text scan of the packaged exe lists 40
  URL literals; the only functional endpoints are the documented
  provisioning sources (`dl.google.com` platform-tools zips and
  `api.github.com`/`github.com` scrcpy releases) that run **only on
  explicit user provisioning action**. The rest are stdlib/spec citation
  strings (iana, w3c, rfc, python docs, packaging PEPs, Nuitka info URL).
  No telemetry.
* **Reproducibility:** observed — recompiling `installer.iss` from the
  byte-identical dist with the recorded ISCC 6.7.3 produced a
  bit-identical installer (sha256 equal to the Stage 14 record), i.e.
  deterministic same-machine output for identical inputs. **Not claimed:**
  clean-runner reproducibility or artifact attestation (no CI runner
  exists in the repo; recorded as the Stage 14 [M] follow-up).

## 7. Compatibility envelope

Executed only on the Stage 15 build host (Windows 11 Pro build 26200
x64). Windows 10 and other Windows 11 SKUs are **untested**; a clean-VM
isolation matrix was not available and was not invented. Startup bound
≤ 4 s held (median 619.9 ms re-measured). The full honest matrix with
PASS/PARTIAL/NOT TESTED statuses is in
`STAGE_15_IMPLEMENTATION_REPORT.md` §8.

## 8. Owner register (unsolved / follow-up items)

| Item | Class | Owner | Stage |
|---|---|---|---|
| Code signing certificate decision | release | project | 16 |
| Clean-VM install/upgrade matrix + Windows 10 checks | verification | project (needs VM host) | 16 |
| Interactive uninstaller + doctor click-through inside the packaged exe | verification [M] | project (manual) | 16 |
| Exact-pin dependency lockfile | hardening | project | 16 |
| Numeric performance budget definition (scan ≤ N ms/app, memory ceiling) | baseline | project | 16 |
| Monitoring snapshot test (1-in-6 under-load instrumented flake) monitoring note | test stability | QA at Stage 16 gates | 16 |
| CI runner (reproducible-build evidence) | release infra | project | beyond 16 |
