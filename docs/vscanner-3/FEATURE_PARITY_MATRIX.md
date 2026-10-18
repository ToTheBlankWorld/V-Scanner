# V-Scanner 3.0 — Feature Parity Matrix

**Baseline of record:** local `main` = `abdb4cb` (2026-10-18).
**Status values:** `implemented` (code present and exercised via menu + verified statically), `unverified` (code present; behavior never executed against a real device/database), `partial` (implemented but limited/biased/broken in a noted way), `missing` (no implementation), `dead` (implemented but unreachable from any menu or entry point).

**Chunking:** CLI features are C-Fxx; Android-only capabilities are A-Fxx; the TUI/Desktop columns are planned targets, **not completed** — they are hard "parity statements" the later stages must satisfy and test before any parity claim is made (Stages 05–08 for TUI, 09–12 for Desktop).

Columns: **Existing implementation** · **Dependencies** · **Side effects** · **Current evidence** · **TUI requirement** · **Desktop requirement**.

---

## 1. Python CLI features (menu options 1–12 + hidden Click CLI)

| ID | Feature | Existing implementation | Dependencies | Side effects | Current evidence | TUI requirement | Desktop requirement |
|----|---------|-------------------------|--------------|--------------|------------------|-----------------|---------------------|
| C-F01 | Interactive main menu (12 options + device banner) | `main.main_menu()` + `main()` loop; `ui_styles` banner/animations | rich; console I/O | Screen clear `os.system('cls')` ×2 | [STATIC] menu rendering helpers verified by import/compile; animation timing untested | Interactive Textual menu equivalent, keyboard-first; animations optional | Qt main window with equivalent navigation |
| C-F02 | ADB auto-setup/provisioning (download, cache, validate) | `tools_manager.setup_adb/ensure_tools`; `adb_setup.get_adb_path` (config → local tools → PATH); `interactive_adb_setup` | urllib, zipfile/tarfile; network | Downloads ADB (~50–60 MB) to `cli/tools/`; writes `cli/adb_config.json`; `pip install` of missing packages via `dependency_checker` | [STATIC] downloads not executed in audit; [TESTED] module compiles; `cli/adb_config.json` tracked w/ machine-specific path | Background job with progress + cancellation; config under user-visible versioned path | Same service, GUI progress dialog; no pip side-effects at startup |
| C-F03 | Device discovery + selection | `get_available_devices` (parses `adb devices`, only state `device`), `select_device`, animated selector; auto-select single device | subprocess; ADB binary | None beyond ADB invocation | [STATIC] logic verified; **[UNVERIFIED]** against real devices (none connected) | Live device list refresh + explicit selection flow | Same list in a device pane |
| C-F04 | Device switching (Change Device, menu 8) | `main()` `change_device` branch | subprocess | None | [STATIC] | Device badge + switcher | Same |
| C-F05 | ADB reconfiguration (menu 9) | `adb_setup.interactive_adb_setup` (auto-detect/custom path/cancel) | subprocess, json | May rewrite `adb_config.json` | [STATIC] | Settings path overwrite + revalidation with feedback | Same in settings dialog |
| C-F06 | App inventory listing (menu 1) with system/third-party toggle | `adb.list_packages(include_system)` + `get_app_label` per row; `pm list packages [-3]` | ADB | None | [STATIC] parsing verified; **labels are heuristic, not real app labels**; [UNVERIFIED] on device | Paginated, searchable, **real labels via `aapt`/labelRes when reachable**, honest fallback | Same grid, exportable |
| C-F07 | Single-app security analysis (menu 2) with deep-scan toggle | `VulnerabilityScanner.scan_app` → `analyze_permissions` + `get_sdk_risk` (deep: `search_apk_for_urls`) | ADB (dumpsys, on-device strings/grep) | None on host | [STATIC] analysis verified [TESTED] for permission/SDK scoring; deep-scan URL path [UNVERIFIED], toybox `strings` dependency flagged | Selection by search/number, deep toggle, typed findings, honest deep-scan status | Same analysis card |
| C-F08 | Full-device scan (menu 3): include-system, deep, format (console/html/json/text/all), output dir | `scan_all_apps` with Rich progress + `ReportGenerator` formats | ADB, jinja2 | Creates `reports/` directory + files | [STATIC]; **[UNVERIFIED]** full scan never executed (no device); apps w/o dumpsys permissions silently dropped from counts | Job progress with per-app detail, cancellation, live summary | Same + report export preview |
| C-F09 | Permission risk analysis & scoring | `permissions.analyze_permissions` (22-permission database, weighted CRIT25/HIGH15/MED8/LOW3/INFO1, cap 100) | pure Python | None | [TESTED] — executed: 4 perms → score 48/MEDIUM | Typed findings rendered with categories/recommendations | Same |
| C-F10 | SDK compatibility/EOL analysis | `get_sdk_risk`, `SDK_SECURITY_INFO` (curent through API 34) | pure Python | None | [STATIC + TESTED]; content dated for API 35+ | Same data, displayed as embeddable widget | Same |
| C-F11 | Insecure URL detection (deep scan) | `ADBInterface.search_apk_for_urls` (on-device strings+grep, ≤20 unique http://) | ADB, toybox strings [UNVERIFIED] | None | [STATIC]; pattern list in `permissions.py` — **credential/secret regexes unused anywhere** | Surface as findings w/ source evidence | Same |
| C-F12 | Report generation HTML/JSON/Text/All | `report_generator.ReportGenerator` (Jinja2 inline templates) | jinja2 | Writes timestamped files to chosen dir | [TESTED] — all 3 formats generated from sample data successfully | Export from TUI (Same service) | Same + file-open/completion action |
| C-F13 | Admin: uninstall app | `adb.uninstall_app` via paginated `select_app_for_admin_op` (50/page, n/p/q + manual package) | ADB | **Destructive to device** | [STATIC] — never executed in audit | Confirmation modal + typed result | Same |
| C-F14 | Admin: open/launch app | `adb.open_app` (`query-activities` + `am start`) | ADB | Launches activity on device | [STATIC][UNVERIFIED] | Same as C-F13 | Same |
| C-F15 | Admin: force-stop app | `adb.force_stop_app` | ADB | Kills app | [STATIC][UNVERIFIED] | Same | Same |
| C-F16 | Demo mode (menu 7) | `main.demo_mode` (rich-only sample table, weak); `scanner.py demo` click command (full pipeline, generates `reports/` files) | pure Python (rich) | **Reports dir** created by click version | [STATIC]; main.py variant is cosmetic, scanning-pipeline one is faithful | Replace with "sample dataset" walkthrough or no-op mode | Same as an onboarding screen |
| C-F17 | Live hardware-usage monitor (camera/mic/GPS) | `main.display_live_sensors` — inline polling loop: `dumpsys window/camera/audio/location`, `ps`, `lsof`, regex package extraction, 2 s refresh, Ctrl+C exit | ADB | None | [STATIC][UNVERIFIED]; heuristic false-positive risk high; `ADBInterface.get_hardware_usage` exists but unused (dup logic) | Async job w/ live table widget + cancel | Same as widget |
| C-F18 | All-sensor values (CPU-Z style) | `adb.get_sensor_values_live` (dumpsys sensorservice → sensormanager → **fabricated fallback placeholders** w/ unit strings) + `display_all_sensors` | ADB | None | [STATIC][UNVERIFIED]; fallback returns plausible-looking fake data — defect documented | Honest events-based view of actually-available sensor data | Same |
| C-F19 | Full device info (menu 6) | `get_comprehensive_device_info` + `get_full_device_info` (IP/MAC/IMEI/BL/fingerprint…); phone_number **hardcoded 'N/A'** | ADB | None | [STATIC][UNVERIFIED] on real hardware (e.g., IMEI path frequently blocked) | Structured device profile panel | Same |
| C-F20 | Screen mirroring via scrcpy (menu 10) | `adb.start_screen_mirroring` (`tools_manager` scrcpy path, `-S -m 1024 --max-fps 30`); install instructions if absent | scrcpy binary, tools download | Spawns scrcpy window (Popen, non-blocking) | [STATIC][UNVERIFIED] (no device, scrcpy present locally at `cli/tools/scrcpy/` but not executed) | Same provisioned path + graceful fallback | Same |
| C-F21 | Forensics: extract app databases | `digital_forensics.extract_app_databases` (50/page picker, `su cat` per file; **text-mode write corrupts binary content** on decode) | ADB, root su | `forensics_cases/<case>/Device_database/…` files written | [STATIC][UNVERIFIED] | Byte-safe extraction (`adb pull`-style or binary-safe `exec-out cat`) | Same |
| C-F22 | Forensics: extract shared prefs | `extract_app_shared_prefs` (50/page, `adb pull` per file) | ADB, root | Local files | [STATIC][UNVERIFIED] | Same as C-F21 | Same |
| C-F23 | Forensics: extract app files | `extract_app_files` (`su find -type f` + `adb pull`) | ADB, root | Local files (recursive mirror) | [STATIC][UNVERIFIED] | Same | Same |
| C-F24 | Forensics: system logs (logcat -d) | `extract_system_logs` (timeout 10) | ADB | `system_logs.txt` | [STATIC][UNVERIFIED] | Streaming log viewer, size/bounds control | Same |
| C-F25 | Forensics: installed packages snapshot | `extract_installed_packages` | ADB | `installed_packages.txt` | [STATIC] | Same | Same |
| C-F26 | Forensics: running processes snapshot | `extract_running_processes` (`ps -A`) | ADB | `running_processes.txt` | [STATIC] | Same | Same |
| C-F27 | Forensics: WiFi networks (wpa_supplicant.conf, root) | `extract_wifi_networks` (`su cat`; **plaintext PSK risk** in output file) | ADB, root | `wifi_networks.txt` | [STATIC][UNVERIFIED] | Redact secrets by default | Same |
| C-F28 | Forensics case creation + JSON report | `create_case`, `generate_report` (auto-case; root extras: packages/processes/SELinux) | ADB, json | `forensics_cases/<ts>/metadata.json`, `forensics_report.json` | [STATIC] | Case-first UX in TUI | Same |
| C-F29 | Forensics: call logs / contacts / messages / browser history | `extract_call_logs/_parse_*` etc. — **call missing `_extract_all_dbs_from_dir` (AttributeError)**; removed from menu | ADB, root, sqlite3 | Would write files if method existed | [STATIC] latent bug documented | Decide: re-implement properly or delete; TUI parity **not required** unless approved | Same decision |
| C-F30 | Device unlock driver (PIN/pattern/password injection) | `main.device_unlock` + `unlock_with_pin/pattern/password` — **unreachable**; pattern coords fixed-res; unlock success not actually verified (`return True`) | ADB | Writes input events to device | [STATIC] dead code | **Not carried forward** unless a documented requirement justifies it (risk/ethics review needed in Stage 01) | **Not carried forward** |
| C-F31 | Secondary Click CLI (`scanner.py list-apps/analyze/uninstall/open/force-stop/scan/demo`) | Full second command surface with own duplicated display helpers | click, ADB | Reports dir (demo) | [STATIC]; undocumented in README | Must remain runnable for backward compatibility (Stage 02 regression target) | Desktop is additive, replaces nothing |
| C-F32 | Startup dependency check/auto-install | `dependency_checker.check_all_dependencies` (+ auto `pip install`) at start | pip, subprocess | Modifies active env | [STATIC]; includes 6 unused declares (adb-shell/requests/pyyaml/colorama/tabulate/qrcode) | Split to explicit `doctor` command; no silent installs | Same explicit tooling |
| C-F33 | Live root-status in forensics UI | `_check_root_safe` — defaults to "ROOTED" on detection failure ("Apatch compatibility") | ADB, su | None | [STATIC] honesty defect documented | Report unknown as unknown | Same |

## 2. Android-only capabilities (unchanged; documented for scope separation)

| ID | Feature | Existing implementation | Dependencies | Side effects | Current evidence | TUI requirement | Desktop requirement |
|----|---------|-------------------------|--------------|--------------|------------------|-----------------|---------------------|
| A-F01 | On-device background sensor monitor (Privacy Guardian) | `PrivacyGuardianService` foreground service, AppOps + UsageStats, 5 s loop, START_STICKY + BootReceiver | Android APIs, Hilt, Room | Continuous notifications, persistent service | [STATIC] | **No** (host has no AppOps) — desktop may observe dumpsys only (C-F17) | **No** — cannot be replicated faithfully without pushing an on-device agent; out of scope |
| A-F02 | On-device package scanning w/ trusted-prefix reduction, Flow progress | `AppScanner` + `PermissionDatabase` + ViewModels | PackageManager | Room writes | [STATIC] | No (CLI covers host-side equivalent) | No |
| A-F03 | Guardian alerts/alerts UI, Room-backed audit log, DataStore settings | GuardianViewModel/AlertsScreen/Repositories/Database | Room/DataStore/WorkManager | DB writes, notifications | [STATIC] | No | No |
| A-F04 | Dashboard charts (Vico), settings screens | Compose screens | Compose BOM, Vico | None | [STATIC] | No | No |

> Rule: parity for A-Fxx rows is **out of scope** for both TUI and Desktop unless a later approved stage expands scope on the record.

## 3. Coverage statement

- All 12 documented main-menu options are represented (C-F01–C-F20, C-F33).
- All 8 forensics menu entries are represented (C-F21–C-F24, C-F25, C-F26, C-F27, C-F28).
- All 7 hidden Click commands are represented (C-F31).
- Significant side effects captured per row (downloads, pip installs, file/dir writes, device-breaking actions, spawned processes).
- Dead/unreachable/degraded features explicitly flagged (C-F16 weak demo, C-F30 dead unlock, C-F29 broken extractors, C-F18 fabricated sensor fallback, C-F33 optimistic root, phone_number N/A in C-F19).
- Android-side continuous guardian explicitly NOT claimed as parity target (A-F01).
- **No TUI/Desktop cell is marked complete** — parity claims must be backed by implementation + tests in Stages 05–08 / 09–12.
