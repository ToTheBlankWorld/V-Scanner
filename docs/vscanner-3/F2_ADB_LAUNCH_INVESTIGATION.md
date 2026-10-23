# F-2 Investigation — Packaged ADB Launch Failure (2026-10-23)

Resolution of checklist item #23 (finding F-2): the packaged/installed
application could not launch the configured ADB executable, reporting
`PermissionError: [WinError 5] Access is denied`, although the same path
worked when invoked from a shell.

## 1. Final status

**FIXED (at the engine launch layer) — root cause was an application defect,
not the packaging and not security software.** A code fix plus regression
tests landed in this repository; a new release-candidate build (new
artifacts, new hashes) was produced with the approved Nuitka + Inno Setup
pipeline and validated on the affected host with the real (defectively
saved) configuration. The historical Stage 14 artifacts are preserved
unchanged and are **not** the fixed build.

## 2. Reproduction (before the fix) — exact and deterministic

Input in the user's saved configuration (`%LOCALAPPDATA%\vscanner\config\config.json`,
field `adb_path`; the value is a platform-tools **directory**, redacted in
commits): a directory such as `…\<somewhere>\platform-tools` with `adb.exe`
directly inside it.

- Minimal standalone reproduction, same user account, no admin:

  ```python
  import subprocess
  subprocess.run([r"…\platform-tools", "version"])   # a directory as argv[0]
  # -> PermissionError: [WinError 5] Access is denied
  subprocess.run([r"…\platform-tools\adb.exe", "version"])  # rc = 0
  ```

- In the installed packaged app the *same* value produced the observed
  defects: the Device workspace banner `FAILING — discovery failed:
  PermissionError: [WinError 5] Access is denied` and the Dashboard check
  reporting `invalid — the saved path did not launch a working adb`.

## 3. Root cause chain (with evidence)

1. `ConfigService` stores `adb_path` as an honest raw string (validated on
   demand, not on load — by design, `config.py`).
2. The desktop backend hands that raw string to `ServiceRegistry`, which
   builds `SubprocessAdbClient(adb_path)`; the client launches
   `[self.adb_path, ...]` — argv-list spawn, correct (R-10).
3. The saved value is a **directory**. Windows `CreateProcess` refuses to
   *execute* a directory and raises `PermissionError`/`WinError 5`. This is
   deterministic OS behavior, reproduced standalone (§2) — not permissions,
   not antivirus, not packaging, not ADB.
4. `check_adb_valid` (the authoritative probe) caught *any* exception and
   returned `False` → the banner's honest "did not launch a working adb".
5. `SubprocessAdbClient.run_text/run_bytes` translated only
   `FileNotFoundError` to the typed `AdbNotAvailable`; the process-creation
   rejection escaped as a raw `PermissionError`, which is what reached the
   device-workspace banner verbatim.

The earlier readiness-recorded hypothesis ("host-environment-bound, e.g.
security agent") is **refuted**: the failure reproduces identically in a
minimal standalone script under the same user account, and the sibling
executable launches fine.

Notable context: the products' own provisioning code already encodes the
`platform-tools`/`adb.exe` layout convention when *it* computes the tool
path — the defect was specifically that arbitrary saved paths were launched
verbatim.

## 4. The fix (smallest safe correction, one choke point family)

`vscanner/services/adb/executable.py`:

- New authoritative `resolve_adb_launch_path(adb_path)`: a path that names
  an existing **directory** resolves to the platform adb executable name
  inside it (`adb.exe` on Windows, `adb` elsewhere); files and absent paths
  pass through unchanged, so every existing honest-failure behavior is
  preserved downstream. Still an *explicit* path from the user's own
  configuration — no PATH search, no shell, no downloads.
- `check_adb_valid` probes the resolved launch target (5 s timeout, rc-0
  contract unchanged).

`vscanner/services/adb/client.py`:

- `SubprocessAdbClient.__init__` launches the resolved target — the single
  choke point every engine ADB spawn flows through (discovery, device
  commands, byte-safe ops, monitoring probes). Serial-bound clients inherit
  it.
- `run_text`/`run_bytes` translate any process-creation `OSError` (beyond
  `FileNotFoundError`) into the typed `AdbNotAvailable` with the path and
  the OS refusal — truthful and actionable, never a raw `PermissionError`
  in a UI banner, and never a fake success.
- `build_adb_command` resolves argv[0] the same way (utility parity with
  the client).

Existing tests keep their shapes: `fake-adb.exe`-style file paths are
unchanged by the resolver (`resolve_semantics` locks the passthrough).

## 5. Regression tests (`tests/unit/test_services_adb.py`, class
`TestDirectoryShapedAdbPath`)

1. `test_resolve_semantics` — directory → `platform-tools\adb.exe`; file
   and absent paths pass through unchanged.
2. `test_validation_probe_resolves_directory_before_spawning` — the probe
   spawns the resolved executable path (argv recorded).
3. `test_validation_missing_executable_still_false` — a directory without
   `adb.exe`, an absent path, and an empty string all remain honest `False`.
4. `test_client_launches_the_resolved_executable_for_real` — REAL child
   process through a directory-shaped path (real executable copied beside
   the probe).
5. `test_spaced_and_non_ascii_directory_launches` — spaced + non-ASCII
   platform-tools directory name, real child process.
6. `test_directory_without_executable_failure_is_typed_not_raw` — the raw
   pre-fix behavior (real `CreateProcess` on the directory) now maps to the
   typed honest failure for text and byte lanes.
7. `test_permission_error_maps_to_typed_not_available` — a synthetic
   `PermissionError(5, "Access is denied")` becomes `AdbNotAvailable`.
8. `test_build_adb_command_resolves_directory` — the argv utility honors
   the resolution.

Focused run: **28 passed** in the file (8 new + 20 pre-existing).

## 6. Source-layer validation against the real configuration

Executed on the affected host, standard user, the genuine saved
configuration as-is: `check_adb_valid(<saved platform-tools directory>)` →
**True**; `SubprocessAdbClient(<saved directory>)` resolved to
`platform-tools\adb.exe` and its `run_text(["version"])` returned rc 0
version `36.0.2`. The exact user input that failed before now works. (No
device was attached during the source-layer validation; the only ADB
command issued was the version probe.)

## 7. Quality gates (exact)

- `pytest tests/unit/test_services_adb.py -q` → **28 passed** (0.51 s).
- `ruff check .` → exit 0, "All checks passed!".
- `mypy` → exit 0, "Success: no issues found in 134 source files".
- `compileall -q vscanner cli ui_terminal tests ui_desktop packaging_windows`
  → exit 0.
- Packaging suite (Stage 14 + 15) → 87 passed / 2 honest privilege skips.
- Stage 16 doc contract + lockfile tests → 22 passed.
- Full suite, fresh process, run 1 → **981 passed, 2 skipped**
  (0:02:47, exit 0).
- Full suite, fresh process, run 2 → 1 failed / 980 passed / 2 skipped —
  a pre-existing create-then-read race in the Stage 11 history-record test
  `test_full_device_scan_completes_with_engine_findings` (the reader sees
  the just-created, not-yet-flushed JSON file; all files involved —
  `vscanner/services/history.py`, `tests/unit/test_stage11_desktop.py` — are
  untouched by the F-2 diff, whose scope is the ADB spawn choke points this
  fake-backed test never executes). Evidence it is a suite-timing flake and
  not the fix: standalone 4/4 green, full-suite runs 1 and 3 green.
- Full suite, fresh process, run 3 → **981 passed, 2 skipped** (0:02:39,
  exit 0) — the gate's second green fresh-process run.
- Full suite + coverage → **981 passed, 2 skipped**, TOTAL 74%
  (0:04:48, exit 0) — threshold-identical to the Stage 16 record.

## 8. New release-candidate build (Section 6 artifact policy)

The fix lives in `vscanner/services/adb/*`, which Nuitka compiles into the
packaged binary → it directly affects the packaged executable, so a new
candidate was built with the approved pipeline
(`python -m packaging_windows.build_windows`, full `stage,nuitka,installer`
steps including its validated staging + dist validation + smoke) into a
**separate work directory** so the historical Stage 14 artifacts and their
work directory were not overwritten:

- Candidate work directory: `%LOCALAPPDATA%\vscanner-build\work-f2candidate1`
  (the Stage 14 artifacts remain at the original locations and hashes).
- Candidate build: pipeline exit 0 with its embedded smoke already
  reporting `DESKTOP_SMOKE_OK`.
- Candidate artifact SHA-256 (independently re-hashed outside the build
  log):
  - exe `cbdf5b67c065ee474d3cd33555367715f6c7c69c8513cdb0daf65eac90848f3f`
    (17,135,616 B);
  - installer `1a9f315f5ee6e70f933908fcd8a58530613b3c574988c0bc61bcc2658459e5cb`
    (25,012,244 B) — the installer hash matches the value the pipeline
    itself reported.
- Historical hashes preserved unchanged: exe
  `1bf3eb42fa0fb5007e8c8b8f4b6c54db9cb76a4fcb7569cdabd1ebae2b27c637`
  (17,127,936 B), installer
  `ac9229aedb574ec052686779b864fb95d592b218133365f7b93bb2245dae25bc`
  (25,010,550 B). The old artifacts do **not** contain this fix.

Candidate validation on the installed layer (affected host, same user
account, the genuine saved configuration untouched):

1. Silent install of the candidate installer
   (`/VERYSILENT /SUPPRESSMSGBOXES /NORESTART`) → exit 0.
2. The on-disk installed exe re-hashed **byte-identical to the candidate
   exe** (`cbdf5b67…8f3f`, 17,135,616 B).
3. Fresh launch of the installed app with the unchanged
   (directory-shaped) saved path → the Dashboard **Check adb availability**
   probe now reports **OK — validated — the saved executable launches and
   reports a version** (previously `invalid — the saved path did not launch
   a working adb` with the raw WinError 5 beneath it).
4. `Refresh devices` in the Device workspace → **OK — 1 device(s)
   reported**, an attached physical device (serial redacted here) honestly
   listed — i.e. the full spawn → `adb devices` → parse chain works through
   the previously-failing launch path (the pre-fix validation at this layer
   could only produce the `PermissionError [WinError 5]` discovery banner).
5. The app was closed gracefully (no force kill).

## 9. Remaining limitations

- The historical Stage 14 artifacts are superseded: publishing the *old*
  installer would ship the unfixed binary. The release checklist's
  publication items therefore point at the candidate hashes from §8.
- A physical Android device *was* attached during the candidate validation
  and discovery listed it correctly; but the device-facing workflows
  (profile load, inventory, scans on real hardware, monitoring, forensics)
  were not exercised in this fix-side window and remain the standing
  checklist item #9 scope. The validated F-2 surface is exactly the
  launch/spawn layer: probe + honest discovery.
- The Settings dialog's message wording intentionally stays generic ("path
  is valid — a working adb executable") even when the user typed the
  platform-tools directory; the resolution is honest and the messaging
  improvement is left as an optional UX follow-up.

## 10. Bottom line for the checklist

Checklist #23 (F-2) moves from **FAIL** to **PASS** for the *validated
candidate build*; the release disposition remains NOT READY until the
standing owner decisions are made (LICENSE, independent review, Win10
scope) and publication is authorized — now with the corrected artifact
pointers.
