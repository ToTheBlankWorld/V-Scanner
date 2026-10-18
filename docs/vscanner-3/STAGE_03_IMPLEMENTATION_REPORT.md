# Stage 03 — Shared Engine and Service Layer — Implementation Report

**Stage status: implementation complete, verification green (see §8). Commit + push recorded in PROGRESS.md.**

This stage built the typed engine package (`vscanner/`), wired the legacy CLI onto it, and remediated the Stage-03-owned defects — while keeping the production lega­cy surface behavior-identical except where a defect fix required a visible change (each deviation documented in §6).

---

## 1. Deliverables

### 1.1 Engine package `vscanner/` (all modules `from __future__ import annotations`, Python ≥ 3.10)

| Module | Contract | Notes |
|---|---|---|
| `core/models.py` | DATA_MODELS §1–§7 typed stdlib dataclasses (`slots=True`) | `Finding.tags` amendment documented (§6.5); honest `None` defaults; ScanSummary legacy-alias buckets |
| `core/errors.py` | typed taxonomy (`VScannerError` base → `ConfigError`, `ConfigSchemaOutdated`, `ProvisioningError`, `AdbCommandError`, `AdbNotAvailable`, `DeviceNotConnected`, `DeviceUnauthorized`, `InputValidationError`, `ExportError`, `ConfirmationRequired`, …) | stderr excerpts redacted + bounded |
| `core/redact.py` | R-12 redaction engine (LOGCONSOLE default preset, FULL explicit) | tradeoff note §6.6 |
| `core/paths.py` | user-data dir resolution (A-07) | no writes at import time |
| `core/kb/permissions.py` | permission/risk KB moved verbatim from `cli/permissions.py` | `cli/permissions.py` is a re-export shim; 25-entry KB verified equal, demo score 40 |
| `services/adb/client.py` | `SubprocessAdbClient` + byte-safe `run_bytes` (R-07 groundwork) | list-argv only; `run_text` replacement-mode |
| `services/adb/devices.py` | device-list parsing + `DeviceDiscoveryService` | unknown state token → `ABSENT` + raw token kept |
| `services/adb/executable.py` | executable validation (5 s `adb version` probe) | single validation authority behind legacy shim |
| `services/adb/device_info.py` | SC-4 `DeviceInfoService` (getprop + kernel) | failures degrade to `None`; root = tri-state `UNKNOWN` |
| `services/scanning/package_parser.py` | dumpsys parser (legacy-semantics mirror) | quirk-preservation documented §6.7 |
| `services/scanning/app_inventory.py` | package listing + app-info fetch | typed failure on nonzero returncode |
| `services/scanning/scanner.py` | SC-3 `ScanService` (`analyze_single_app`, `scan_full_device`) | skip reasons recorded honestly; deep scan emits `UNVERIFIED_CONDITION` INFO note |
| `services/reports/templates.py` | legacy HTML/TEXT templates copied verbatim | byte-equality vs legacy verified (`==` both templates) |
| `services/reports/service.py` | SC-9 `ReportService` + `bundle_to_legacy_dict` | byte-parity across all three formats (test-proven) |
| `services/tools/manifest.py` | pinned manifest + asset resolution rules | no fabricated URLs; darwin drift adjustment documented §6.3 |
| `services/tools/_extraction.py` | member/link-validated safe extractors | symlink-target rejection |
| `services/tools/provisioning.py` | SC-7 `ToolProvisioningService` | staging → checksum → extract → atomic install; `cleanup_done=True` on failures |
| `services/config.py` | SC-11 config + R-02 authoritative loader + R-08 migration | atomic write, schema envelope, strict typed errors |
| `services/doctor.py` | SC-11 doctor, R-14 report-only | import-probes only; zero pip/subprocess |
| `services/registry.py` | service composition + device selection | unauthorized/offline → typed errors |

### 1.2 Legacy rewiring (behavior-preserving)

- `cli/permissions.py` → re-export shim with repo-root `sys.path` bootstrap.
- `cli/adb_setup.py` → delegating adapter (config load/save + executable validation) over `ConfigService`/`check_adb_valid`; exact function surface kept (`check_adb_valid`, `save_adb_config`, `load_adb_config`, `get_adb_path`, `interactive_adb_setup`, `CONFIG_FILE`).
- `cli/tools_manager.py` → R-11 hardening (see §3/§6.4).
- `cli/main.py` → R-01 single `admin_operations_menu` (one module-level definition, body restored verbatim); R-02 local `load_adb_config`/`save_adb_config`/`CONFIG_FILE` removed (imports resolve to `adb_setup` — the adapter — since Stage 02); `ADB_PATH` defined once.

### 1.3 Packaging

- `pyproject.toml`: `[build-system]` setuptools; `[project]` `vscanner 3.0.0a0`, `requires-python >= 3.10`, deps rich/click/jinja2; dev extra group; explicit `[tool.setuptools] packages`; coverage now measures `cli` + `vscanner`; ruff `target-version = "py310"`; mypy `files = ["tests", "vscanner"]`.
- `requirements.txt` (repo root): thin `-e .` shim; `cli/requirements.txt` untouched (legacy install path preserved).

---

## 2. Scope discipline

- Android app (`android/**`): zero modifications (`git status -- android` empty).
- No production dependency versions changed; `cli/requirements.txt` byte-unchanged.
- Pre-existing user items remain unstaged and untouched: modified `.gitignore` (whitespace hunk) and untracked `cli/python usb_charging_control.py`.
- Explicitly deferred per mission: **SC-5 AdministrationService** and **SC-8 ForensicsService** ports (Stage 08); SC-11 remains report-only (doctor + config tool-state), the interactive doctor UI is Stage 05+.
- App dependency note: `adb-shell`, `requests`, `pyyaml`, `colorama`, `tabulate`, `qrcode` remain over-declared in legacy requirements (unused — Stage 00 audit §3.11); untouched here, they fall out at Stage 16.

---

## 3. Defect remediations (Stage-03-owned)

| Row | Disposition | Proof |
|---|---|---|
| R-01 | Single `admin_operations_menu` restored/kept; duplicates gone | AST count == 1; `test_known_defects.py::TestR01*` fixed-behavior test |
| R-02 | Authoritative strict loader + delegating legacy adapter; visible-error upgrade (no more silent swallow); `main.py` shadow defs removed | `test_known_defects.py::TestR02*`, `test_legacy_module_structure.py::TestAdbConfigConsumers*` |
| R-08 | `ConfigService.import_legacy_config` / `import_repo_legacy_config` migration | `test_services_config.py::TestLegacyMigrationR08` (target stays clean on failed migration) |
| R-10 | Engine: argument-list-only subprocesses, zero `shell=True` (lint/AST-locked) | `test_import_architecture.py::TestSubprocessPolicyR10`, byte-exact `run_bytes` proof |
| R-11 | Legacy extractors hardened (validated members + PEP 706 `filter='data'` fallback); stale v2.4 URL deleted with regression lock; engine manifest+staging+checksum+atomic-install | `test_tool_extraction.py`, `test_tool_provisioning_urls.py`, `test_services_tools.py` |
| R-14 | Doctor report-only; zero pip/ensurepip imports in engine (AST-locked) | `test_services_doctor.py`, `test_import_architecture.py::TestNoStartupInstallsR14` |
| R-15 | Engine has zero bare `except:`; legacy bare-excepts remain exempted (legacy freeze until 08/16) | ruff E722 over `vscanner` + `tests` clean |
| R-16 | Fallback URL deleted → drift structurally impossible; live-API sanity smoke executed once (§6.3) | recorded output below |

Stage 02 defect tests updated **in the same change** (strict xfail discipline): R-01 pair → single fixed-behavior assertion; R-02 pair → delegation test + authoritative-loader typed-error test (legacy adapter's non-raising contract pinned separately); R-11 traversal pair → hardened-behavior tests + v2.4-URL regression lock. No Stage 02 assertion was weakened; every divergence is a documented defect-fix flip.

---

## 4. Verification record (exact commands)

On Python 3.12.10 (Windows); suite is device-, network-, and root-free (mocked subprocess, in-memory archives, fake transports; one `sys.executable` list-argv spawn proves byte-safe plumbing).

| # | Command | Result |
|---|---|---|
| 1 | `python -m pytest tests -q --no-header` | **276 passed, 4 xfailed** (runtime ≈ 1.8 s) — xfails: R-04/R-05/R-06/R-07 (Stage 08) |
| 2 | `python -m ruff check vscanner tests` | **All checks passed** |
| 3 | `python -m mypy` | **Success: no issues found in 46 source files** |
| 4 | `python -m compileall -q vscanner cli tests` | clean |
| 5 | `python -m coverage run -m pytest` + `coverage report --include="cli/*,vscanner/*"` | **TOTAL 41%** (was 20% cli-only at Stage 02; per-engine anchors ≥ 92% — honest table in TESTING_STRATEGY §6) |
| 6 | AST duplicate-def scan over `cli/main.py` | `admin_operations_menu` ×1; no duplicates |
| 7 | `import tomllib` on `pyproject.toml` | valid (`vscanner`, `3.0.0a0`) |
| 8 | Import-cycle check + framework check (in-suite) | 36 architecture tests green |

---

## 5. Test inventory (new files)

| File | Count | Focus |
|---|---:|---|
| `tests/unit/test_core_models.py` | 30 | models honesty, stable IDs, alias buckets, redaction, serialization |
| `tests/unit/test_services_adb.py` | 20 | parser semantics (both output shapes), registry selection errors, **R-07 byte-safety proof**, typed error mapping |
| `tests/unit/test_services_scanning.py` | 26 | parser parity vs legacy (risk score/level equal), validation charset, findings mapping, full-device lifecycle |
| `tests/unit/test_services_reports.py` | 7 | **byte parity all three formats**, naming, honest partial-failure export |
| `tests/unit/test_services_tools.py` | 19 | manifest pins, asset rules, staging pipeline, checksum/missing-executable/traversal failures, offline short-circuit |
| `tests/unit/test_services_config.py` | 20 | strict load/save, envelope, R-08 migration branches, atomic write |
| `tests/unit/test_services_doctor.py` | 7 | report-only semantics, probe-failure degradation |
| `tests/unit/test_import_architecture.py` | 36 | framework independence, jinja2 confinement, no `shell=True`, no pip, import cycles, engine→legacy isolation, lean-source budget |
| *(updated)* `tests/unit/test_known_defects.py`, `test_legacy_module_structure.py`, `tests/conftest.py`, `tests/integration/test_tool_extraction.py`, `tests/unit/test_tool_provisioning_urls.py` | — | Stage 02 → hardened-behavior flips (same-commit discipline) |

## 6. Documented decisions & deviations

### 6.1 R-02 two-layer semantics
Legacy adapter prints a visible warning and returns `None` on config errors (compat with all legacy callers); the engine loader raises typed errors. `isolated_config` fixture now points only at `adb_setup.CONFIG_FILE` (the only remaining config state); the validation monkeypatch seam stays `adb_setup.check_adb_valid` (single authority).

### 6.2 SC-3 package charset (deviation, documented in SERVICE_CONTRACTS)
Implemented `^[A-Za-z0-9._][A-Za-z0-9._+-]*$` (≤255) instead of the planned `^[a-z0-9._+]+$` — real package IDs contain uppercase and `-`.

### 6.3 R-16 live-API sanity smoke (executed once, 2026-10-18)
`https://api.github.com/repos/Genymobile/scrcpy/releases/latest` → **v5.0.1** (9 assets). Resolution results: windows → `scrcpy-win64-v5.0.1.zip` ✔; linux → `scrcpy-linux-x86_64-v5.0.1.tar.gz` ✔; darwin/arm64 → initially **NO MATCH** — upstream renamed macOS arm64 assets from `arm64` to `aarch64` in v5.x (`scrcpy-macos-aarch64-v5.0.1.tar.gz`). This is a reviewed (not silent) drift adjustment: `resolve_scrcpy_asset` now accepts both tokens for the darwin arm64 branch, with the drift evidence recorded here and in the manifest docstring (+ dedicated regression test). Upstream also began publishing `SHA256SUMS.txt(.asc)` — noted as the future source for real checksum pinning (manifest `sha256` entries remain `None` = "no pinned digest; skipped honestly"; wiring upstream digest verification is recorded as follow-up work for Stage 14/05). Network was touched only by this one-off smoke — never by the test suite.

### 6.4 R-11 legacy success-path characteristic retained
On extraction/success semantics legacy still keeps the downloaded archive on failure (documented characterization; not upgraded to cleanup since that is a visible behavior change owned by the engine's staged pipeline). Legacy now **rejects** malformed archives via member validation BEFORE any write.

### 6.5 `Finding.tags` (DATA_MODELS amendment)
Controlled free-form tuple; permission findings carry `(KB category,)` and the compat report writer consumes it to reproduce legacy `dangerous_permissions[].category`.

### 6.6 `redact_text` tradeoff
Console-preset digit-run masking can mask timestamp-like digit runs in prose text; structured fields (`target`, etc.) are unaffected. Documented; refinement deferred to the Stage 04 log-boundary work.

### 6.7 Parser quirk preservation (parity requirement)
`analyze_permissions` counts the install-permissions section duplicate (e.g. INTERNET appears twice after `requested permissions` + `install permissions` sections) — the NEW parser mirrors legacy byte-for-byte, so scores (e.g. risk 46 for the fixture) match legacy exactly. Dedup would be a behavior change; deferred with the same parity argument.

### 6.8 Reports `scan_time` sourcing
Legacy stamps each app with `datetime.now().isoformat()` (nondeterministic); the engine uses the first evidence timestamp (deterministic, traceable). File-byte parity is test-proven at pinned clocks; the production-format difference is intentional and documented here (engine times are UTC-aware).

### 6.9 R-07 groundwork evidence
`tests/unit/test_services_adb.py::TestSubprocessAdbClientByteSafety` proves `run_bytes` preserves `b'SQLite\x00\x89PNG\xff\xfe'` through list-argv `sys.executable` child processes (no shell, no encoding) — the wiring Stage 08 will attach to `exec-out` forensics extraction.

## 7. Out of scope (explicit)

SC-5/SC-8 service ports, R-04/R-05/R-06/R-07 full remediations, UI surfaces, logging/eventing, i18n — Stage 04+ per ROADMAP.

## 8. Status summary

All Stage 03 acceptance checks green (§4). Two-truth commitment: everything stated above is backed by a named test or command; the byte-parity guarantee is executable, not aspirational.
