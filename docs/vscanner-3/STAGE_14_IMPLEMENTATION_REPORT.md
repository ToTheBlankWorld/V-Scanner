# Stage 14 Implementation Report — Windows executable and installer

Branch `main`, baseline `93e623a` (Stage 13 completion, pushed and verified).
This stage delivered the approved **T-05 packaging strategy**: a **Nuitka
standalone** Windows executable (`V-Scanner.exe`, real desktop GUI, no
console window) plus a per-user **Inno Setup 6** installer/uninstaller
(`V-Scanner-3.0.0a0-Setup.exe`). No application feature changed; no Android
code was touched; the packaging tooling lives in `packaging_windows/` at the
repository root and never ships inside the application.

---

## 1. Why standalone + Inno Setup (T-05 restated and kept)

Stage 01's roadmap pre-decision (T-05) fixed the mode: **Nuitka
standalone → Inno Setup**. Alternatives considered once more at execution
time and rejected: PyInstaller (one-file extraction to temp is fragile
around our Qt plugin contract and gives weaker version metadata control),
MSIX (requires signing identity), MSB-based MSI (Windows Installer XML is
heavy, per-user semantics awkward). Inno Setup gives exact per-user,
non-admin semantics with a stable AppId, which the stage brief demands
(A-07 data conventions + non-destructive upgrade).

## 2. Toolchain — exact versions and how each was obtained

| Component | Version | Obtained (verified) |
|---|---|---|
| Python | 3.12.10 | already on the build host (MinGW64 requires Python < 3.13 — holds) |
| Nuitka | 4.3.1 | `pip install --user nuitka` |
| ordered-set | 4.1.0 | `pip install --user ordered-set` |
| zstandard | 0.25.0 | `pip install --user zstandard` |
| PySide6 | 6.12.0 | already present from the `[desktop]` extra |
| C compiler | winlibs MinGW64 **gcc 15.2.0** (r6, msvcrt) | downloaded by Nuitka itself into `%LOCALAPPDATA%\Nuitka\Nuitka\Cache\downloads\` via `--mingw64 --assume-yes-for-downloads` (first build only) |
| Inno Setup | **6.7.3** (ISCC.exe) | see below |

**Inno Setup sourcing fact (important):** the portable ZIP that older
stages' plans assumed is **no longer published** by jrsoftware —
`https://files.jrsoftware.org/is/6/` today carries only `.issig`
signature files, and the GitHub release for `is-6_7_3` ships only the
self-installer and its signature. The official, **digitally signed**
`innosetup-6.7.3.exe` was downloaded from the
`jrsoftware/issrc` GitHub release and its sha256 verified byte-for-byte
against the release-published digest
`9c73c3bae7ed48d44112a0f48e66742c00090bdb5bef71d9d3c056c66e97b732`
before execution. It installed **per-user, with no elevation and no
system changes**, accepting `/CURRENTUSER`:

```
innosetup-6.7.3.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP- /CURRENTUSER ^
    /DIR=%LOCALAPPDATA%\vscanner-build\inno\InnoSetup6-6.7.3
```

That location is auto-discovered by `build_windows.find_iscc()` (fallbacks:
`--iscc PATH`, `VSCANNER_INNO_SETUP`, standard `Inno Setup 6` dirs).
Recorded: ISCC.exe (1,422 KB, "Inno Setup Command-Line Compiler"),
unins000.exe ProductVersion 6.7.3.

## 3. The packaging package (`packaging_windows/`) — what each module does

| Module | Role |
|---|---|
| `versioning.py` | Parses `[project] version` from `pyproject.toml` (tomllib with a strict regex fallback); derives the numeric version and the **4-part quad**. |
| `staging.py` | Copies the release allowlist (`vscanner/**`, `ui_desktop/**` + the thin launcher) into a fresh staging tree under the work dir **outside the repository**. Excludes `ui_terminal`, `cli`, `tests`, `android`, `pyproject.toml`, caches, secrets, binaries. |
| `validation.py` | Validates the staged tree and the compiled dist: executable exists and is a real PE (`MZ` header), PySide6 bindings dir present, required runtime DLL closure (`python3*.dll`, `Qt6Core/Gui/Widgets.dll`, `qwindows.dll` platform plugin), forbidden content never staged/exe-side, and a whole-process clean-environment smoke launch. |
| `build_windows.py` | CLI orchestration: preflight → stage → Nuitka → validate → smoke → installer, each step failing early with the actual path in the message; everything build-owned lives in `%LOCALAPPDATA%\vscanner-build\work`. |
| `icon.py` | Regenerates `assets/vscanner.ico` via PySide6 (`QPainter` on `QImage`, PNG payloads, 7 entries 16–256 px). The committed icon is 15,420 bytes and parse-validated. |
| `vscanner_desktop.py` | The exe main module: imports **only** `sys` and `ui_desktop.app.main` and calls it (locked by tests — no test hooks, no second entry point, no special-case paths). |
| `installer.iss` | Inno Setup script (below). |

`pyproject.toml` is the single version authority (`3.0.0a0`, lockstep-
tested with `ui_desktop.APP_VERSION` since Stage 09). The build reads it at
build time; nothing in `packaging_windows/` hardcodes a version.

## 4. Version chain and the 4-part resource version

Observed ISCC error during the first compile:

```
Error on line 46: Value of [Setup] section directive "VersionInfoVersion" is invalid.
```

Root cause: Inno's `VersionInfoVersion` requires a four-part numeric value;
`3.0.0` is rejected, `3.0.0.0` compiles. `versioning.derive_version_quad()`
was added (`3.0.0a0 → 3.0.0.0`, `2.3 → 2.3.0.0`) and the quad is used
everywhere a numeric VERSIONINFO value is needed:

* Nuitka `--product-version` / `--file-version` → exe metadata shows
  FileVersion/ProductVersion **3.0.0.0** (verified by reading `VersionInfo`
  of the built exe below);
* Inno `/DVSCANNER_RESOURCE_VERSION=` → `VersionInfoVersion` and
  `VersionInfoProductVersion`.

`AppVersion` / `AppVerName` / `OutputBaseFilename` keep the verbatim
`3.0.0a0` (prerelease suffix visible to humans and to upgrade logic).

## 5. The ISPP define-name collision (root-caused, then locked by tests)

The first ISCC invocation defined `/DPRODUCT_VERSION=3.0.0.0`. Despite the
`#ifndef PRODUCT_VERSION` guard and `#error` gate passing, the compile
failed at `VersionInfoVersion` with the error above. A three-step minimal
diagnosis (all verified live against ISCC 6.7.3):

1. Literal `VersionInfoVersion=3.0.0.0` → **compiles clean**.
2. `VersionInfoVersion={#PRODUCT_VERSION}` with the same `/D` values →
   **fails with exactly the stage error** (also with quotes, also with a
   3-part value released) → the define is the variable, not the value.
3. Diagnostic that forces the define into the output filename:
   `OutputBaseFilename=dbg-{#PRODUCT_VERSION}-{#VERSION}` produced
   `dbg-ProductVersion-3.0.0a0.exe` — `{#PRODUCT_VERSION}` silently
   expanded to the **text `ProductVersion`**, i.e. it collided with an
   ISPP built-in name instead of seeing our define, while `/DVERSION`
   expanded correctly. Underscore-only names verify fine
   (`/DMY_NAME=alphanum` → `dbg-A-alphanum-B-plain.exe`).

**Fix:** every define renamed to the prefixed `VSCANNER_*` scheme —
`VSCANNER_VERSION`, `VSCANNER_RESOURCE_VERSION`, `VSCANNER_STAGE_DIR`,
`VSCANNER_OUT_DIR`, `VSCANNER_REPO_ROOT` (all with `#ifndef` guards and
`{#...}` references). The renamed scheme compiles clean. The ISS contract
tests now assert the new names, and a dedicated test
(`test_defines_avoid_ispp_collision_names`) forbids `{#PRODUCT_VERSION}` /
`{#StageDir}` / `{#RepoRoot}` from returning.

## 6. Real artifact build (executed)

Two full `python -m packaging_windows.build_windows` runs were executed
(the first before the ISCC define fix — it proved the standalone side and
reproduced the define failure; the final one after all fixes), plus a
final `--steps installer` run after the uninstall-quiet fix. Final facts:

* **Staging:** 64 files (`vscanner` 39, `ui_desktop` 24 + 1 launcher).
  `pyproject.toml` is deliberately not staged; `ui_terminal`/`cli`/`tests`
  are never staged.
* **Nuitka compile flags (recorded from the log):** `--mode=standalone
  --assume-yes-for-downloads --mingw64 --enable-plugins=pyside6
  --include-package=vscanner --include-package=ui_desktop
  --nofollow-import-to=ui_terminal --nofollow-import-to=tests
  --nofollow-import-to=cli --nofollow-import-to=android
  --windows-console-mode=disable
  --windows-icon-from-ico=<icon> --company-name=ToTheBlankWorld
  --product-name=V-Scanner --product-version=3.0.0.0
  --file-version=3.0.0.0 --file-description="V-Scanner - Android security
  auditing" --output-dir=<work>\nuitka --output-folder-name=V-Scanner
  --output-filename=V-Scanner.exe <stage>\vscanner_desktop.py`.
* **The compile runs from the STAGED tree** (cwd = stage dir), never the
  repo, so repository-local caches/path tricks cannot leak in.
* **Dist:** `V-Scanner.dist` — 64 files, 88,231,752 bytes (84.1 MiB);
  `V-Scanner.exe` 17,127,936 bytes,
  sha256 `1bf3eb42fa0fb5007e8c8b8f4b6c54db9cb76a4fcb7569cdabd1ebae2b27c637`;
  PySide6 sub-tree 23 files; `qwindows.dll` platform plugin present;
  FileVersion=`3.0.0.0`, ProductVersion=`3.0.0.0`,
  CompanyName=`ToTheBlankWorld`, ProductName=`V-Scanner`,
  FileDescription=`V-Scanner - Android security auditing` (all read
  from the binary's `VersionInfo`).
* **Exe smoke 1** (dist exe): launched from
  `%LOCALAPPDATA%\vscanner-build\run dir with spaces` (a path with spaces,
  outside the repo) → exit 0 with stdout **`DESKTOP_SMOKE_OK`** (the
  console-disabled exe still writes its harness marker to stdout when
  stdout is captured).
* **Startup timing** (ROADMAP acceptance): the dist exe `--smoke` wall
  time measured **1107 / 1012 / 1022 ms** over three runs (that includes
  full GUI construction + harness exit; cold-start acceptance bound is
  ≤ 4 s — met with ~4× headroom).

## 7. Installer build and its recorded facts

`V-Scanner-3.0.0a0-Setup.exe` — 25,010,550 bytes, sha256
`ac9229aedb574ec052686779b864fb95d592b218133365f7b93bb2245dae25bc`
(final script incl. the `UninstallSilent()` guard; the pre-guard build
differed: 25,010,529 bytes, `e18a75579d40adc2f63116949c734b4425a8306fea5f2f98a392a4a1564f2378`).
ISCC compile log: clean, uses lzma2/max + solid compression.

Installer semantics implemented (all asserted by ISS contract tests):

* `PrivilegesRequired=lowest`, `DefaultDirName={localappdata}\Programs\V-Scanner`
  — per-user, never elevation.
* Stable `AppId={{1AB0A622-DB19-4B71-88B9-1988011A281A}` (literal-brace
  GUID idiom).
* Start-menu shortcut always (`V-Scanner`, `WorkingDir: {app}`), an
  **unchecked-by-default** desktop-icon task, plus `Uninstall V-Scanner`.
* Version directives from defines only (no literals in the script — test
  enforced).
* `[UninstallDelete]` intentionally empty; the registry is touched with
  nothing beyond Inno's own uninstall bookkeeping; nothing is downloaded,
  no shell download hooks exist (test-enforced), no device operations at
  any install phase.
* `[Code]` uninstall user-data question (below).

## 8. Install → launch → uninstall smoke (executed against this machine)

Executed end-to-end on Windows with the final artifacts:

1. **Baseline** recorded: install dir, Start-menu folder and uninstall
   registry key all absent; `%LOCALAPPDATA%\vscanner` empty.
2. **Install:** `Setup.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART` →
   exit 0; 66 files at `%LOCALAPPDATA%\Programs\V-Scanner`
   (64 dist files + `unins000.exe`/`unins000.dat`); Start menu has
   `V-Scanner.lnk` + `Uninstall V-Scanner.lnk`; uninstall registry key
   created at exactly
   `HKCU\...\Uninstall\{1AB0A622-DB19-4B71-88B9-1988011A281A}_is1`
   (this confirms the literal-brace AppId semantics) with
   `DisplayName=V-Scanner`, `DisplayVersion=3.0.0a0`,
   `Publisher=ToTheBlankWorld`, `UninstallString=` the `unins000.exe` path.
3. **Launch (Start-menu-equivalent):** the *installed* exe executed with
   `--smoke` from `WorkingDirectory=C:\` — i.e. neither the app dir nor
   the repo — exit 0, stdout `DESKTOP_SMOKE_OK`. CWD independence and
   path-with-spaces safety are therefore both proven on the installed
   artifact, not just the dist.
4. **Uninstall (the documented Add/Remove Programs path):**
   `unins000.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /LOG=` →
   log records `Uninstallation process succeeded`, `Removed all? Yes`,
   `Need to restart Windows? No`; afterwards install dir, both Start-menu
   shortcuts and the registry key are gone; a planted user-data marker
   under `%LOCALAPPDATA%\vscanner` **survived** (retention verified
   empirically, not by code reading).

### 8.1 Root cause found during the uninstall smoke (and the fix)

The first uninstall attempt seemed to do nothing. Diagnosis: the
`MsgBox` written in `[Code]` (the optional user-data deletion question,
default *No/retain*) is **displayed even when the uninstaller runs
`/VERYSILENT`** — confirmed against the Inno Setup installer sources
(`Uninstall.pas`/`Setup.Uninstall.pas`) and the official docs entry for
`UninstallSilent()` ("Returns True if Uninstall is running silently").
Not suppressed, the hidden-but-modal prompt blocked the quietly-running
second uninstall phase; the process had to be killed and the machine
left half-cleaned (removed manually — recorded here for honesty).

**Fix shipped in the final installer:** `CurUninstallStepChanged` now asks
`UninstallSilent()` first and skips the prompt in silent runs, **taking
the safe default (retain user data)** and logging that fact; interactive
uninstalls keep the exact prior prompt with `MB_DEFBUTTON2` (retain) as
the default answer and `DelTree` only reachable behind the explicit
"Yes". A dedicated ISS contract test locks the guard.

### 8.2 Honest note on `Setup.exe /UNINSTALL`

The alternative invocation `Setup.exe /UNINSTALL /VERYSILENT ...`
returned exit 0 but performed **no removal on this machine** (both before
and after the guard fix). The verified uninstall path is therefore the
one every real uninstall flow uses: the `unins000.exe` `UninstallString`
from the registry (what Add/Remove Programs and our Start-menu shortcut
execute). Recorded as an observed Inno 6.7.3 behavior on this host; not
worked around with registry trickery (R-10 spirit: keep the package
boring and standard).

## 9. [D] Record: bundled-tools variant and code signing

* **Bundled ADB/scrcpy variant: NOT bundled (decision confirmed).**
  Per T-05 and the provisioning-service design already delivered, ADB and
  scrcpy are downloaded by the app's own provisioning flow into
  `%LOCALAPPDATA%\vscanner\tools` when the user chooses to provision
  (stage 06/07 behavior, unchanged). The dist was checked to contain no
  ADB/scrcpy binaries and the launcher's missing-tool diagnostics stay
  honest (the app refuses with actionable guidance instead of pretending).
* **Code signing: unsigned (decision recorded).** No certificate is
  configured; both exe and installer are unattributed to SmartScreen
  (first-run warnings on other machines are expected until a cert exists).
  This is stated here, in `README` "Signing status", and in the acceptance
  deviation; buying/purchasing and wiring an OV/EV cert remains a real
  release item for Stage 16, not something this stage can claim.

## 10. Tests added (`tests/unit/test_stage14_packaging.py`, 69 tests)

All toolchain-free (no Nuitka/ISCC needed to run the suite): for
`versioning` (parse/numeric/quad incl. rejection cases), `staging`
(allowlist-only, forbidden-content never staged, non-destructive fresh
reset, dirs-vs-files sets), `validation` (PE header check, PySide6-dir
check ordering — the fundamental error is reported first, DLL closure
missing-matching errors, launcher purity), `build_windows` (work-dir
outside-repo guard, missing-node fails, quad in preflight, '--steps'
filtering, compile_installer argument contract, ISCC-missing guidance, the
exact Nuitka flag list incl. quad number and icon path), `icon` (7 sizes,
parse of committed bytes), `vscanner_desktop` (exact locked contents and
imports), and the `TestInstallerScript` ISS contract class (AppId shape,
`VSCANNER_*` defines without literals, collision-name guard, per-user
semantics, publisher, unchecked desktop task, single source = stage dir,
uninstall default retain + `MB_DEFBUTTON2` + silent-skip guard).

## 11. Quality gates — exact commands and observed results

* `python -m pytest tests -q` — **933 passed, 0 failed, 0 xfailed,
  0 skipped** ×2 consecutive fresh processes (166.95 s / 167.11 s).
* Coverage run (`--cov=vscanner --cov=ui_terminal --cov=ui_desktop
  --cov=cli`): 933 passed; **TOTAL 74%** (13,854 statements) — unchanged
  from Stage 12's re-measure because packaging tooling is not part of the
  measured source set (see TESTING_STRATEGY §6 note).
* `python -m ruff check .` — all checks passed.
* `python -m mypy` — Success: no issues found in **131** source files
  (`packaging_windows` added to the mypy `files` list this stage; two
  PySide6-stub mismatches in `icon.py` are silenced with scoped
  `# type: ignore[call-overload]` comments above the verified-runtime
  calls).
* `python -m compileall …` — exit 0 (all packages incl. `packaging_windows`).
* `python -m ui_desktop --smoke` — `DESKTOP_SMOKE_OK` (source tree sanity
  unchanged; the **packaged** exe was smoke-verified separately, §6/§8).

## 12. Files changed (complete list; staged diff inspected)

New:
* `packaging_windows/__init__.py` (AppId GUID + `EXECUTABLE_NAME` + docstring)
* `packaging_windows/versioning.py`, `staging.py`, `validation.py`,
  `build_windows.py`, `icon.py`, `vscanner_desktop.py`
* `packaging_windows/installer.iss`
* `packaging_windows/README.md` (operator-facing build guide)
* `packaging_windows/assets/vscanner.ico` (generated, committed)
* `tests/unit/test_stage14_packaging.py`

Modified:
* `pyproject.toml` — mypy `files` list addition for
  `packaging_windows` (version unchanged: still `3.0.0a0` authority;
  the wheel `packages`/`source` lists intentionally stay without it —
  packaging tooling is not shipped application code).
* Docs (second commit): `ROADMAP.md`, `ACCEPTANCE_CRITERIA.md`,
  `TESTING_STRATEGY.md`, `PROGRESS.md`, `FEATURE_PARITY_MATRIX.md`, and
  this file.

## 13. [M] / [UNVERIFIED] limitations carried forward (honest)

* **Clean Windows VM matrix not executed** — the install/upgrade/uninstall
  smoke ran on this build host only. A clean-VM (Windows 10 + Windows 11)
  pass incl. the upgrade-over-previous-version case stays [M] for QA
  stages (15/16 REQUIRES it anyway).
* **CI reproducibility not demonstrated** — the repo has **no `.github/`
  CI infrastructure**; "reproducible on CI Windows runner" cannot be
  honestly claimed. What was proven instead: build reproducibility from a
  clean staging tree with declared inputs (allowlist + version authority +
  frozen flags), all recorded. Acceptance deviation noted in
  ACCEPTANCE_CRITERIA.
* **Doctor page inside the packaged exe: not exercised interactively** —
  the desktop has a live `doctor` section and its service layer is
  suite-tested at 100%-fixture level, and the packaged `--smoke` proves
  the whole desktop closure boots; but a human click-through of the
  doctor page inside the *installed* app remains manual ([M] for QA).
* **Real-GPU/HiDPI window behavior on physical displays** — offscreen
  harness only; unchanged [M] from Stages 09–13.
* **SmartScreen/AV reputation on new machines** — expected to flag the
  unsigned artifacts; a manual download-and-run test on an outside
  machine is [M].
* **`Setup.exe /UNINSTALL` quirk** (§8.2) — recorded, not root-caused
  into Inno internals beyond the source-reading above; the verified ARP
  path is unaffected.

## 14. Git record

* Commit 1: `build(windows): add standalone app and installer` —
  `packaging_windows/**`, `tests/unit/test_stage14_packaging.py`,
  `pyproject.toml` (mypy lists only).
* Commit 2: `docs(progress): record Stage 14 completion`.
* Pushed to `origin/main` (HTTPS); verified by fetch + rev-parse equality.
* The pre-existing unrelated working-tree items (modified `.gitignore`,
  untracked `cli/python usb_charging_control.py`) were never staged, as
  required.
