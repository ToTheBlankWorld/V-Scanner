# V-Scanner 3.0 — Stage 00: Repository Audit

**Status:** COMPLETE (audit only; no code changes made)
**Date of audit:** 2026-10-18
**Audited tree:** local `main` = `abdb4cb`, `origin/main` = `abdb4cb` (fast-forwarded from `fc16571` during this stage — remote contained only a `README.md` wording change; see §1)

Evidence notation used throughout:
- **[VERIFIED]** — confirmed by executing a safe, non-destructive check during this audit.
- **[STATIC]** — determined by reading source/configuration; not executed against a device.
- **[TESTED]** — covered by an automated test that was actually run and passed/failed.
- **[ASSUMPTION]** — inferred; requires later-stage verification.

No device was connected and **no device-side commands were executed** during this audit (`adb devices` and interacting with any connected device were deliberately not run, per Stage 00 safety rules). All CLI behavior that requires a device is therefore **[STATIC]/[UNVERIFIED]**.

---

## 1. Repository and branch state

| Item | Value | Evidence |
|---|---|---|
| Working directory | `D:\My Projects\V Scanner` | [VERIFIED] |
| Branch | `main` on `main...origin/main` (synchronized) | [VERIFIED] |
| Remote `origin` | `https://github.com/ToTheBlankWorld/V-Scanner.git` (fetch + push, **HTTPS only, no SSH**) | [VERIFIED] |
| Local HEAD at audit start | `fc16571` "Clean up code and update documentation for Digital Forensics" | [VERIFIED] |
| Remote extra commit | `abdb4cb` "Update README.md" (1 line changed in README only) | [VERIFIED] |
| Fast-forward performed | `git pull --ff-only origin main` → `fc16571..abdb4cb` (safe, non-destructive, no conflicts; the working tree only contained an unrelated whitespace edit to `.gitignore` and one untracked script, neither touched by `abdb4cb`) | [VERIFIED] |

### Pre-existing user work (untouched, unstaged, left in place)

| Item | State | Note |
|---|---|---|
| `.gitignore` modification | Working-tree only | Whitespace-only edit (adds a trailing space to the "Environment Variables" section header comment). Entirely unrelated to Stage 00; **not committed**. |
| `cli/python usb_charging_control.py` | Untracked file | A local experiment script that controls `/sys/class/power_supply/battery/input_suspend` via ADB. Not part of the tracked codebase, never imported by shipped modules. **Not committed**, per Stage 00 rules (unrelated user work). Also notable: its filename contains spaces and starts with `python `. |

---

## 2. Repository top-level structure [VERIFIED]

```
V Scanner/
├── README.md, MASTER_README.md, PROJECT_SUMMARY.md, QUICK_START.md,
│   TOOLS_SYSTEM.md, CLEANUP_REPORT.md       # root documentation (multiple, overlapping)
├── .gitignore
├── android/                                  # Kotlin/Compose Android app (out of plan scope)
│   ├── app/ (source, build.gradle, proguard)
│   ├── build.gradle, settings.gradle, gradle/ (wrapper 8.2), gradlew.bat
│   ├── build/reports/problems/problems-report.html  ← TRACKED generated artifact (hygiene issue)
│   └── .gradle/, app/… — local, git-ignored
├── cli/                                      # Python CLI (upgrade target)
│   ├── main.py            (62 KB, 1588 lines)  # interactive menu entry point
│   ├── scanner.py         (73 KB, 1891 lines)  # ADBInterface + VulnerabilityScanner + hidden Click CLI
│   ├── digital_forensics.py (41 KB, 1012 lines)
│   ├── report_generator.py  (22 KB)
│   ├── permissions.py       (21 KB)
│   ├── tools_manager.py     (15 KB)
│   ├── ui_styles.py         (14 KB)
│   ├── setup.py, adb_setup.py, auto_setup.py, dependency_checker.py
│   ├── requirements.txt, setup.py, adb_config.json (tracked, machine-specific!)
│   ├── INSTALLATION_GUIDE.md, SETUP_GUIDE.md
│   ├── reports/, forensics_cases/, tools/{platform-tools,scrcpy}, __pycache__  ← local, git-ignored
│   └── python usb_charging_control.py   ← untracked user file (see §1)
├── docs/                                     # 10 legacy .md documents (see §10)
└── platform-tools/                           # local extracted ADB, git-ignored
```

Tracked file count: ~125 (Android ~95 res/source + config, CLI 16 code/config/docs, root+docs ~17).

## 3. Python CLI module inventory [STATIC]

Module dependency graph (imports, direction = depends-on →):

```
main.py ──► scanner.py (ADBInterface, VulnerabilityScanner)
        ├─► report_generator.py (ReportGenerator, models)
        ├─► adb_setup.py (get_adb_path, load/save_adb_config, check_adb_valid… — then SHADOWED by local defs)
        ├─► ui_styles.py
        ├─► dependency_checker.py
        ├─► auto_setup.py ──► tools_manager.py
        └─► digital_forensics.py (uses adb_interface passed in)
scanner.py ──► permissions.py (analysis, RiskLevel, patterns)
           ├─► report_generator.py (models)
           └─► tools_manager.py (scrcpy path; imported lazily inside methods)
adb_setup.py ──► tools_manager.py
dependency_checker.py ──► (tools_manager lazily)
digital_forensics.py ──► (adb interface only)
ui_styles.py ──► rich only
```

### 3.1 `cli/main.py` (entry point, 1588 lines) [STATIC]

- Decorated entry point: `python main.py` (only `__main__`; no console-script packaging).
- Flow: clear screen → `auto_setup.check_and_setup()` (may **download** ADB+scrcpy) → `dependency_checker.check_all_dependencies()` (may **pip-install** missing packages) → banner/animation → `find_adb()` → list devices → interactive main loop.
- Main menu: **12 options** (1 List Applications, 2 Analyze Single App, 3 Full Device Scan, 4 Admin Operations, 5 Sensor Monitoring, 6 Full Device Info, 7 Demo Mode, 8 Change Device, 9 Reconfigure ADB, 10 Screen Share, 11 Digital Forensics, 12 Exit). Device auto-select when exactly one connected.
- **Defects found:**
  1. `admin_operations_menu()` is defined **twice** (lines 754 and 1224) with identical bodies — the second silently wins. [STATIC]
  2. `load_adb_config`/`save_adb_config` are imported from `adb_setup` (line 21) then **redefined locally** (lines 38–62) — the import is shadowed; two implementations of the same config I/O exist. The local loader has a bare `except:` swallowing all errors. [STATIC]
  3. `device_unlock(device)` (line 529) — a full PIN/pattern/password unlock driver that injects input into the device — is **never reachable from any menu** (dead code). Besides being unused, it is a security-sensitive capability with fixed-resolution pattern coordinates and a `return True` regardless of actual unlock success. [STATIC]
  4. `select_device()` recursion on ADB reconfigure can recurse unboundedly if the user keeps choosing "1" with no devices. [STATIC]
  5. `import io, sys, re, getpass` etc. performed inside functions repeatedly; `sys` imported at call time while already a module-level symbol. Cosmetic.
  6. Forensics path rebuilds `ADBInterface(current_device, adb_path=adb_result)` — bypassing the `get_adb_interface` helper (inconsistent construction). [STATIC]

### 3.2 `cli/scanner.py` (1891 lines) [STATIC]

Two distinct things live in this file:

**A. `ADBInterface`** — the whole ADB facade. Key methods:
- `_run_cmd` — subprocess with timeout, UTF-8, returns (stdout, stderr, code); graceful FileNotFoundError/TimeoutExpired handling.
- `check_connection`, `get_device_info` (7 getprop calls), `get_comprehensive_device_info` (props, screen, `/proc/meminfo`, `df -h`, `uname -r`, root check via `su -c echo rooted`).
- `get_full_device_info` — IP, MAC, IMEI (`service call iphonesubscriptionservice`), Bluetooth, phone number (**always hardcodes 'N/A'** — the call result is discarded), device name, fingerprint, bootloader, display id, IMSI, timezone, locale.
- `list_packages` (`pm list packages [-3]`), `get_package_info` (dumpsys parsing: versionName/Code, targetSdk, minSdk, codePath, install/update times, requested permissions).
- `get_app_label` — hard-coded 20-entry label cache, otherwise heuristic package-name mangling (never reads real app labels from the device → **derived/fabricated names**, e.g. `com.foo.bar` → "Foo"). Documented "app names" are thus approximations. [STATIC]
- `search_apk_for_urls` (deep scan): `shell strings … | grep -oE` against base.apk on-device; falls back to `cat … | strings | grep`. Returns up to 20 unique insecure URLs (http:// only, private-range filtered). Reliability depends on `strings` availability in toybox (often missing) — **[UNVERIFIED]**, flagged.
- `uninstall_app`, `open_app` (query-activities + `am start`), `force_stop_app`.
- `capture_screen` (screencap → pull → rm) — **defined but never called** from any menu.
- `pull_apk` — **defined but never called** (deep scan analyses APK on-device instead of pulling).
- `start_screen_mirroring(turn_off_screen)` (scrcpy via `tools_manager`, `-S -m 1024 --max-fps 30`), `check_scrcpy_installed`.
- `wake_up_device`, `detect_lock_type`, `check_is_locked`, `unlock_with_pattern/pin/password` (hardware-usage/unlock block is unreachable dead code except wake/detect which are used by the dead `device_unlock`).
- `get_hardware_usage` — **never called** (main.py implements its own inline live-monitoring loops instead).
- `get_sensor_values_live` (3 fallback methods), `get_all_sensors`, `get_live_sensor_readings`, `get_system_monitoring` (CPU/mem/battery/storage/uptime/temperature), `get_current_sensor_data` — mostly **never called**; `display_all_sensors` uses only `get_sensor_values_live`.
- **Defect:** `get_sensor_values_live` fallback **Method 3** fabricates default sensor entries with unit strings (`'Accelerometer (X, Y, Z)': ['m/s²']`) — i.e. it can return plausible-looking but **fake** sensor data when dumpsys parsing fails. [STATIC] — dishonest-data risk.
- **B. `VulnerabilityScanner`** — `scan_all_apps` (Rich progress) / `scan_app` / `get_full_report`. Skips apps whose dumpsys yields no permissions (silently excluded from reports and counts — small reporting bias).

**C. Hidden second CLI** — a Click group (`list-apps`, `analyze`, `uninstall`, `open`, `force-stop`, `scan`, `demo`, `--device`) reachable via `python scanner.py <cmd>`. It has its **own duplicated display helpers** (`_display_app_report`, `_display_scan_summary`, `_display_high_risk_apps` differ from main.py's versions of the same name — e.g. it supports CRITICAL level in colors while main.py maps only HIGH/MEDIUM/LOW). Documented anywhere? The docs advertise `python main.py` only; `scanner.py` CLI usage strings exist in its docstring. [STATIC]

### 3.3 `cli/permissions.py` [STATIC + TESTED]

- `RiskLevel` enum (CRITICAL/HIGH/MEDIUM/LOW/INFO), `PermissionInfo` dataclass, curated `DANGEROUS_PERMISSIONS` dict — **22 permissions** with risks/mitigations/alternatives.
- `SDK_SECURITY_INFO` — current through **API 34 (Android 14)**; APIs 35/36 not represented (device targetSdk 35 would fall to "Unknown/MEDIUM"). Content is now dated (2024-era).
- `INSECURE_URL_PATTERNS` — 8 regexes incl. hardcoded credential patterns. **Note:** these patterns are defined but the deep-scan URL search (`search_apk_for_urls`) does not use them; it only flags `http://` URLs. The credential/secret regexes are **effectively dead**. The README claims "Hardcoded secret detection" — **not implemented in any executed path**. [STATIC]
- `analyze_permissions` — weighted scoring (CRIT 25/HIGH 15/MED 8/LOW 3/INFO 1, cap 100), threshold bands, recommendations (top-2 mitigations per perm).
- `get_sdk_risk` — target/min SDK advisories.

### 3.4 `cli/report_generator.py` [STATIC + TESTED]

- Dataclasses `AppSecurityReport`, `FullScanReport`; `create_app_report`, `create_full_report` (totals, sorted, summary with top-10 common permissions).
- `ReportGenerator` — Jinja2 `HTML_TEMPLATE` (interactive dark report, expandable cards) and `TEXT_TEMPLATE`; `generate_json` via `asdict` fallback. Timestamped filenames, `generate_all`.
- No CSV/PDF; no template files (all inline).

### 3.5 `cli/tools_manager.py` [STATIC]

- Downloads ADB from Google (latest platform-tools ZIP per OS) and scrcpy (GitHub **API latest-release lookup**, fallback `v2.4` URL — note: `scrcpy-2.4-win64-v4.zip` fallback filename is version-stale risk) into `cli/tools/`.
- ZIP/TAR extract, temp-dir shuffle for scrcpy versioned folders, retry ×3 with backoff on download, cleanup of archives.
- `ensure_tools`, `get_adb_path`, `get_scrcpy_path`, `check_tool_exists` (with `console.print` DEBUG noise leaking to menus).
- Extracts archives with `extractall` without member sanitization (mild, standard risk). Downloads over HTTPS by `urlopen` **without certificate pinning** (normal practice; noted).

### 3.6 `cli/adb_setup.py` [STATIC]

- `check_adb_valid` (runs `adb version`, 5 s timeout), `save/load_adb_config` (json at `cli/adb_config.json`), `get_adb_path` (config → local tools → PATH `adb`), `interactive_adb_setup` (auto-detect / custom path / cancel loop).
- Tracked artifact concern: `cli/adb_config.json` is committed and currently contains a **machine-specific absolute path** (`D:\\My Projects\\V Scanner\\cli\\..\\platform-tools\\adb.exe`). Not a secret, but it pins the repo to one machine's filesystem and should be git-ignored/generated instead.

### 3.7 `cli/auto_setup.py` [STATIC]

- `check_and_setup` → `tools_manager.ensure_tools()` (downloads on first run). Also `check_tool_status` and `interactive_tool_setup` — **`interactive_tool_setup` is never called from any menu** (dead; README's "tool setup menu" story only half-exists).

### 3.8 `cli/dependency_checker.py` [STATIC]

- Imports-check for `adb-shell, rich, click, jinja2, requests, pyyaml, colorama, tabulate`; auto **`pip install`** of missing packages at startup (silent side effect on the user's environment); ADB/scrcpy PATH check.
- **Defect:** the checked list includes packages the code never imports (see §3.10). Its "ADB available" check ignores the locally-provisioned ADB (checks PATH only) — inconsistent with `tools_manager`.

### 3.9 `cli/digital_forensics.py` (1012 lines) [STATIC]

- `DeviceForensics`: auto-creates `cli/forensics_cases/` and a timestamped case dir + `metadata.json` on menu entry.
- Root detection `_check_root_safe`: **defaults to "assume ROOTED (Apatch compatibility mode)" when detection fails** — i.e. the code lies about root status by design; consequences: non-rooted users are routed into doomed `su` extraction paths instead of the limited fallbacks. [STATIC] — questionable behavior, documented here, unmodified.
- Menu (8 ops): 1 App Databases, 2 App Shared Prefs, 3 App Files, 4 System Logs (`logcat -d`), 5 Installed Packages, 6 Running Processes (`ps -A`), 7 WiFi Networks (`su cat wpa_supplicant.conf`), 8 Generate JSON report.
- App extraction: paginated 50-per-page selection or `pkg:` manual entry (matches recent commits); databases copied via `su cat` into local files (**text-mode decode via `stdout.encode` — binary corruption risk** for DBs containing arbitrary bytes, since `_run_cmd` decodes with `errors=replace`); prefs/files via `adb pull`.
- **Latent bug:** `extract_call_logs`, `extract_contacts`, `extract_messages`, `extract_browser_history` call `self._extract_all_dbs_from_dir(...)` — a method **that does not exist anywhere** in the module. If invoked, `AttributeError`. They are not exposed on the menu today, so this is dormant code (earlier menu generations used them). [STATIC]
- `_parse_*` sqlite helpers also unused.

### 3.10 `cli/ui_styles.py` [STATIC]

- GEMINI-style banner/menu/animations; several exported helpers (`print_scanning_progress`, `print_security_score_card`, `print_risk_summary_table`, `print_app_analysis_header`, `print_permission_alert`, `create_gradient_text`, `print_scan_complete_animation`) are **imported in main.py but never actually invoked** (partial) / never used.

### 3.11 Packaging & dependencies [STATIC + VERIFIED]

- `requirements.txt`: `adb-shell`, `rich`, `click`, `jinja2`, `requests`, `pyyaml`, `colorama`, `tabulate`, `qrcode[pil]`.
  - **Actually imported by code:** `rich`, `click`, `jinja2` only. **Unused/over-declared:** `adb-shell`, `requests`, `pyyaml`, `colorama`, `tabulate`, `qrcode`.
- `setup.py` — interactive installer (pip install + platform-specific scrcpy/ADB instructions; runs `pip` via shell string).
- No `pyproject.toml`, no package metadata, no console-script entry point, no version constant anywhere (banner says "2.0" in strings).
- `dependency_checker.py` auto-pip-installs missing declared packages at every startup.

### 3.12 Runtime checks actually executed during this audit

1. `python -m py_compile` on all 11 CLI modules → **ALL_COMPILE_OK** [TESTED, PASSED]
2. Functional check of the pure analysis/report layer (no device): `analyze_permissions` on 4 perms → risk_score 48 / MEDIUM; `create_app_report` + `create_full_report` totals OK; `ReportGenerator.generate_all` produced HTML (12,662 B), JSON (2,707 B), TXT (2,897 B) successfully. Output isolated under the approved temp directory; nothing written into the repo except the pre-existing ignored `forensics_cases` cache. [TESTED, PASSED]
3. Environment availability: `rich`, `click`, `jinja2`, `requests`, `pyyaml`, `colorama`, `tabulate` importable; **`adb_shell` and `qrcode` NOT installed** — yet the CLI runs fine without them, confirming they are unused declarations, not broken dependencies. [TESTED]
4. **No automated test suite exists anywhere in the repo** (`**/test*/**` finds zero Python/Kotlin/Java test files; no pytest config, no CI workflows, no `.github/`). The Android `build.gradle` declares JUnit/Espresso/compose-test dependencies, but there are **no test sources**. Everything documented about features is therefore untested by automation. [VERIFIED — absence]

## 4. Android application inventory [STATIC — unchanged, out of plan scope]

Kotlin/Jetpack Compose app, `applicationId com.vsecurity.scanner`, minSdk 26 / targetSdk 35 / compileSdk 35 / Kotlin 1.9.20 / AGP 8.2.0 / Gradle 8.2, Hilt 2.48 + kapt, Room 2.6.1, DataStore, WorkManager, Vico charts, Gson.

| Layer | Files | Responsibility |
|---|---|---|
| UI | MainActivity, Navigation, 5 screens (Dashboard, Scanner, Guardian, Alerts, Settings), theme | Material 3 UI, charts |
| ViewModels | 5 ViewModels | state/flows |
| Data | Database.kt (Room), AppModels, GuardianModels, PreferencesManager (DataStore), Repositories | persistence & audit trail |
| DI | AppModule | wiring |
| Scanner | AppScanner, PermissionDatabase (18.5 KB curated permission knowledge base) | **on-device** package scanning with trusted-prefix risk reduction, Flow-based progress |
| Guardian | PrivacyGuardianService (foreground `specialUse`), BootReceiver | **continuous, on-device background sensor monitoring** via AppOpsManager + UsageStatsManager every 5 s, alert notifications, boot persistence |
| Manifest | QUERY_ALL_PACKAGES, FOREGROUND_SERVICE(+SPECIAL_USE), POST_NOTIFICATIONS, RECEIVE_BOOT_COMPLETED, PACKAGE_USAGE_STATS | permissions distinct from CLI |

**Key difference from the Python CLI (explicitly requested):** desktop/CLI sensor inspection is *pull-scoped*: it introspects `dumpsys camera/audio/location` over ADB from the host and can only infer usage while polling. The Android Privacy Guardian is *push-continuous*: an on-device foreground service using AppOps (camera/mic/location/body-sensors ops) and UsageEvents, running at boot, writing alerts to a Room DB and raising notifications even when the phone is offline from the host. These are **not equivalent capabilities**, and desktop "parity" for the Guardian cannot be claimed by copying dumpsys polling.

Also documented (static observation): icon PNGs in all mipmap densities are 68 bytes (likely placeholder/blank images) — cosmetic packaging issue inside the Android app, noted only, **not modified**.

## 5. Actual entry points and execution flows [STATIC]

1. `python cli/main.py` — interactive 12-option TUI (primary).
2. `python cli/scanner.py [list-apps|analyze|uninstall|open|force-stop|scan|demo] [--device SERIAL]` — secondary Click CLI, undocumented in any README.
3. `python cli/tools_manager.py` — direct tool provisioning.
4. `python cli/dependency_checker.py` — dependency report.
5. `python cli/setup.py` — one-shot environment installer.
6. `python cli/auto_setup.py` — headless provisioning check.

Side effects on normal startup (`main.py`): creates `cli/tools/`, downloads binaries if missing, `pip install`s packages into the active environment, writes `cli/adb_config.json`, creates `reports/` and `forensics_cases/` on demand. `os.system('cls')` runs twice.

## 6. Documentation claims vs. reality (defects and unverified claims)

| Claim (README/docs) | Reality |
|---|---|
| "Hardcoded secret detection" | Regexes exist in `permissions.py` but are not used by any executed scan path. **Not implemented.** |
| "Advanced APK analysis (URLs, hardcoded values)" | Only on-device `strings|grep` for http:// URLs; APK is never deposited locally (`pull_apk` unused); reliability depends on toybox `strings`. **Partially implemented, unverified against real devices.** |
| "Device sensor monitoring (CPU-Z style)" | `dumpsys` polling with a hardcoded **fallback that fabricates sensor placeholders** when parsing fails. Accuracy questionable. |
| Root-status display in forensics | Defaults to "ROOTED" when detection fails by design. Misleading UX. |
| "Enterprise-grade" / "Real-time Analysis" / "app names" | Marketing wording; app "names" are heuristic package-name derivations; no real labels are fetched. |
| Banner/UI "2.0" | No version constant in code; packaging absent. |
| Tool setup interactive menu (`TOOLS_SYSTEM.md`) | `interactive_tool_setup` exists but is unreachable. |
| README quick-start "that's it" | True only on first successful run; failures keep cascading (auto pip-install may fail offline). |
| Multi-page app contents (docs/DIGITAL_FORENSICS.md etc.) | Largely descriptive; some docs still describe call-log/contacts/messages/browser-history extractions removed from the current menu — those four functions are broken (missing helper method). Feature documentation is out of sync with the menu. |

Six dead/broken feature areas identified: device_unlock block, capture_screen, pull_apk, hardware_usage, sqlite parsers, call/contacts/messages/browser extractors. `admin_operations_menu` duplicate definition and shadowed ADB-config functions included in §3.1.

## 7. Security-sensitive operations and data handling [STATIC]

- Uninstall/force-stop/open, screen unlock injection (unreachable today), full-owner data extraction via root (databases/prefs/files/WiFi with plaintext passwords), IMEI/IMSI/MAC collection, logcat dumps (may include private messages persisted by apps), WiFi conf, and `adb_config.json` with local paths.
- Forensics output defaults to `cli/forensics_cases/`, git-ignored — good. But the extracted database content is written via a text-mode round-trip (`stdout.encode('utf-8', errors='replace')` after `_run_cmd` decoded it with `errors='replace'`), which **can corrupt binary SQLite files**; WiFi conf output may include `psk=` entries in plaintext.
- No secrets found in tracked files (only local artifact paths). `git status --ignored --short` confirms ADB/scrcpy binaries, venv caches, and case data are all properly excluded EXCEPT the tracked `android/build/reports/problems/problems-report.html`.

## 8. Project health / hygiene summary

| Finding | Severity | Detail |
|---|---|---|
| Tracked generated artifact `android/build/reports/problems/problems-report.html` | Low | Should be removed from tracking at a later sanctioned stage. |
| Tracked machine-specific `cli/adb_config.json` | Medium | Absolute local path in VCS; breaks fresh checkouts on other machines (config points at `D:\…\platform-tools\adb.exe`; `..\platform-tools` outside `cli/`). |
| Over-declared dependencies incl. `qrcode[pil]`/`adb-shell` | Low | Bulky install; also `dependency_checker` pip-installs them at startup. |
| `.gitignore` regex typo `**pycache**/` | Low | Works accidentally via `**` glob semantics but is fragile. |
| No tests, no CI | High | Critical for the 3.0 upgrade plan; Stage 02 addresses. |
| Duplicated 700-line-ish code paths (two CLI surfaces, duplicated display helpers) | Medium | Maintenance hazard; Stage 03 addresses. |
| Device-dependent code paths unverifiable without hardware | Medium | see §9 limitations. |

## 9. Limitations of this audit

1. **No Android device was connected**; all device-backed features (scan, live sensors, mirroring, unlock, forensics extraction) are static observations only.
2. The Android app was not built or instrumented; Kotlin analysis is source-level only (`./gradlew test` would have no test sources to run anyway).
3. Some network endpoints (GitHub latest-release asset names) were not fetched; the scrcpy v2.4 fallback URL staleness is an assumption from code reading.
4. The Windows desktop TUI behaviors dependent on terminal emulation (ANSI colors etc.) were not exercised beyond module compilation.
5. The untracked local script `cli/python usb_charging_control.py` is a user experiment (battery input-suspend control via ADB); not relevant to the 3.0 plan and documented here for transparency only.

---

**Conclusion:** Repository is on the intended branch, HTTPS remote correct. The Python CLI is a functioning monolith with real, testable pure-analysis capabilities plus several dead/unreachable/broken feature paths and zero automated tests. The Android app is a credible but independent counterpart with a fundamentally different continuous-monitoring architecture. The upgrade surfaces (TUI, desktop, packaging) have clean room to build on top of a service-layer extraction proposed in `TARGET_ARCHITECTURE.md`.
