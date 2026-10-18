# V-Scanner 3.0 — Typed Data Models

**Stage 01 deliverable.** Implementation target: `vscanner/core/` (models only; no service, no UI imports). Technological choice per ARCHITECTURE_DECISIONS T-10: stdlib **dataclasses** (`slots=True`, `frozen=True` where data model is a snapshot), hand-written light validators at construction boundaries. No pydantic. This file specifies shapes, invariants, serialization, and back-compat identity rules.

Notation: `(opt)` marks `Optional[T] = None`; `RO` = frozen/read-only.

---

## 1. Device identity & connection state

```python
DeviceTransport(Enum)   # USB, WIFI  (fallback UNKNOWN)
DeviceState(Enum)       # DEVICE, OFFLINE, UNAUTHORIZED, RECOVERY, ABSENT
ConnectionInfo          # serial: str; transport: RO DeviceTransport; state: RO DeviceState;
                        # usb_props: dict[str, str] (opt, e.g. vid/pid)
DeviceIdentity          # serial: str; model: str = ""; manufacturer: str = "";
                        # android_version: str = ""; sdk_int: int | None = None;
                        # security_patch: str = ""; unknown_when_missing: bool = True
```
- Serial from `adb devices` line; state mapped from the status token; parsing tolerances: unknown states map to `ABSENT` + diagnostic string `raw_state`.
- **Honesty rule (carries from A-09):** every model field that may be unavailable on some device is `Optional`; renderers must show "Unknown", not fabricate.

## 2. Installed application metadata

```python
AppLabelSource(Enum)    # EXACT, HEURISTIC, UNKNOWN   ← honesty about derived names
AppInfo                 # package_name: str;
                        # label: str = "(unknown)";
                        # label_source: RO AppLabelSource = HEURISTIC;
                        # version_name: str (opt); version_code: int (opt);
                        # target_sdk: int (opt); min_sdk: int (opt);
                        # apk_path: str (opt);
                        # first_install_time: datetime (opt, UTC);
                        # last_update_time: datetime (opt, UTC);
                        # is_system: bool = False;
                        # requested_permissions: tuple[str, ...] = ()
```
- Invariants: `package_name` non-empty, matches `^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z0-9_]+)+$` w/ tolerant mode `TolerantAppInfo` for odd vendor names (kept rare, flagged).
- Legacy parity: when label derivation is heuristic (legacy `get_app_label` parsing), `label_source=HEURISTIC` so UIs may show "derived" badge instead of pretending app name.

## 3. Scan request / configuration / lifecycle

```python
ScanKind(Enum)          # SINGLE_APP, FULL_DEVICE
ScanConfiguration       # include_system: bool = False; deep: bool = False;
                        # export_paths: tuple[str, ...] = (); output_dir: str (opt);
                        # device_serial: str (opt) — validated non-empty when ScanKind=FULL_DEVICE
ScanRequest             # id: RO str (uuid4 hex); created_at: RO datetime (UTC ISO-8601);
                        # kind: ScanKind; config: ScanConfiguration
ScanLifecycleState(Enum)# QUEUED, RUNNING, COMPLETED, FAILED, CANCELLED  (terminal: last 3)
ScanRun                 # request: ScanRequest; state: ScanLifecycleState;
                        # device: DeviceIdentity (opt); started_at / finished_at: datetime (opt, UTC)
```
- Stable identifier: `ScanRequest.id` is uuid4-hex generated **inside the service**, never user-supplied; jobs reference this `job_id` (see E).

## 4. Findings and evidence

Distinguishing Principle (mission requirement): missing info is never a finding; every finding carries the kind of certainty its Detection basis supports.

```python
FindingSeverity(Enum)   # CRITICAL, HIGH, MEDIUM, LOW, INFO      (values = legacy 5-level RiskLevel)
FindingCategory(Enum)   # PERMISSION_EXCESS, SDK_COMPAT, INSECURE_URL,
                        # HARDCODED_SECRET, DEVICE_EXPOSURE, FORENSICS_ARTIFACT, INFO_NOTE
EvidenceKind(Enum)      # CONFIRMED_ARTIFACT, CONFIRMED_COMMAND_OUTPUT,
                        # HEURISTIC_PATTERN, INFORMATIONAL, UNVERIFIED_CONDITION
Evidence                # kind: EvidenceKind; description: str;
                        # source: str          (command / file path / kernel of analysis, redaction-safe)
                        # extracted_at: datetime (UTC)
                        # raw_excerpt: str (opt, size-capped ≤ 2KB, redaction-applied)
Remediation             # recommendation: str; category: FindingCategory; effort: str (opt)
Finding                 # id: RO str = stable_id(); kind: FindingCategory;
                        # severity: FindingSeverity; app: AppInfo (opt) — device-scope findings have None;
                        # device_serial: str (opt);
                        # title: str; detail: str;
                        # evidence: tuple[Evidence, ...];
                        # remediation: tuple[Remediation, ...];
                        # detected_by: str (module name), run_id: str;
                        # tags: tuple[str, ...] (DATAMODELS amendment, Stage 03)
```
- `stable_id()` = sha256 over (`kind|severity|app.package|device_serial|title|first evidence.source`) truncated to 16 hex chars → dedup across runs; documented as the stable finding key.
- Mapping from legacy: `dangerous_permissions` list → `Finding(kind=PERMISSION_EXCESS, severity=RiskLevel.to.Threshold, evidence=kind=CONFIRMED_ARTIFACT from dumpsys)`. SDK advisories → `SDK_COMPAT, …, evidence kind=INFORMATIONAL`. Insecure URLs from deep scan → `INSECURE_URL, evidence kind=HEURISTIC_PATTERN (grep on binary strings)`. Future secret detection → `HARDCODED_SECRET, evidence kind=CONFIRMED_ARTIFACT` (only successful extraction+match), never partially-guessed.
- What never appears as a finding: absence of knowledge (unknown SDK 35 entries → INFO note), root check failures → UNVERIFIED_CONDITION note with detail "root status could not be determined."
- **Amendment (Stage 03): `Finding.tags` is a controlled free-form `tuple[str, ...]`** — UI badge metadata and compat-writer data, never secret material, always renderable. Current producer: the permission analysis emits `(KB category,)` per permission finding (e.g. `("SMS",)`), which the compat report writer uses to reproduce the legacy `dangerous_permissions[].category`. The plan needs this field documented because the compat-writer consumes it as a serialization input.

## 5. Scan results and summaries

```python
AppScanResult           # app: AppInfo; findings: tuple[Finding, ...];
                        # scan_skipped_reason: str (opt)   ← legacy "no permissions accessible" drop
ScanSummary             # run: ScanRun; total_apps: int; high/medium/low/info counts: int;
                        # findings_total: int; per_category_counts: Mapping[FindingCategory, int];
                        # skipped_apps: tuple[str, ...] = (); generation_ms: float
ScanResultBundle        # summary: RO ScanSummary; apps: tuple[AppScanResult, ...]  (risk-desc sorted for read convenience)
```
- Legacy-compat computed aliases (NOT stored): `high_risk_apps`, `medium_risk_apps` etc. derived by mapping CRITICAL+HIGH→HIGH etc. so report exporters can produce legacy-shaped JSON.

## 6. Report metadata & export

```python
ReportFormat(Enum)      # HTML, JSON, TEXT   (legacy filenames preserved: security_report_<ts>.<fmt>)
ReportMetadata          # scan_run_id: str; generated_at: datetime (UTC); device_model: str (opt);
                        # total_apps: int; tool_versions: Mapping[str,str];
                        # redaction: RedactionPreset
ExportResult            # ok: bool; path: str (opt); size_bytes: int (opt); error: str (opt);
                        # formats_written: Mapping[ReportFormat, str]
```

## 7. Tool provisioning state

```python
ToolId(Enum)            # ADB, SCRCPY
ToolState(Enum)         # NOT_FOUND, FOUND_UNVALIDATED, VALIDATED, PROVISIONING, INSTALL_FAILED
ToolStatusReflected     # tool: ToolId; state: ToolState; path: str (opt);
                        # version: str (opt); last_checked: datetime (opt);
                        # last_validation_ok: bool (opt); notes: tuple[str, ...] = ()
```

## 8. Operation errors (taxonomy)

```python
VScannerError(Exception)              # base; fields: message, details: Mapping[str, str]
├─ AdbNotAvailable                    # no adb binary / not launchable
├─ DeviceNotConnected (details: serial)
├─ DeviceUnauthorized                 # state UNAUTHORIZED — requires on-device approval
├─ AdbCommandError                    # cmd: tuple[str,...], returncode: int, stderr_excerpt: str, timeout: bool
├─ ScanInterrupted                    # unexpected mid-scan failure; partial: bool
├─ JobCancelRequested / JobCancelled  # see E
├─ JobConflictError                   # duplicate op on same device
├─ ConfirmationRequired / ConfirmationInvalid
├─ ConfigError / ConfigSchemaOutdated
├─ ProvisioningError (details: url, cause)
└─ ExportError
```
- Subprocess fail-safety: `AdbCommandError` carries ≤ 1KB stderr excerpt; timeouts flagged (`timeout=True`) so UI can differentiate "hung" from "fast-fail".

## 9. Progress / lifecycle events

Detailed schema and delivery contract live in `JOB_AND_EVENT_CONTRACTS.md` §2 — the models themselves (`JobStartedEvent`, `JobProgressEvent`, `JobFindingEvent`, `JobLOGEvent`, `JobTerminalEvent` …) are defined and owned there, implemented in `vscanner/core/events.py`; the rule importable from this file: **events are frozen dataclasses of primitives/typed models** — no functions, no framework objects.

## 10. Serialization, timestamps, redaction

- `datetime` always timezone-aware UTC, serialized ISO-8601 (`2026-10-18T14:22:05+00:00`); never `naive`.
- Serialization rule: `model_to_dict(model)` recursive asdict + `enum → .value`; `dict → JSON` with `ensure_ascii=False`, `indent=2`.
- Every persisted record (config, history, export) embeds `"schema_version": int` and the epoch id `"created_by": "vscanner/<tool_version>"`. Unknown-field tolerance on read (forward-compatible).
- Redaction: a `RedactionPreset(LOGCONSOLE=0, FULL=1)` enum; `LOGCONSOLE` (default) masks WiFi `psk`, IMEI/IMSI digits, phone numbers, SMS bodies; `FULL` only via explicit export action; applied at the boundary of `Evidence.raw_excerpt` insertion and at log-line emission (see SECURITY_AND_REMEDIATION_PLAN R-12).
- Backward-compatibility anchors recorded this file: legacy JSON report keys (`device_info`, `total_apps`, `apps[]`, …) preserved exactly by `io_compat` writers; `RiskLevel.value` strings preserved; legacy permission knowledge base IDs unchanged.

## 11. Validation & parity notes (for Stage 02/03 tests)

- Legacy parity: transform legacy `FullScanReport` → new model must retain identical counts (audit [TESTED] 1/?/1/0 sample fixture reusable).
- Property tests (Stage 02): `stable_id()` collision-free across the real permission domain; serialization round-trip is lossless for every model type incl. `Optional`s.
- Honesty tests: any route that shifts missing→assumption data must introduce UNVERIFIED_CONDITION/INFO — lint rule pinned in AC-02 (ACCEPTANCE_CRITERIA).
