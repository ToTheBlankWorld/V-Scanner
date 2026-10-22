# Installing V-Scanner 3.0 on Windows

This guide is for end users. It describes how to obtain, install, launch and
uninstall the Windows release candidate **V-Scanner 3.0 (3.0.0a0)**, and how to
troubleshoot the most common problems.

> **Is there a download yet?** No public release has been published at the time
> of writing. If a maintainer or trusted channel has provided you with the
> installer described below, verify it against the recorded SHA-256 hash
> before running it (§2). V-Scanner's documentation intentionally does not
> point at any download URL that does not exist.

---

## 1. System prerequisites

| Requirement | Detail |
|---|---|
| Operating system | Windows 10 or 11, 64-bit. **Verified so far only on Windows 11 (x64, build 26200)** — the Windows 10 path is a requirement claim, not a tested statement |
| Disk space | ≈ 100 MB for the app + space for reports and ADB/scrcpy tool downloads if you use provisioning |
| Admin rights | **Not required.** V-Scanner installs per-user |
| Python | **Not required** for the desktop app (standalone executable) |
| Android device | Needed for device features (scanning, inventory, monitoring, forensics, mirroring, administration), with **USB debugging enabled**. Without a device the app still launches and its Doctor page honestly explains what is missing |
| ADB / scrcpy | Optional, downloaded on demand by you (§4) |

---

## 2. Obtaining and verifying the installer

1. Obtain `V-Scanner-3.0.0a0-Setup.exe` from a maintainer-provided channel — a
   GitHub Release may exist in the future; until a release is actually published
   there is no official download.
2. Verify the SHA-256 hash **before** running it. In PowerShell:

   ```powershell
   Get-FileHash .\V-Scanner-3.0.0a0-Setup.exe -Algorithm SHA256
   ```

   The recorded release-candidate value is
   `ac9229aedb574ec052686779b864fb95d592b218133365f7b93bb2245dae25bc`
   (25,010,550 bytes). A mismatch with an official record means **do not run
   it** — check with the maintainer channel.
3. Note the corresponding standalone executable hash in case you receive the
   un-installer distribution instead: `V-Scanner.exe`
   SHA-256 `1bf3eb42fa0fb5007e8c8b8f4b6c54db9cb76a4fcb7569cdabd1ebae2b27c637`
   (17,127,936 bytes; `FileVersion`/`ProductVersion` show `3.0.0.0` — this is
   the derived quadruple of `3.0.0a0`, see `STAGE_16_FINAL_RELEASE_REPORT.md` §2).

### What about the SmartScreen warning?

The current release-candidate build is **unsigned** — there is no code-signing
certificate. Windows SmartScreen will therefore show a security prompt the
first time you run the installer or the app. This is expected for unsigned
software, not a sign of malware by itself.

The correct response is:

1. **Verify the SHA-256 hash first** (above). Hash verification is the
   integrity mechanism this release relies on.
2. If and only if the hash matches, you may choose to run the file. That is a
   decision for you; read the SmartScreen text, do not dismiss it blindly.
3. If you cannot confirm the hash through a channel you trust, delete the file
   rather than circumventing the warning.

Do not add an exclusion to Defender or disable SmartScreen globally to get
around this warning.

---

## 3. Installation and launch

1. Run `V-Scanner-3.0.0a0-Setup.exe`. It installs **per user** — no admin prompt.
2. Default location: `%LOCALAPPDATA%\Programs\V-Scanner`.
3. Start-menu shortcuts are created (V-Scanner and its uninstaller).
4. Launch V-Scanner from the Start menu, or run
   `%LOCALAPPDATA%\Programs\V-Scanner\V-Scanner.exe` directly.
5. First launch takes ≈ 0.6–1.1 s observed on the verified hardware (the
   acceptance bound is ≤ 4 s).
6. Use the **Doctor** page (desktop) for first-run diagnostics: it reports what
   is present/missing (ADB path validation, device/transport checks) without
   fabricating a "connected" state.

Installing over an existing installation is supported: files are replaced in
place, and everything under `%LOCALAPPDATA%\vscanner` (config, reports,
history, forensics cases, downloaded tools) is left untouched.

---

## 4. ADB configuration (and optional scrcpy)

V-Scanner never requires ADB to start, and it never downloads anything unless
**you** trigger the action.

* **In-app ADB download (recommended for most users):** use the Doctor / tools
  section, which provisions Android platform-tools from `dl.google.com` and
  scrcpy from the official Genymobile GitHub releases. Progress and failures
  are reported honestly.
* **Bring your own ADB:** install Android platform-tools yourself, then give
  the path to the app (Settings / Doctor). The Settings page includes a
  "Validate path now" check. Paths with spaces are fine — V-Scanner passes
  tool paths as whole argv entries, never through a shell.
* **scrcpy** is only needed for screen mirroring; provision or select it the
  same way.
* No device/ADB? The app still starts; device pages will show honest
  "missing/not connected" states rather than fabricated data.

---

## 5. Data and report locations

| Location | What lives there | Removed by uninstall? |
|---|---|---|
| `%LOCALAPPDATA%\Programs\V-Scanner` | App files | Yes |
| `%LOCALAPPDATA%\vscanner` | Config (`config.json`), exported reports, scan history, forensics cases, provisioned ADB/scrcpy | **No — retained on uninstall**; delete manually only if you want it gone |
| Start-menu shortcuts | Launchers | Yes |
| Uninstall registry key | Add/Remove-Programs entry (per user) | Yes |

V-Scanner runs fully locally: **no telemetry, no tracking, no cloud calls**.
The only network activity possible is the explicit tool download you trigger
(§4). The app also writes no log files by design; the Doctor page output is
what a request for help should include.

---

## 6. Upgrading

1. Run the newer installer over the existing one — no special steps.
2. Verify the *new* installer's hash against the newer release record; hash
   values change with every build, so compare against the record for that
   specific build, not this 3.0.0a0 one.
3. Your data under `%LOCALAPPDATA%\vscanner` survives reinstalls and upgrades.

---

## 7. Uninstalling (and what happens to your data)

1. Windows Settings → Apps → **V-Scanner** → Uninstall, or the Start-menu
   uninstaller (`unins000.exe`).
2. The uninstaller removes the app directory, shortcuts and the
   Add/Remove-Programs entry. On the release-building host this was verified
   to complete cleanly (per-user, no leftover services, scheduled tasks or
   Run-key entries).
3. **User data is retained.** `%LOCALAPPDATA%\vscanner` is not silently
   deleted. Interactive uninstall may offer an optional data-deletion question;
   the *default* answer in that dialog is **retain**. Deleting the folder is
   your manual, explicit choice.
4. Known quirk (recorded): uninstalling through the original installer's
   `Setup.exe /UNINSTALL` flag has been observed to do nothing on one host.
   Use the Windows Settings / `unins000.exe` path instead — that is the
   supported and verified route.

---

## 8. Troubleshooting and diagnostics

General rule: open the **Doctor** page (desktop app) or the Doctor screen
(TUI). It validates the ADB path, device state and environment honestly.

| Problem | What to check / do |
|---|---|
| App window never appears | Re-run the hash check first; then try from a shell so errors are visible; report the Doctor output. `python -m ui_desktop --smoke` (developer install) prints a startup self-check |
| Qt / platform plugin error at start | Update your GPU driver; ensure Windows display settings are standard; report the exact message text and your Windows version |
| Device not detected | Enable USB debugging on the device; re-plug the cable; confirm ADB works (`adb devices`) or let the app validate the configured ADB path; accept the on-device authorization dialog |
| ADB path invalid | Point Settings at the actual `adb.exe` location; use "Validate path now"; re-provision via the tools section if the download was interrupted |
| Scan stuck / slow | Cancel from the app — cancellation is real; check the device USB connection; large inventories paginate |
| Mirroring fails | scrcpy must have been provisioned/selected; mirroring reports honest tool-preflight refusals; your phone screen may need an unlock for scrcpy to attach |
| Report export failed | The app refuses to overwrite without confirmation and does partial-state honesty — check the app's message and the chosen folder's free space |
| Anything else | Open an issue at the project repository and include: Windows version, **Doctor page output text**, the step that failed and what the app displayed. Do **not** paste device identifiers or sensitive report contents — findings are redacted by default, but forensic case files are not |
| Install looks unfinished | Reinstall over the existing install (§3) — files are replaced in place, data is kept |
