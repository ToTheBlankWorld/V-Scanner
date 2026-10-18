# V-Scanner 3.0 — Architecture Decision Record

**Stage 01 deliverable. Decisions are binding for Stages 02–16 unless re-approved here. Status notation: `DECIDED`, `PROPOSED` (validated at the stage that consumes it), `DROPPED`.**

Grounded in `STAGE_00_REPOSITORY_AUDIT.md` (commit `39e54f8` baseline; repo unchanged since → HEAD `518b652` verified).

---

## 1. Technology stack decisions

| ID | Decision | Status | Rationale | Alternatives considered | Trade-offs / consequences |
|---|---|---|---|---|---|
| T-01 | Python remains the shared scanning engine (single codebase for CLI/TUI/Desktop) | DECIDED | The entire capability set (ADB orchestration, dumpsys parsing, forensics, reports) already exists in Python; rewriting is cost with zero capability gain | Rust/Go rewrite; Node backend | Constrained by GIL for CPU work — irrelevant here (workload is subprocess-bound; jobs are I/O). Python 3.9+ floor assumed; exact floor confirmed in Stage 02 (`vermin`-style check against syntax used) |
| T-02 | Dependency floor: keep existing pins (`rich>=13`, `click>=8`, `jinja2>=3`). **Do not upgrade blindly**; add new deps only per stage with rationale | DECIDED | Audit §3.11: only 3 of 9 requirements.txt entries are actually imported; 6 are over-declared | Upgrade-all policy | Stage 02 slimming of requirements via `pyproject.toml`; `adb-shell`/`qrcode`/`requests`/`pyyaml`/`colorama`/`tabulate` are candidates for removal (no imports exist); removal requires grep-verified zero usage at that stage |
| T-03 | Terminal UI: **Textual + Rich** | DECIDED | Rich already installed and used; Textual shares its API; gives Claude/OpenCode-class interactivity | prompt_toolkit; curses; urwid | Textual app must never mutate `main.py`-style global `Console` state; legacy CLI keeps its own cosmetic animations until Stage 16 |
| T-04 | Windows desktop UI: **PySide6 + Qt Widgets** (not QML) | DECIDED | Qt Widgets suits dense data UIs (tables/findings) and packages well; PySide6 license (LGPL) is distribution-compatible | Tkinter (too weak), wxPython (packaging), QML (superfluous abstraction), Electron + Node (banned) | Binaries grow (~60–80 MB) — addressed in Stage 14 sizing; Qt event loop must interop with the job system (documented in E) |
| T-05 | Packaging: **Nuitka, standalone mode** (not onefile); installer: **Inno Setup** | DECIDED at Stage 01 (ROADMAP Stage 01 scope requires the choice now), validated in Stage 14 | Standalone keeps startup fast and avoids onefile temp-extraction problems when spawning bundled tools (scrcpy/ADB); Nuitka gives C-level compilation with no Python-install assumption; Inno Setup provides mature install/uninstall on Windows | PyInstaller (fallback if Nuitka fails Stage 14 validation: size/startup/AV-flags — re-approval recorded in PROGRESS); MSI (heavier tooling); onefile (startup/temp-dir drawbacks) | scrcpy/ADB are NOT bundled by default — first-run provisioning (or a "bundled tools" installer variant decided at 14) |
| T-06 | Tests: **pytest** (+ pytest-cov) | PROPOSED | Simple, fixture-based, records golden imagery (report output); stdlib `unittest` sufficiency rejected due to fixtures/parametrize needs | unittest | Stage 02 owns setup; CI runner decision also Stage 02 |
| T-07 | Quality tools: **Ruff** (lint+format) and **mypy** (type check, gradual) | PROPOSED | Existing code is untyped; mypy introduced on `vscanner/` with strict settings on `core/`, lenient on legacy shims. Ruff enforced on new code only initially | pylint (slower, redundant w/ Ruff) | lint/type CI job lands in Stage 02; legacy `cli/*.py` excluded from enforcement until each module migrates |
| T-08 | Durable local scan history: plain JSON files; **SQLite only if history grows past justification** (e.g. > 2k scans or query-driven UI needs) | DECIDED (conditional) | Local-first, inspectable, no schema lock-in | SQLite from day one (premature) | History capped (retain last N scans / size limit); schema_version field mandatory; `reports/` legacy dir untouched |
| T-09 | No backend server, cloud, telemetry or mandatory accounts | DECIDED | Product is a local security auditor; all features are host-device-local | (none accepted) | Cloud features need a written requirement + stage approval to exist |
| T-10 | No new heavyweight validation framework (no pydantic) — stdlib `dataclasses` + narrow hand-written validators | DECIDED | Audit shows zero modeling deps today; pandas-scale validation not needed; dataclasses are enough and serialize via `asdict` | pydantic v2 (runtime cost, packaging weight), attrs (marginal gain over dataclasses) | Validation lives in service boundary code; documented in C |

## 2. Architecture decisions

### 2.1 Layering and dependency direction

```
┌────────────────────────────────────────────────────┐
│ Interfaces (nothing may import "down" past contracts)│
│  ui_terminal (Textual)   ui_desktop (PySide6)       │
│  cli/legacy shims (frozen during migration)         │
└───────────────┬────────────────────────────────────┘
                │ ServiceContracts (D) — typed, async-friendly
┌───────────────▼────────────────────────────────────┐
│ Application services (orchestration, jobs)          │
│  services/… (scanning, devices, forensics, reports, │
│  tools, config, jobs, monitoring, admin, demo)      │
└───────────────┬────────────────────────────────────┘
                │ models + interfaces (ABC/Protocol)
┌───────────────▼────────────────────────────────────┐
│ Domain core (models, evidence, risk knowledge base, │
│ config schema, error taxonomy) — zero external deps │
└───────────────┬────────────────────────────────────┘
                │
┌───────────────▼────────────────────────────────────┐
│ Infrastructure (ADB process wrapper, provisioning,  │
│ Jinja2 templates, filesystem paths, logging setup)  │
└────────────────────────────────────────────────────┘
```

| ID | Decision | Status | Rationale |
|---|---|---|---|
| A-01 | Strict dependency direction: `interfaces → services → core`; infrastructure sits behind core-facing interfaces (`AdbClientProtocol`, `ProvisionerProtocol`) so services don't import subprocess directly | DECIDED | Dependency inversion exactly where it cuts test cost: the whole service layer is testable against fakes without ADB |
| A-02 | Presentation / application / domain / infrastructure separation as above | DECIDED | Prevents recurrence of legacy tangles (`main.py ⇄ scanner.py` mutual duplication, display helpers in two places) |
| A-03 | UI frameworks never leak into `services`/`core`: no `textual`, no `PySide6`, no `rich` imports below the interface seam (Rich rendering configured only inside `ui_terminal`) | DECIDED | Services emit data events (E); the event objects are frozen dataclasses |
| A-04 | Services emit `JobEvent`s and return typed models; they never `print()`/log to user-visible console | DECIDED | Dual-frontend requirement; legacy print-based paths are preserved inside legacy shims only |
| A-05 | Legacy CLI compatibility contract: `python cli/main.py` (12 menus) and `python cli/scanner.py` (7 Click commands) remain runnable and behavior-compatible until Stage 16 sign-off; regressed after every stage that touches shared modules | DECIDED | Stated in ROADMAP; migration re-wires internals, not the user-facing surface |
| A-06 | Dead/unsafe code disposition (from audit): the `device_unlock` PIN/pattern/password injection driver (main.py:529, scanner.py:894–1114) is **not carried forward** (security-sensitive, unreachable, unverifiable success); duplicate `admin_operations_menu` and shadowed `load/save_adb_config` are consolidation items owned by Stage 03; call-log/contacts/messages/browser-history forensics extractors (missing method + unused parsers) are **deprecated** unless a documented requirement revives them (TUI must not promise them) | DECIDED (recorded here as required by mission) | Avoids porting defects; keeps parity matrix honest |
| A-07 | Settings/logs/reports/local state storage: `settings → %LOCALAPPDATA%\vscanner\config.json` (versioned, schema-validated, legacy `cli/adb_config.json` imported once); `logs → %LOCALAPPDATA%\vscanner\logs\` rolling; `reports → user-chosen dir, default legacy `./reports`` during migration, then `Documents\vScanner\reports` (Stage 05 approval point); `history → %LOCALAPPDATA%\vscanner\history\` (T-08); tools → `%LOCALAPPDATA%\vscanner\tools\`; in dev-repo mode (env var `VSCANNER_LOCAL=1`) everything stays under the repo dir like today | DECIDED | Windows packaging (T-05) cannot write into Program Files; repo-dir mode keeps dev/test hermetic |
| A-08 | External tool lifecycle: discover (saved config → user tools dir → PATH) → provision (download w/ progress + checksum if published + pinned fallback version file) → validate (`--version` execution) → launch. Provisioning is a cancellable job; setup never runs implicit `pip install` in the new engine (legacy keeps its behavior until Stage 16) | DECIDED | Fixes audit §3.11 silent side effects |
| A-09 | Error model: typed error hierarchy in `core/errors.py` (see C); services raise; interfaces catch at edge and translate once; no bare `except:` in new code (lint-enforced) | DECIDED | Legacy bare excepts swallowed ADB failures (audit §3.1) |
| A-10 | Sensitive device data: collected device identifiers (IMEI/IMSI/MAC/phone number) are shown in UIs on demand, **redacted by default in logs**; WiFi `psk` values never logged; forensics output directories are user-chosen (NOT auto-created under the source tree); no data leaves the machine (T-09) | DECIDED | Audit §7 |

### 2.2 How the two interfaces invoke the same workflows

- Both frontends resolve a single `ServiceRegistry` (composition-root class) that constructs services with injected infrastructure adapters.
- Textual app: jobs run as asyncio tasks consuming the same `JobHandle`/event stream (async bridge in `ui_terminal/jobs_bridge.py`).
- Qt app: `jobs_bridge.py` forks per-UI — Qt variant bridges events into Qt signals (`QObject::emit`) in the Qt main thread; if a job model resolves to a ThreadPoolExecutor for blocking subprocess work (Stage 04 choice), the Qt bridge marshals events via `QMetaObject.invokeMethod`.
- Identical confirmation flows: UI must obtain explicit confirmation then pass `OperationConfirmation(reference=..., confirmed_at=...)` token to destructive service calls — service refuses without it (D).

### 2.3 Android separation reminder (unchanged scope)

The Kotlin app (HUD of Privacy Guardian service, AppOps monitoring, Room persistence) is autonomous, on-device, out of scope for all Python stages. Host-side "sensor" features remain dumpsys-polling introspection and are documented as such (parity matrix A-F01).

### 2.4 Reuse classification from source inspection (audit §3, re-verified)

| Classification | Items |
|---|---|
| **Reusable directly** (pure logic, device-free) | `permissions.analyze_permissions`, `permissions.get_sdk_risk`, permissions knowledge base dicts, `SDK_SECURITY_INFO`, report generators (after model extraction), Jinja2 templates, display-color mapping |
| **Reusable with wrapper** (subprocess/side-effecting) | `ADBInterface._run_cmd`→`AdbClient.run` (needs clean errors, stdout/stderr capture, and byte mode), `tools_manager` download/extract (needs checksum + zip-slip guard), `get_package_info` dumpsys parsing (keep logic, split from ADB client), `digital_forensics` extractors (must switch to byte-safe pull), scrcpy launcher |
| **Extract-in-later-stage** | device info collection, monitoring loops inline in `main.py`, interactive menus (deprecated at the TUI's end-state; legacy kept frozen) |
| **Dropped** | `device_unlock*`, `check_is_locked`, unused sqlite parsers if forensics extractors are deprecated, phantom pip installs, Quick `demo_mode` (replaced by deterministic demo service) |

## 3. Decision consequences recap (for Stage 02–16 acceptance)

1. Stage 02 must establish pytest + captured golden outputs **before** any extraction (Stage 03 cannot proceed without a green baseline).
2. Stage 03 must demonstrate byte-identical analysis/report outputs for the same inputs (score, totals, filenames policy) — the "compat contract".
3. Stage 04's job design must support both asyncio and Qt bridges; frozen-dataclass events only.
4. Stage 05–08 build the TUI on contracts D; Stage 09–12 build the desktop on the same contracts; both require AC parity tables per ROADMAP stages.
5. Stage 14 validates T-05 with a clean Windows VM; if Nuitka fails acceptance (size/startup/AV-flag issues), Tier-2 fallback PyInstaller with explicit re-approval recorded in PROGRESS (installer choice likewise confirmed/adjusted per Stage 01 decision T-05).
6. Android code remains untouched in every stage (git history is the proof).
