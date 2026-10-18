# V-Scanner 3.0 — Service Contracts

**Stage 01 deliverable.** The shared application services that the Textual TUI (Stages 05–08) and PySide6 desktop (Stages 09–12) will call. Implementation lands in Stage 03/04 (`vscanner/services/`); Stages 05+ must not invent behavior outside these contracts — deviations require updating this document in the same stage.

Ground rules (inherit from ARCHITECTURE_DECISIONS):
- Services never `print()`; they return models or raise typed errors (`core/errors.py` taxonomy) or emit job events (E).
- Any capability marked **REMEDIATION REQUIRED** is a known-defective or unverified feature (SECURITY_AND_REMEDIATION_PLAN); contracts define the *target* behavior; implementation stages must first remediate, then wire.
- Long/blocking operations always run inside the job system (E) — they return a `JobHandle`, not the result; query/timeout semantics per contract line.
- Destructive operations require an `OperationConfirmation`, the UI obtains it from an explicit user action; services refuse without it.

Legend for each contract: **Inputs/Validation · Returns · Errors · Blocking? · Progress · Cancellation · Side effects · Confirmation · CLI preservation.**

---

## SC-1 DeviceDiscoveryService

| Operation: `list_devices()` |
|---|
| Inputs | None. |
| Returns | `tuple[ConnectionInfo, ...]` (zero or more; includes OFFLINE/UNAUTHORIZED states honestly). |
| Errors | `AdbNotAvailable` (no adb executable). |
| Blocking? | Quick — executes only `adb devices` (default 10 s timeout). Runs on a job if called from UI thread (UI must use job wrapper; the service itself may be called synchronously from non-UI thread). |
| Progress | None (single command). |
| Cancellation | N/A; timeout enforced internally. |
| Side effects | None beyond an `adb devices` invocation. |
| Confirmation | None. |
| CLI preservation | Legacy `get_available_devices()` behavior — parse only `state == "device"` lines — is preserved inside the legacy shim; the service exposes richer states, legacy shim filters them. |

| Operation: `select_device(serial: str \| None)` |
|---|
| Inputs | serial; None clears selection. Validation: serial must exist among `list_devices()` active set or raises. |
| Returns | `DeviceIdentity`. |
| Errors | `DeviceNotConnected`, `DeviceUnauthorized` (returns state info instead of failing availability — caller decides). |
| Blocking/Cancel/Progress | None/sync. |
| Side effects | Mutates session-level current-device binding (per registry instance, not global). |
| CLI preservation | Multi-device menus remain exactly "select by index" in legacy shim; the service adds neutral APIs the legacy shim maps onto menu numbers. |

## SC-2 PackageInventoryService

| Operation: `list_packages(include_system: bool, app_label_mode: Literal["legacy","exact-first"])` |
|---|
| Inputs | Counted flags validated against device presence (`DeviceNotConnected` otherwise). |
| Returns | `tuple[AppInfo, ...]` where each label carries `label_source` (EXACT when obtained at runtime; HEURISTIC retains legacy string for compat). |
| Errors | `AdbCommandError`, `DeviceNotConnected`. |
| Blocking? | Yes-scale — one `pm list packages` plus optional per-package label resolution for requested pages. Runs as a job. |
| Progress | `JobProgressEvent` (list ready → labels completed per N). |
| Cancellation | Yes — between label-lookups (never interrupt the `pm list` itself mid-flight). |
| Side effects | None. |
| CLI preservation | Legacy menu 1 output builds from these shapes (packages identical). |

## SC-3 ScanService (single-app, full-device)

| Operation: `analyze_single_app(package: str, config: ScanConfiguration)` / `scan_full_device(request: ScanRequest)` |
|---|
| Inputs | Package validated regex `^[a-z0-9._+]+$` plus existence check (`DeviceNotConnected`/not-installed → error with packagist hint). Scan request validated (`include_system`/`deep` flags). **Amendment (Stage 03):** the implemented validator is `^[A-Za-z0-9._][A-Za-z0-9._+-]*$` (max 255 chars) — a documented deviation: real Android package IDs contain `-` and uppercase (e.g. `org.fdroid.FDroid`, `com.example.some-app`), which the planned charset rejected. |
| Returns | `JobHandle` → events; on success `ScanResultBundle` (single app = one `AppScanResult`). |
| Errors | Scheduled via job: `AdbCommandError`, `ScanInterrupted`, `JobCancelRequested`. |
| Blocking? | Job-scoped; UI never blocks. |
| Progress | Per-app `JobProgressEvent(current,total,package context)`, per-finding `JobFindingEvent` streaming. |
| Cancellation | Cooperative at defined points: between apps (full scan), between analysis stages (single app). ADB subprocess killed mid-timeout. |
| Side effects | Called only: report files when `export_paths` configured. |
| Confirmation | None (read-only introspection). |
| REMEDIATION REQUIRED | Deep scan (`search_apk_for_urls`) reliability depends on on-device `strings` availability — real remediation: **Stage 08 streams the APK to host & string-extract locally**; until then deep results carry `EvidenceKind.UNVERIFIED_CONDITION` when `strings` path fails (no silent empty result). |
| CLI preservation | Legacy `scan`/`analyze` Click commands use the same service after Stage 03; scores/counts must match the legacy fixture (byte-identical totals). |

## SC-4 DeviceInfoService

| Operations: `get_basic_profile()` · `get_full_profile()` |
|---|
| Inputs | None (current selected device). |
| Returns | `DeviceIdentity` + extended `DeviceProfile` model (basic: model/manufacturer/brand/board/hardware/build_id/android/sdk/patch/kernel/RAM/storage/screen/root_status). Full adds IP/MAC/bluetooth/serial/build fingerprint/bootloader/timezone/locale. |
| Errors | `AdbCommandError`; fields degrade to `Optional=None` (honesty rule) rather than skipping the profile. |
| Blocking? | Many quick ADB calls — job-wrapped. |
| Progress | Coarse (`collecting properties` → `memory/storage` → `network`). |
| Cancellation | Yes (between property fetch groups). |
| Side effects | None read-only. |
| REMEDIATION REQUIRED | `phone_number` is hardcoded `'N/A'` in legacy (`dumpsys iphonesubscriptionservice` output discarded) — Stage 08 attempts-query honestly or removes the row; root check semantics per R-05. |
| CLI preservation | Menu 6 panels render from same profile data. |

## SC-5 AdministrationService (destructive-capable)

| Operations: `uninstall_app(package, confirmation)` · `launch_app(package, confirmation)` · `force_stop_app(package, confirmation)` |
|---|
| Inputs | Package + mandatory `OperationConfirmation(reference=..., confirmed_at=...)` token. |
| Returns | `OperationResult(ok: bool, adb_returncode: int, message: str)` — legacy returns booleans; new callers get honest detail. |
| Errors | `ConfirmationRequired`/`ConfirmationInvalid` if token missing/stale (> 60 s), `AdbCommandError`, `DeviceNotConnected`. |
| Blocking? | One-shot adb call (≤ 30 s). |
| Side effects | **Device-mutating.** |
| Confirmation | Mandatory at the service boundary (see §0 note above); the UI owns presenting the dialog/warning. |
| CLI preservation | Legacy admin menu paths keep semantic parity (accept-and-execute) — destructiveness of the legacy surface is unchanged, but the new engine requires a confirmed call. |

## SC-6 MonitoringService (host-side sensor observation)

| Operations: `poll_hardware_usage(interval_s: float, token)` (job) · `list_sensor_capabilities()` · `read_sensor_values_once()` |
|---|
| Inputs | Interval 0.5 s–30 s (validated clamped); device from selection. |
| Returns | Stream (`JobLogEvent[HardwareUsageSnapshot]` / `tuple[SensorReading, ...]`). |
| Errors | `AdbCommandError` (each iteration tolerant — one failed dumpsys iteration surfaces in stream, doesn't kill the job unless consecutive fails ≥ 3). |
| Blocking? | Continuous job, by nature. |
| Progress | Snapshot events every interval. |
| Cancellation | Yes — between poll iterations. |
| Side effects | None. |
| REMEDIATION REQUIRED | (a) legacy inline loops produce false positives via broad keyword regexes — Stage 08 rewrites detection on `dumpsys camera/audio/location` *-service-specific client lines* & documented confidence level; (b) `get_sensor_values_live` fallback fabricated placeholder rows — target model returns `SensorReading(status=UNAVAILABLE, reason)`; **no invented values**. |
| CLI preservation | Menu 5 identifiers preserved; implementation replaced at the same UX label. |

## SC-7 AdbConfigurationService & ToolProvisioningService

| Operations: `current_path()`, `set_path(path \| None, validation: bool=True)`, `validate(path)`, `ensure_tool(ToolId)`, `provision_tool(ToolId, version: str\|None="latest")`, `tool_status(ToolId)` |
|---|
| Inputs | Path meaningful filesystem path; "adb" PATH-name resolves; provisioning `version=None` = latest resolved from pinned releases file (never implicit latest-URL without checksum). |
| Returns | `ToolStatusReflected` / validation boolean / `JobHandle` for provisioning. |
| Errors | `AdbNotAvailable`, `ProvisioningError` (network, checksum, extraction). |
| Blocking? | Provisioning is a job (minutes-scale). Validation quick (`--version` ≤ 5 s). |
| Progress | Download/extract/events per tools job. |
| Cancellation | Yes — mid-download (chunk boundaries; partial archive discarded on cancel). |
| Side effects | Creates `tools/` dirs, writes config, downloads archives (temp files removed after completion/failure). |
| Confirmation | UI-level advisory ("this will download X MB") before starting provisioning job; service has none. |
| REMEDIATION REQUIRED | Pinned-fallback `scrcpy-2.4-win64-v4.zip` URL staleness (audit §3.5) → Stage 03 verifies live via fallback-checksum release pinning or replacement docs — see R-11. |
| CLI preservation | `python cli/main.py` first-run behavior unchanged for legacy app (explicit kept in `auto_setup` legacy); the new engine's settings path is the only place needing provisioning UX. |

## SC-8 ScreenMirrorService (scrcpy lifecycle)

| Operations: `launch(options: MirrorOptions{persist_device, resolution: int\|None=1024, max_fps: int\|None=30, turn_screen_off: bool, always_on_top: bool=False, confirm_screen_off: bool (mandatory)})` · `list_running()` · `stop(process_token)` |
|---|
| Inputs | Device locked to selection; server options UX-bound. |
| Returns | `JobHandle`-adjacent: registry handle; running list = `tuple[MirrorHandle, ...]`. |
| Errors | `ToolNotValidated(SCRCPY)` (from tool status), `AdbNotAvailable`, `DeviceNotConnected`. |
| Blocked? | Non-blocking — process spawn; UI observes. |
| Progress/cancel | Events: launched/exited; kill is allowed (it's the process manager's own), user closes window "naturally". |
| Side effects | Spawns scrcpy subprocess; option turn_screen_off changes device display. |
| Confirmation | Mandatory in UI before launching mirror screen-off; mirror launch requires explicit "launch" button/keypress. |
| CLI preservation | Menu 10 launches via same service after Stage 03 behind the legacy choice labels. |

## SC-9 ReportService

| Operations: `export(bundle: ScanResultBundle, requested: Mapping[ReportFormat, str \| None], output_dir: str \| None)` |
|---|
| Inputs | Format-or-path mapping; output_dir validated (created if absent). |
| Returns | `ExportResult(formats_written={"HTML": path,...})`. |
| Errors | `ExportError` (filesystem permission, template failure), `ConfigError`. |
| Blocking? | Fast job. |
| Side effects | Writes files wrapped in try/finally (partial export reported with `failed_formats`). |
| CLI preservation | JSON-schema legacy keys preserved (compat guarantee of Stage 03). |

## SC-10 DemoService

| Operation: `demo_scan() → ScanResultBundle` (deterministic fixture generator) |
|---|
| Inputs | None. |
| Returns | Bundle marked `device_serial=None` + "demo" app set with `INFORMATIONAL` facts; records the demo fixture ID in summary. UIs label "DEMO DATA" prominently. |
| Errors | None. |
| CLI preservation | Click `demo` command keeps reports-writing behavior; TUI/Desktop never write reports from demo without explicit user action. |

## SC-11 ConfigService & LoggingService

| Operations: config: `get(keypath)`, `set(keypath, value)`, `schema_version()`, `migrate_import_from_legacy("cli/adb_config.json")`; logging: `redaction_preset()` set/get, `recent_logs(n)`, `log_directory` |
|---|
| Inputs | keypaths validated against published schema doc (kept in `core/config/schema.json` doc-side). |
| Returns | dataclass payload for the value requested; logging returns paths/lines with redaction pre-applied. |
| Errors | `ConfigError`, `ConfigSchemaOutdated`. |
| Side effects | Config writes atomic (file + rename); first write creates dirs. |
| CLI preservation | Legacy ADB config import handled invisibly; legacy CLI behavior stays unchanged while legacy stands. |

---

## Coverage cross-check against FEATURE_PARITY_MATRIX.md (§5.4 requirement)

Every matrix row is covered here or explicitly dispositioned:

| C-Fxx rows | Covered by / disposition |
|---|---|
| C-F01 (interactive menu shell) | Interface concern, not a service — implemented by `ui_terminal` (Stages 05–08) |
| C-F02, C-F05 (ADB tool provisioning & reconfiguration) | SC-7 |
| C-F03, C-F04 (device discovery, selection, switching) | SC-1 |
| C-F06 (app inventory listing) | SC-2 |
| C-F07, C-F08, C-F09, C-F10 (analysis, scans, permission & SDK scoring) | SC-3 (+ core models) |
| C-F11 (insecure URL detection) | SC-3 — REMEDIATION REQUIRED (host-side APK string extraction planned Stage 08) |
| C-F12 (report generation) | SC-9 |
| C-F13–C-F15 (admin: uninstall/open/force-stop) | SC-5 (confirmation-gated) |
| C-F16 (demo mode) | SC-10 |
| C-F17, C-F18 (sensor monitoring) | SC-6 — REMEDIATION REQUIRED (honest data; no fabricated rows) |
| C-F19 (full device info) | SC-4 — REMEDIATION REQUIRED (phone_number hardcoded N/A; root honesty R-05) |
| C-F20 (scrcpy mirroring) | SC-8 |
| C-F21–C-F28 (forensics ops 1–8) | ForensicsService contract (bottom of this document) — byte-safety REMEDIATION REQUIRED (R-07) |
| C-F29 (call logs / contacts / messages / browser history) | NOT COVERED BY A CONTRACT — intentionally dropped per A-06 (broken legacy code; revival requires a documented requirement) |
| C-F30 (device unlock injection driver) | NO CONTRACT — dropped per A-06 (unsafe, unreachable, unverifiable) |
| C-F31 (legacy Click CLI) | No new contract — legacy shim backed by these same services (Stage 03) |
| C-F32 (dependency check / doctor) | SC-11 + explicit `doctor` service op documented in Stage 03 acceptance |
| C-F33 (root status honesty) | ForensicsService + SC-4 — REMEDIATION REQUIRED (R-05) |
| A-F01–A-F04 (Android-only capabilities) | NOT host-side functionality — remain classified separately in FEATURE_PARITY_MATRIX; no TUI/desktop parity claims for them in Stages 05–12 (per ARCHITECTURE_DECISIONS §2.3) |

### ForensicsService contract sketch (own doc-table, parity for C-F21…C-F28)

- `create_case(device, note: str="") → CaseManifest`; auto-`create` when menu entered like legacy.
- `extract_app_data(package, sources: tuple[Literal["databases","shared_prefs","files"],...], confirmation) → JobHandle; events per file; byte-safe via `adb exec-out/data pull` (R-07 remediation required).
- `extract_system_logs()`, `extract_installed_packages()`, `extract_running_processes()` — one-shot jobs.
- `extract_wifi_networks(confirmation_with_acknowledge_redaction: bool)` — writes redacted-by-default file (R-12); full-secret file allowed only on explicit extra confirmation.
- `generate_report() → Exported path` (legacy metadata.json fields preserved: case name, created at, device, android version, is_rooted — plus remediation-owned `root_status: "rooted|not-rooted|unknown"` honest enumeration (R-05).
- Side effects: writes under user-chosen case dir (legacy → `cli/forensics_cases` only until Stage 08 path migration approval).
