# V-Scanner 3.0

Android security and privacy auditing for Windows — local-only, free, and
honest about what it does and does not know.

**Status: `3.0.0a0` release candidate.** Core engine and all three user
surfaces are complete; a Windows release-candidate build is produced and
audited (see [Release record](#documentation)). **No public release has been
published yet** — there is no download link in this file, on purpose, because
none legitimately exists while the release decision is open.

---

## What V-Scanner does

V-Scanner scans an Android device over ADB and audits, from the **host
computer**:

* installed applications and their permissions (permission knowledge base,
  SDK incompatibilities and advisories),
* security-relevant configuration and suspicious patterns (URLs, hardcoded
  credentials — detected and **redacted**, never rendered),
* full HTML/JSON/text reports with byte-identical content across the UIs,
  plus report history,
* device tools: ADB/scrcpy provisioning (explicit download by you only),
  screen mirroring, live monitoring polls, forensics case collection
  (byte-exact extraction with SHA-256 records; WiFi passwords redacted by
  default, with an explicit opt-in flow), device administration
  (launch/force-stop/uninstall behind confirmed prompts),
* a Doctor diagnostics page, an offline Settings screen, and a deterministic
  demo mode.

**Important distinction:** everything above runs on your computer via ADB.
V-Scanner does **not** include an Android-side background monitoring service
running on the phone.

Honesty rules are built in: unknown values are shown as `unknown`, cancelled
or failed operations say so, and deep-scan checks that cannot be confirmed
report explicit *unverified* status. Nothing is fabricated.

## Surfaces

| Surface | How to start* |
|---|---|
| **Windows desktop app** (PySide6) | `V-Scanner.exe` from the installed app, or `vscanner-desktop` / `python -m ui_desktop` from source |
| **Terminal UI** (Textual) | `vscanner-tui` or `python -m ui_terminal` |
| **Menu-driven CLI** (legacy-compatible) | `python cli/main.py` |

*from a source checkout — see §Development. The desktop entry point supports
`python -m ui_desktop --smoke` for a startup self-check.

Nothing in V-Scanner telephones home. The only network requests possible are
tool downloads **you** explicitly trigger (ADB platform-tools from
`dl.google.com`, scrcpy from the official Genymobile GitHub releases).

## Installation (Windows)

The full, current guide lives in
[`docs/vscanner-3/WINDOWS_INSTALLATION.md`](docs/vscanner-3/WINDOWS_INSTALLATION.md).
Summary:

1. Obtain the installer `V-Scanner-3.0.0a0-Setup.exe` from a maintainer
   channel you trust. **There is no published release yet** — this README
   invents no URL.
2. Verify its SHA-256 before running (the guide lists the recorded
   release-candidate hashes and a PowerShell one-liner). The build is
   unsigned, so expect a SmartScreen warning; verify the hash rather than
   dismissing the warning blindly.
3. Install — per user, no admin rights, no Python required. Launch from the
   Start menu and open the **Doctor** page for diagnostics.
4. For device features: enable USB debugging on the phone and provision or
   configure ADB in the app.

Requirements (as designed, *verified only on Windows 11 x64 build 26200 so
far*): Windows 10/11 x64; an Android device with USB debugging for device
features; optional ADB/scrcpy via in-app provisioning or your own install.

## Data locations and privacy

* App: `%LOCALAPPDATA%\Programs\V-Scanner` (removed by uninstall).
* User data — config, reports, history, forensics cases, provisioned tools:
  `%LOCALAPPDATA%\vscanner` (**retained on uninstall**; delete manually only
  if you want everything gone).
* No telemetry, no account, no registration, no log files. Findings are
  redacted by default; forensic case files are not — do not share them
  casually.

## Documentation

| Document | Purpose |
|---|---|
| [`docs/vscanner-3/WINDOWS_INSTALLATION.md`](docs/vscanner-3/WINDOWS_INSTALLATION.md) | Install, SmartScreen/verify, ADB & scrcpy, data locations, upgrade/uninstall, troubleshooting |
| [`docs/vscanner-3/STAGE_16_FINAL_RELEASE_REPORT.md`](docs/vscanner-3/STAGE_16_FINAL_RELEASE_REPORT.md) | The single source-of-truth release record (facts, evidence, disposition) |
| [`docs/vscanner-3/RELEASE_READINESS_REPORT.md`](docs/vscanner-3/RELEASE_READINESS_REPORT.md) | Release-readiness assessment: quality-gate numbers, artifact provenance, findings ledger, verdict |
| [`docs/vscanner-3/PUBLIC_RELEASE_DRAFT.md`](docs/vscanner-3/PUBLIC_RELEASE_DRAFT.md) | Pre-publication draft of the future release notes (not a release; nothing is published while this exists) |
| [`docs/vscanner-3/RELEASE_CHECKLIST.md`](docs/vscanner-3/RELEASE_CHECKLIST.md) | Per-check status grid with evidence and owners |
| [`CHANGELOG.md`](CHANGELOG.md) | Version history (candidate level) |
| [`docs/vscanner-3/`](docs/vscanner-3/) | Full stage-by-stage reports (00–15), progress tracker, testing strategy, security review |
| `TOOLS_SYSTEM.md`, `QUICK_START.md`, `MASTER_README.md` | **Historical 2.0-era CLI documents** — kept for reference; they describe the pre-3.0 tool flow |

## Reporting problems

Open an issue at the project repository
(`https://github.com/ToTheBlankWorld/V-Scanner`) with the **Doctor page
output**, your Windows version, and the step that failed. Do not paste device
identifiers or sensitive report contents.

---

## Development

For contributors; the release-candidate desktop app ships standalone and
needs none of this.

* **Python ≥ 3.10.** Install editable with the tool you need:

  ```bash
  pip install -e .            # engine + TUI + CLI surfaces
  pip install -e .[desktop]   # + PySide6 for the desktop app
  pip install -e .[dev]       # + pytest/coverage/ruff/mypy
  ```

* **Run the tests** (no device, no network, no root required; all faked at
  the transport seam):

  ```bash
  python -m pytest tests -q
  ```

* **Quality gates** (used per stage; numbers in `docs/vscanner-3/TESTING_STRATEGY.md`):
  `ruff check .`, `mypy` (tests + engine + UI layers), `compileall`, and
  `python -m ui_desktop --smoke` (requires `[desktop]`).
* **Windows packaging** (maintainers, reproduces the release-candidate
  artifacts): `python -m packaging_windows.build_windows` — see
  `STAGE_16_FINAL_RELEASE_REPORT.md` §6 for the exact pipeline and cautions
  (a rebuild replaces build outputs; the recorded artifacts live elsewhere).
* Architecture and stage history: start with
  `docs/vscanner-3/PROGRESS.md`, `docs/vscanner-3/TARGET_ARCHITECTURE.md` and
  `docs/vscanner-3/ARCHITECTURE_DECISIONS.md`, then the per-stage reports.

## License

No LICENSE file is present in this repository and no license is granted or
claimed. The previous README's "MIT License" footer was factually wrong and
has been removed. See `docs/vscanner-3/STAGE_16_FINAL_RELEASE_REPORT.md`
§12 risk row 9: picking and documenting a license is recorded as an
outstanding decision for the project owner.

---

**V-Scanner 3.0 (`3.0.0a0`)** · development branch: `main` · release status:
NOT READY for distribution (documentation stage complete; publication awaits
separate authorization) — see `docs/vscanner-3/STAGE_16_FINAL_RELEASE_REPORT.md` §13.
