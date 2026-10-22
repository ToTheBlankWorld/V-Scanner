# V-Scanner 3.0 — Release notes (DRAFT — Stage 15, pre-publication)

> STATUS: draft for the Stage 15 acceptance item "release notes drafted".
> This file is **not** the release record: tagging, artifact publication
> and final sign-off are Stage 16 work. Facts below are the Stage 14/15
> audited values.

---

## What is this?

V-Scanner 3.0 is a free, local-only Android security scanner for Windows.
It inventories the applications installed on a connected device, runs a
host-side risk analysis (permission database, SDK advisories, deep-scan
URL/secret heuristics), and produces HTML/JSON/text reports. It also
offers device tools management (ADB/scrcpy provisioning), mirroring,
monitoring polls, forensics case collection — including a pre-authorized,
explicitly-confirmed cleartext WI-FI PSK flow — device administration
(launch/force-stop/uninstall behind exact confirmations), demo mode and
an offline Settings surface.

Nothing in V-Scanner contacts a cloud service. The only network requests
the app can make are the tool downloads **you** explicitly trigger
(Android platform-tools from `dl.google.com`, scrcpy from the official
Genymobile GitHub releases). The scan itself is entirely local.

## This build

| Field | Value |
|---|---|
| Version | 3.0.0a0 (exe metadata 3.0.0.0) |
| Executable | `V-Scanner.exe` — standalone, 17,127,936 B (≈16.3 MiB), SHA-256 `1bf3eb42…27c637` |
| Installer | `V-Scanner-3.0.0a0-Setup.exe`, per-user, 25,010,550 B, SHA-256 `ac9229ae…25bc` |
| Cold start | ≈0.6–1.1 s observed (bound ≤ 4 s) |
| Footprint | 64 files / ≈84.1 MiB installed |
| Signing | **Unsigned** — expect a SmartScreen first-run warning; verify the SHA-256 hash from this page instead of trusting certificates that do not exist |

## Requirements

* Windows 10 or 11 (x64). Verified on Windows 11 (build 26200): install,
  reinstall, launch, uninstall, and user-data retention were executed on
  that host; other SKUs are pending verification.
* No Python installation, no pip, no admin rights. Per-user install to
  `%LOCALAPPDATA%\Programs\V-Scanner`.
* A device that has USB debugging enabled for scanning, monitoring,
  forensics, mirroring and administration. Without a device — and
  without ADB — the app starts and navigates honestly: Doctor explains
  what is missing and no fabricated "connected" state is ever shown.

## What's new in 3.0 (vs the 2.x CLI era)

* One audited engine behind all three UIs (menu-driven CLI, terminal TUI,
  Windows desktop app) — identical findings, identical byte-identical
  report output.
* Desktop app (PySide6): dashboard, devices & administration, scanning,
  findings, reports/history, monitoring, forensics case store, mirroring,
  demo mode, and a Doctor self-check page.
* Honest-by-construction safety rules: destructive administration needs
  an operation-specific typed confirmation and a freshly validated
  selected target; wifi-cleartext forensics additionally requires typing
  `I ACCEPT CLEARTEXT PSK`; findings that could not be confirmed carry
  explicit *unverified* evidence instead of silent guesses; scan results
  are prefixed by default redaction so secret-matching hits never render
  their values.
* Installer lifecycle: silent install/reinstall supported; uninstalling
  never silently deletes case data and reports — `%LOCALAPPDATA%\
  vscanner` is retained and can be removed manually if desired
  (interactive uninstall offers the explicit choice).

## Known limitations in this release

* No code signature yet (SmartScreen warning on first run is expected;
  certificate purchase is a documented decision for the final release).
* Bundled ADB/scrcpy variant not shipped: use in-app provisioning
  (Doctor → tools) to fetch them on demand.
* Display-scaling/larger-text and reduced-motion behavior beyond the
  tested defaults has not been verified on physical hardware.
* No telemetry exists; no automatic updates exist. Get updates from the
  project release page.

## Upgrading & uninstalling

* Installing over an existing installation is supported (files are
  replaced in place; your case data, reports and tool downloads in
  `%LOCALAPPDATA%\vscanner` are not touched).
* Uninstall via Windows Settings → Apps → "V-Scanner" (or the Start-menu
  uninstaller). Leave `%LOCALAPPDATA%\vscanner` alone to keep forensic
  cases and reports; it can be deleted manually afterwards.
* The uninstaller runs silently from the Settings path; after it
  finishes, app files, shortcuts and the uninstall registry entry are
  removed (verified on the release-building host).

## Report issues

Open an issue at the project repository with the Doctor page output
(the app prints no log files; the Doctor page carries everything a
triage needs). Do not paste any device identifiers or report contents
you consider sensitive — findings are redacted by default but case
forensics are not.
