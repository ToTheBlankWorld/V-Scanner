# V-Scanner Windows packaging (Stage 14)

Reproducible Windows distribution tooling for the V-Scanner 3.0 desktop
application (PySide6). Implements the approved T-05 strategy: **Nuitka
standalone compilation + Inno Setup installer**. Nothing in this directory
ships inside the application.

## Layout

| Path | Role |
| --- | --- |
| `build_windows.py` | Build orchestration CLI (preflight → stage → Nuitka → validate/smoke → installer). |
| `versioning.py` | Authoritative version parse from `pyproject.toml` + numeric Windows derivation. |
| `staging.py` | Release-policy allowlist stager (non-destructive). |
| `validation.py` | Staged-tree, distribution, icon, and clean-environment smoke launch validation. |
| `icon.py` | Regenerates the committed app icon (`assets/vscanner.ico`). |
| `vscanner_desktop.py` | The thin launcher compiled as the exe main module (delegates to `ui_desktop.app:main`). |
| `installer.iss` | Inno Setup script consuming the validated standalone distribution. |
| `assets/vscanner.ico` | Original generated application icon (7 sizes, PNG payloads). |

The build workspace (staging tree, compiler caches, logs, dist, installer,
smoke-run directory) lives **outside the repository** by default:
`%LOCALAPPDATA%\vscanner-build\work`. Generated binaries never enter Git.

## Prerequisites (worked facts, Stage 14)

* Windows x64 with Python **3.12.10** (project floor is 3.10; the build
  tooling itself prefers 3.11+ for `tomllib`, with a strict regex fallback).
* `pip install --user nuitka ordered-set zstandard` — recorded versions of
  the Stage 14 build: **Nuitka 4.3.1**, **ordered-set 4.1.0**,
  **zstandard 0.25.0** (+ PySide6 **6.12.0** from the desktop extra).
* The C compiler used is the **Nuitka-managed winlibs MinGW64** fetched into
  the Nuitka user cache on first build
  (`--mingw64 --assume-yes-for-downloads`; MinGW64 requires Python < 3.13
  which holds: 3.12.10).
* Inno Setup 6 compiler: the (formerly packaged) portable zip is no longer
  published; the official alternative is the **digitally signed**
  `innosetup-6.7.3.exe` from the jrsoftware GitHub release, whose sha256 is
  published there
  (`9c73c3bae7ed48d44112a0f48e66742c00090bdb5bef71d9d3c056c66e97b732`).
  It was installed **per-user, without admin**, with:

  ```
  innosetup-6.7.3.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP- /CURRENTUSER /DIR="%LOCALAPPDATA%\vscanner-build\inno\InnoSetup6-6.7.3"
  ```

  `build_windows.py --iscc` / `find_iscc` discovers that location
  automatically (`%LOCALAPPDATA%\vscanner-build\inno\**\ISCC.exe`), or a
  standard `Inno Setup 6` install dir, or `--iscc`/`VSCANNER_INNO_SETUP`.

## Commands

* **Regenerate the icon** (only needed if the icon changes):

  ```
  python -m packaging_windows.icon
  ```

* **Full build** (stage → Nuitka standalone → dist validation + smoke from
  a space-containing path outside the repo → installer compile):

  ```
  python -m packaging_windows.build_windows
  ```

  Step filtering is available via `--steps stage,nuitka,installer` and
  `--skip-smoke`; `--work-dir` and `--repo-root` may be overridden; `--iscc`
  points directly at ISCC.exe.

* **Run the tests** (toolchain-free policy tests):

  ```
  python -m pytest tests/unit/test_stage14_packaging.py -q
  ```

## What the distribution contains

* `V-Scanner.exe` (standalone Nuitka build; windowed, no console) plus all
  compiled `vscanner` + `ui_desktop` modules and their native closure
  (CPython runtime DLL, Qt 6 DLLs, the `qwindows.dll` platform plugin,
  PySide6 bindings).
* **No** ADB/scrcpy binaries (T-05: tools are user-provisioned into
  `%LOCALAPPDATA%\vscanner\tools` at runtime), no tests, no `.git`, no
  docs, no machine-local config (the legacy `adb_config.json` import
  no-ops when absent), no user data, no caches, no bytecode.

## Installer semantics

* Per-user, no administrator rights (`PrivilegesRequired=lowest`,
  default dir `{localappdata}\Programs\V-Scanner`).
* Start-menu shortcut always; desktop shortcut is an optional, unchecked
  task.
* Stable AppId GUID `1AB0A622-DB19-4B71-88B9-1988011A281A` — upgrades
  replace the application files; user data under
  `%LOCALAPPDATA%\vscanner` (settings/logs/history/cached tools) is never
  touched by upgrade.
* Uninstall removes the app files and shortcuts and **retains user data by
  default**; deletion is an explicit opt-in question (default = keep).
  Reports live wherever the user chose to save them and are never touched.
* Silent smoke procedure (documented, executed during Stage 14 validation):

  ```
  ISCC.exe /DVSCANNER_VERSION=... /DVSCANNER_RESOURCE_VERSION=... /DVSCANNER_STAGE_DIR=... /DVSCANNER_OUT_DIR=... /DVSCANNER_REPO_ROOT=... installer.iss
  V-Scanner-<version>-Setup.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART    (install)
  V-Scanner-<version>-Setup.exe /VERYSILENT /UNINSTALL                     (uninstall)
  ```

## Version sourcing

`pyproject.toml` `[project] version` is the single authority (lockstep-
tested with `ui_desktop.APP_VERSION`). The build reads it at build time
and injects:

* Nuitka `--product-version` / `--file-version`: the numeric derivation
  (`3.0.0a0` → `3.0.0`).
* Inno Setup `/DVSCANNER_VERSION=` (verbatim, e.g. `3.0.0a0` → `AppVersion`)
  and `/DVSCANNER_RESOURCE_VERSION=` (numeric quad → `VersionInfoVersion`).
  Define names carry the `VSCANNER_` prefix: `/DPRODUCT_VERSION` was
  root-caused during Stage 14 to collide with an ISPP built-in (its
  expansion silently rendered `ProductVersion`, which ISCC rejects as an
  invalid `VersionInfoVersion` value).

## Signing status

The executable and the installer are **unsigned** (no code-signing
certificate is configured). Distributing them will trigger SmartScreen and
publisher warnings; a certificate purchase and signing step is an explicit
outstanding item, documented in STAGE_14_IMPLEMENTATION_REPORT.
