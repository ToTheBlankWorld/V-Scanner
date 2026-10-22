# V-Scanner 3.0 release — DRAFT publication text (pre-release)

**This file is a draft. Nothing here is published, and no release exists in
the repository while this draft exists.** Publication happens only under
separate maintainer authorization, per `STAGE_16_FINAL_RELEASE_REPORT.md`
§13 and `RELEASE_READINESS_REPORT.md` §12. This draft is derived from verified
records only; where a statement could not be verified, it says so.

## Release title (draft)

`V-Scanner 3.0.0a0 — first Windows release candidate (unsigned, pre-release)`

## Release notes body (draft)

V-Scanner 3.0 is Android security and privacy auditing for Windows —
local-only, free, audit-focused. Everything runs on your computer through ADB
(an Android-debugging client bundled in the installer); the app never phones
home, never collects telemetry, and its report content comes only from your
chosen device and your chosen output location.

This is the first packaged Windows build of the 3.0 engine. It ships three
user surfaces: the desktop app (PySide6), a terminal UI (Textual), and the
legacy-compatible menu CLI.

### What the desktop app does (verified in its packaged form)

- Device app inventory and risk findings through the local engine (installed
  applications and their permissions, with a permission knowledge base and
  SDK incompatibility/advisory logic).
- Security-relevant configuration and suspicious pattern checks (URLs,
  hardcoded credentials — detected and **redacted**, never rendered).
- Deep-scan policy probes via real `adb shell` dumpsys surfaces (sensors,
  camera, audio, location — honest "not observed" semantics).
- Live hardware monitoring sessions delivering typed snapshots on the UI
  thread.
- Forensics case collection (byte-exact extraction with SHA-256 records,
  WiFi listing with passwords redacted by default and an explicit opt-in)
  and device administration (launch/force-stop/uninstall behind confirmed
  prompts).
- Report export in three formats (HTML/JSON/TEXT), local files only.
- Doctor diagnostics page, offline Settings screen (ADB path), and a
  deterministic demo mode, clearly labeled `[DEMO]`.
- Report export in three formats (HTML/JSON/TEXT), local files only.
- Doctor diagnostics page and a settings dialog for the ADB path.
- Guided demo mode, clearly labeled `[DEMO]` everywhere.

### Honest known limitations of this build

1. **Unsigned installer (no code-signing certificate).** Windows SmartScreen
   will show an unknown-publisher warning; `WINDOWS_INSTALLATION.md` documents
   the hash-verification step for that state. Verify the SHA-256 below against
   the file you downloaded.
2. **Tested only on Windows 11 x64.** The installer and app lifecycle were
   executed end-to-end on Windows 11 Pro (build 26200), including install,
   reinstall over an existing install, interactive and silent uninstall, and
   user-data retention. No Windows 10 machine was available: the Windows 10
   support claim is **unverified**, not disproven.
3. **ADB workflows need an Android device with USB debugging.** All
   device-facing behavior was validated against the product's own fake-device
   test transport; no physical device pass has happened yet for a release
   build. Expect first-contact surprises (vendor ADB quirks, driver issues)
   and report them.
4. **ADB spawn on some hosts.** On at least one Windows 11 host, the packaged
   app could not launch the bundled ADB (an access-denied process-spawn
   failure, visible as an honest FAILING banner in the app) while the same
   ADB path works from a normal shell. If you see this, please report your
   Windows version and whether ADB works from a shell, via the channels
   listed in the README. Mitigation from source-based installs is possible.
5. **Mirroring is not bundled.** Screen mirroring does not ship in this app;
   without scrcpy present the mirroring page honestly refuses to launch.
6. **Unsigned hash-only integrity.** Until a signed build exists, integrity
   rests entirely on the SHA-256 comparison (and eventually the installed
   app's own self-reported diagnostics).

### Integrity (SHA-256, rechecked before publication)

| Asset | SHA-256 | Size (bytes) |
|---|---|---|
| `V-Scanner-3.0.0a0-Setup.exe` | `ac9229aedb574ec052686779b864fb95d592b218133365f7b93bb2245dae25bc` | 25,010,550 |
| `V-Scanner.exe` (packaged dist, for source users) | `1bf3eb42fa0fb5007e8c8b8f4b6c54db9cb76a4fcb7569cdabd1ebae2b27c637` | 17,127,936 |

*The release maintainer must recheck these against the exact files uploaded —
recorded in `RELEASE_READINESS_REPORT.md` §3.*

### System requirements

- Windows 10 or 11 x64 (verified on 11 x64 build 26200 only — see #2 above);
  per-user install, no administrator rights, no Python required.
- An Android device with USB debugging enabled for device workflows.
- Optional: scrcpy, for mirroring (not bundled).

### License

No LICENSE file exists in the project tree, so no license is granted by this
distribution. Third-party licensing of bundled components is documented in
`RELEASE_READINESS_REPORT.md` §10 (PySide6 under its Qt LGPL terms; rich and
textual MIT; click/jinja2/markupsafe BSD-3-Clause). Final license text is a
maintainer decision pending before publication.

## Artifact manifest (publication checklist, machine-readable)

```text
V-Scanner-3.0.0a0-Setup.exe   sha256=ac9229aedb574ec052686779b864fb95d592b218133365f7b93bb2245dae25bc  bytes=25010550
V-Scanner.exe                 sha256=1bf3eb42fa0fb5007e8c8b8f4b6c54db9cb76a4fcb7569cdabd1ebae2b27c637  bytes=17127936
```

Distribution-policy note for the maintainer at publication time: either asset
set is defensible; the installer alone is the minimal verified surface, the
packaged dist + installer pairs the SHA-256 table above. Verify both hashes
at upload time against the actual uploaded files, then record the flip of
checklist #12–#14.
