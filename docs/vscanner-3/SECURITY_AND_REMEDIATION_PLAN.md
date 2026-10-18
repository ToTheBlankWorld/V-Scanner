# V-Scanner 3.0 — Security & Remediation Plan

**Stage 01 deliverable.** Converts Stage 00 audit findings (§3, §7, §8 + source verification) into prioritized, stage-owned remediation work. **Nothing is fixed in Stage 01.** Each row names the implementation stage that owns the fix and the tests that prove it. Evidence references are file:line-of-audit-time (verified statements, not secrets).

Severity scale: CRIT (data corruption / destructive semantics), HIGH (dishonest or misleading security signal), MED (fragility, hygiene, latent crash), LOW (cleanup).

---

## R-01 · Duplicate `admin_operations_menu` definition
- **Severity:** MED (dead duplicate; behavior-neutral today since both bodies are identical and the later definition wins).
- **Evidence:** `cli/main.py` line **754** and line **1224** define the same function; the second shadows the first. [STATIC]
- **Impact:** any future edit to the "first" copy silently vanishes — a maintenance trap when legacy is edited during migration.
- **Fix (owned by Stage 03):** when legacy menu is frozen into the shim, keep one definition; delete the first occurrence in the same commit that re-wires legacy onto services; a grep-lint rule (`ruff F811` style duplicate-def detection expanded, custom check optional) asserts no duplicate function names in `cli/**`.
- **Tests:** import module → assert symbol count/function identity; legacy menu behavior test unchanged (4 options + back).
- **Verification stage:** 03 (with legacy wiring).
- **Stage 03 status (2026-10-18): REMEDIATED.** Both byte-identical copies were AST-diff-verified, then exactly one definition was restored to `cli/main.py` (dead first copy deleted; the shadowed second copy lost in the edit was re-added verbatim). Verified: `admin_operations_menu` appears exactly once, no duplicate top-level defs remain in the module (`tests/unit/test_import_architecture.py` guards the engine side; the R-01 regression assertions in `test_known_defects.py` lock the legacy side). Menu behavior (4 options + back) preserved byte-for-byte.

## R-02 · Shadowed ADB-config functions in `main.py`
- **Severity:** MED. **Evidence:** `main.py:21` imports `load_adb_config, save_adb_config, get_adb_path, check_adb_valid` from `adb_setup`; lines **38–62** redefine `load_adb_config`/`save_adb_config` locally, with bare `except:` swallowing config errors ("except: pass" at line 49).
- **Impact:** two divergent config implementations; silent failure modes on malformed `adb_config.json`; confusing global ADB_PATH mutation (lines 34, 65 duplicated `ADB_PATH = None`).
- **Fix (Stage 03):** legacy shim delegates to `services/config.py`; new-engine config has explicit typed errors (no bare excepts, lint-enforced).
- **Tests:** config migration test (existing `cli/adb_config.json` → new schema, first-run); malformed-file test returns honest error, not silence.
- **Stage 03 status (2026-10-18): REMEDIATED (two-layer design).** Authoritative loader = `vscanner.services.config.ConfigService` (strict; raises typed `ConfigError`/`ConfigSchemaOutdated`; atomic writes; legacy `{"adb_path": ...}` files accepted as v1). The legacy `cli/adb_setup.py` shim now delegates to it and keeps its exact function surface; one deliberate behavior upgrade documented: a malformed config prints a visible warning and returns None (legacy silent swallow removed) while the return contract `None` on failure is unchanged for callers. `main.py` no longer redefines `load_adb_config`/`save_adb_config` (local defs + bare-`except` paths deleted; `ADB_PATH` defined once). Stage 02 tests updated in the same commit: the R-01/R-02 characterization/xfail pairs collapsed to fixed-behavior assertions (regression-locked in `test_known_defects.py` + `test_legacy_module_structure.py`).

## R-03 · Forensics extractors calling missing method (`_extract_all_dbs_from_dir`)
- **Severity:** HIGH-as-latent-crash (functionality-specific). **Evidence:** `cli/digital_forensics.py` — the four extractors `extract_call_logs` (≈line 506), `extract_contacts` (≈line 549), `extract_messages` (≈line 590) and `extract_browser_history` (≈line 638) each invoke `self._extract_all_dbs_from_dir(...)`, which has **no definition anywhere in the module** (global grep confirmed). These functions are unreachable from the menu (menu exposes ops 1–8 only), so the crash is dormant.
- **Impact:** `AttributeError` on any future re-exposure; docs in older DIGITAL_FORENSICS docs reference revived menus — risk of half-fixed feature.
- **Fix (Stage 01 decision, honored at 08):** **DEPRECATED/DROPPED** per A-06 — legacy menu never re-exposes; new ForensicsService provides only the 8 real ops; dead methods and their unused sqlite parsers removed during Stage 08 forensics port. Awakening the feature requires a documented requirement + spec addition (SC-forensics would grow an extraction protocol).
- **Tests (Stage 08):** menu make-the-8-ops test asserting no phantom op is reachable; grep-based dead-code check.

## R-04 · Fabricated sensor fallback data
- **Severity:** HIGH (honesty/security-signal integrity). **Evidence:** `cli/scanner.py:653–670` — `get_sensor_values_live` "Method 3" builds `default_sensors = {'Accelerometer (X, Y, Z)': ['m/s²'], …}` — returning plausible-looking rows with units as "values" when dumpsys parsing fails.
- **Impact:** user may believe live sensor telemetry exists when the device provided none; security conclusions could rest on invented data.
- **Fix (Stage 08, via SC-6):** model `SensorReading` with explicit `status: AVAILABLE | UNAVAILABLE(reason)`; no synthetic rows; UI renders "no usable sensor data — dumpsys sensorservice returned <desc>".
- **Tests:** replay-fake with empty/failing `dumpsys` outputs yields zero rows plus one UNAVAILABLE informational entry; property assertion that no fabricated sensor name/value pair can ever appear in the row set.

## R-05 · Root status defaults to "ROOTED"
- **Severity:** HIGH. **Evidence:** `cli/digital_forensics.py:436–459` `_check_root_safe` ends with the comment "Assuming ROOTED (Apatch compatibility mode)" — on detection failure it `return True`; the UI then displays "Root access confirmed" and restricted routing decisions follow.
- **Impact:** non-root users get doomed root paths and mislabelled case metadata (`is_rooted: true` in `metadata.json`).
- **Fix (imposing SC-4/Forensics model):** root status tri-state `ROOTED | NOT_ROOTED | UNKNOWN` (new model, Stage 03 model + Stage 08 wiring); extraction flows branch on `UNKNOWN` with informative fallbacks (the *legacy* non-root fallback paths reused).
- **Tests:** fake-adb failing `su` detection yields UNKNOWN; case metadata carries tri-state; routing decision test.

## R-06 · Secret-detection regexes never executed
- **Severity:** MED (claimed capability gap). **Evidence:** `cli/permissions.py:556–565` defines `INSECURE_URL_PATTERNS` incl. hardcoded API key/_password/secret/token/AWS/Firebase regexes; global grep shows zero consumers; README claims "Hardcoded secret detection".
- **Impact:** users trust a detection that never runs; classic ASVS gap.
- **Fix (Stage 08, within SC-3 remediation of deep scan):** with host-side APK string extraction (R-07 groundwork), run the credential-class regexes against extracted strings; findings emitted as `HARDCODED_SECRET` with `EvidenceKind.CONFIRMED_ARTIFACT` (extracted snippet, redacted beyond key prefix ≤ 6 chars + length) or `HEURISTIC_PATTERN` when matched against minified/multi-line noise. Documentation trimmed in Stage 15 to match real capabilities.
- **Tests:** golden fixtures (synthetic APK strings with seeded key/password/token) produce findings with correct kinds; false-positive budget test (benign strings like `password_field_id:` — avoided patterns documented).

## R-07 · Database rewrite corruption (text-mode cat)
- **Severity:** CRIT for forensics evidentiary integrity. **Evidence:** `cli/digital_forensics.py:277–297` — DB extraction uses `adb shell su -c cat …` through `_run_cmd` (decodes UTF‑8 with errors="replace", thereby losing bytes), then re-encodes `stdout.encode('utf-8', errors='replace')` into a `.db` file.
- **Impact:** extracted SQLite files can be silently corrupted → forensics/report evidence mis-read, hashlib mismatch vs device, unusable cases.
- **Fix (Stage 08, byte-safety):** new `AdbClient` gains binary mode via `adb exec-out su -c 'cat …'` (exec-out is unencoded) or staged `adb pull` where permissible; sha256 recorded in the CaseManifest per file; UI shows hash match/miss.
- **Tests:** fake binary payload extraction byte-equality test; corrupted-path parity test leveraging recorded fixtures; hash recorded test.

## R-08 · Machine-specific `cli/adb_config.json` tracked in git
- **Severity:** MED (portability/leaks local environment shape; not a secret). **Evidence:** file contain `{"adb_path": "D:\\My Projects\\V Scanner\\cli\\..\\platform-tools\\adb.exe"}` — a Windows-specific absolute path committed; fresh non-Windows clones inherit garbage config.
- **Impact:** first-run confusion on clean environments; accidental local-artifact commits later.
- **Fix (Stage 02 hygiene + Stage 03 migration):** untrack the file in Stage 02 alongside R-09 (`git rm --cached`, template `adb_config.example.json`, `.gitignore` entry); in Stage 03 the config service imports a pre-existing copy into the user dir (A-07) and ignores the repo path. Removal uses `git rm --cached` — a normal commit, no history rewrite.
- **Tests:** fresh-clone simulation (env home override) yields config-free first-run path; migration test at Stage 03.
- **Stage 03 status (2026-10-18): REMEDIATED (migration portion).** `ConfigService.import_legacy_config` / `import_repo_legacy_config` implement first-run migration (malformed legacy input is never imported — target stays untouched; unknown `schema_version` is guarded). Tests cover both branches plus the fresh-clone absence case (fabricated repo root). The repo-local untracked copy of `cli/adb_config.json` is still present locally and untouched (R-15 hygiene rule: no discards, no user-file edits).

## R-09 · Generated Android build report tracked in git (`android/build/reports/problems/problems-report.html`)
- **Severity:** LOW. **Evidence:** tracked file within ignored pattern scope (`android/build/`), committed before the rule. [VERIFIED via `git ls-files`]
- **Impact:** repository noise; `.gitignore` unenforced for tracked files; eventual merge conflicts on rebuild.
- **Fix (Stage 02):** `git rm --cached android/build/reports/problems/problems-report.html` + note in commit; NO Android source change.
- **Tests:** post-commit `git ls-files android/build` empty; git log check no further build artifacts.

## R-10 · Subprocess invocation hardening
- **Severity:** MED. **Evidence:** `cli/setup.py:22` — `run_command(cmd, …)` uses `shell=True` with f-string interpolation of `sys.executable` and `requirements_file` path (spaces in path break quoting on Windows).
- **Impact:** quoting/injection-prone pattern; also inconsistent envs (pip target ambiguity).
- **Fix (policy + implementation):** New engine: **zero** `shell=True` anywhere (AdbClientProtocol adapter requirement + lint check); legacy `setup.py` behavior is deprecated outright in Stage 14 when replaced by the installer. From Stage 03, the engine's own subprocess paths use argument-list invocation only.
- **Tests:** lint assertion (no `shell=True` under `vscanner/`); pip-install path test runs via list-args with quoted path.
- **Stage 03 status (2026-10-18): ENGINE PORT DONE.** Every `vscanner/` module is AST-scanned by `tests/unit/test_import_architecture.py`: zero `shell=True`, zero `pip`/`ensurepip` imports, argument-list subprocess only (`SubprocessAdbClient`; `tests/unit/test_services_adb.py` proves the client by launching `sys.executable` with list-argv payloads — R-07 groundwork evidence). Legacy `cli/setup.py` is NOT touched (deprecated, replaced at Stage 14 per the plan).

## R-11 · Tool-download validation & archive extraction safety
- **Severity:** MED→HIGH (supply-chain surface). **Evidence:** `cli/tools_manager.py:30–93` — URLs unverified (GitHub latest-release API, fallback `scrcpy-2.4-win64-v4.zip` — a static versioned asset known to drift); `extract_windows_zip`/`extract_unix_tar` (140–149) call `extractall` without member path checks (zip-slip/tar traversal possible vs TOOLS_DIR); no checksums.
- **Impact:** malicious/compromised upstream or MITM could drop executables; forged archives could write outside tools dir.
- **Fix (Stage 03):** pinned release-manifest (`tools_manifest.json`: tool, version, sha256, URL mirrors) shipped with app and updatable only by user action; verify checksum-before-extract; zipfile/tar extraction with explicit member path validation (reject `..`, absolute paths, symlinks); `tarfile.extractall(filter='data')` where Python ≥ 3.12, manual equivalent otherwise; over HTTPS with verified TLS (urlopen default) noted in docs.
- **Tests:** checksum mismatch rejection; traversal-bomb archive rejection (fixture archives); version-pin fallback test (API unresponsive → pinned manifest).
- **Stage 03 status (2026-10-18): REMEDIATED (engine + legacy hardening).**
  - Engine: `vscanner/services/tools/` ships a pinned manifest (`manifest.py`), member/link-validated safe extractors (`_extraction.py`), and `ToolProvisioningService` (`provisioning.py`) — download to `.staging`, checksum-verify-when-pinned, validate → extract → atomic move; any failure cleans staging and reports `cleanup_done=True`. No fabricated fallback URL exists anymore: pinned Google canonical links for platform-tools; scrcpy resolves ONLY via the live GitHub API and fails with a typed actionable `ProvisioningError` otherwise (stale v2.4 asset intentionally NOT replaced — no unverifiable guessed assets).
  - Legacy: `extract_windows_zip`/`extract_unix_tar` in `cli/tools_manager.py` now validate members (absolute, drive-letter, `..`, and anchored-realpath containment) and use `filter='data'` (PEP 706) with pre-3.12 fallback (validation carries the guarantee there); the stale v2.4 fallback URL was deleted (`get_scrcpy_download_url` returns None on API/asset failure → actionable message, setup aborts) and a regression test locks the URL pattern out of the module.
  - Documented characteristic kept: legacy provisioning still keeps the downloaded archive on failure (parity rule — production behavior must not drift in Stage 03); the failure-cleanup story is the engine's staged install.

## R-12 · Sensitive data in logs, reports and forensics outputs
- **Severity:** HIGH. **Evidence:** Forensics WiFi extraction writes `wpa_supplicant.conf` **in cleartext incl. `psk=`** to user-visible text file (`digital_forensics.py:781–806`); device identifiers (IMEI/IMSI paths, `get_full_device_info`) flow into console panels and (future) logs unredacted; logcat dumps may contain SMS/app message bodies.
- **Impact:** forensic/host artifacts become PII/crypto-leak stores; logs shipped for support would carry secrets.
- **Fix (Stage 04 logging + Stage 08 forensics):** redaction engine (R-12 filters) applied at log boundary and default WiFi output; full-secret output behind explicit double-confirmation (SC-forensics `extract_wifi_networks` signature); case manifests note redaction preset.
- **Tests:** golden log-line redaction tests; WiFi extraction redacts by default test; unredacted path requires explicit flag test.
- **Stage 04 status (2026-10-18): LOG/EVENT BOUNDARY GROUNDWORK LANDED (job layer).** Every job-emitted string passes the R-12 engine at the boundary inside `vscanner/services/jobs.py`: `params_summary` keys matching `psk/password/secret/token/authorization/api_key` (case-insensitive) are wholly `<redacted>`, all event payloads/log messages/progress contexts pass `redact_text` with 120/2000-char caps (contract §12.4). Boundary tests: `test_services_jobs.py::TestLifecycle::test_context_redaction_and_caps_at_the_event_boundary` (+ serialized-payload assertions in `test_core_events.py`, redacted-log checks across subscriber tests); the forensics-side remediation (WiFi extraction, case manifests) remains Stage 08-owned.
- **Stage 05 status (2026-10-18): TUI emits no new logging surfaces.** The Stage 05 terminal UI is presentation-only: it displays service results and the user's own config values in the user's own terminal (never writes them to any file or log); no device identifiers, paths, or findings are rendered yet (no device/scanning wiring in this stage), and nothing is auto-probed at startup - so no new R-12 exposure was introduced. When Stage 06+ device panels start displaying identifiers, the job-layer `redact_text` boundary (Stage 04) is the required pass-through point for anything that also reaches a log or report.
- **Stage 06 status (2026-10-18): DEVICE UI RENDERS IDENTIFIERS — STILL NO NEW LOGGING SURFACES.** The device workspace displays serials, models, and typed error excerpts in the user's own terminal only (never written to any file or log); error text shown in banners is the engine's already-redacted `AdbCommandError.stderr_excerpt`/typed failure words — the R-12 boundary semantics are pinned by a workspace test (a credential-carrying excerpt cannot reach the screen). Forensics-side R-12 remediation remains Stage 08-owned. R-05: the workspace renders the R-05 tri-state honestly (`not determined` vs `not rooted (verified probe)`); the verified root probe itself remains Stage 08-owned.

## R-13 · Destructive device-management operations
- **Severity:** HIGH (UX safety surface). **Evidence:** legacy admin menu executes uninstall/open/force-stop immediately after selection (`main.py` admin block); `select_app_for_admin_op` numbers are 1-based paginated ordering that also accepts any "1..50" value — a misclick is destructive; no undo, no confirm.
- **Impact:** accidental uninstall of user apps; under-confirmed device actions.
- **Fix (policy + services):** `OperationConfirmation` token gating at service boundary (SC-5), UI confirmation dialogs naming package and human label; legacy shim *also* gains a non-behavioral extra confirm prompt inside its own UX during Stage 08 hardening (user-visible change must be noted in stage log; if forbidden, service keeps legacy behavior only when called through legacy entrypoint, documented). Keep parity honest in matrix (C-F13–15): new flows safer, legacy unchanged until 16.
- **Tests:** service refuses unconfirmed call tests; UI confirmation flow integration test; misclick-rescue test (second confirm requires package-name re-entry).

## R-14 · Silent dependency modification at startup (`dependency_checker` auto-pip)
- **Severity:** MED. **Evidence:** `cli/dependency_checker.py:89–113` auto `pip install` invoked during `main()` startup; list includes 6 unused declares (audit §3.11).
- **Impact:** mutating user environments without consent; offline startup errors; bloats envs.
- **Fix (Stage 03):** new-engine `doctor` service reports only (SC-11); explicit `install-doctor-fixes` command opt-in; legacy behavior unchanged until 16 (documented as accepted risk in PROGRESS per-stage note).
- **Tests:** doctor report correctness; no implicit pip call test (subprocess monkeypatch counts zero unless explicitly invoked).
- **Stage 03 status (2026-10-18): REMEDIATED (new-engine surface).** `vscanner/services/doctor.py` is report-only by construction: import-probe package checks (no side effects), tool status reflection (probe failures degrade to honest NOT_FOUND notes), zero pip/ensurepip imports (AST-locked in `test_import_architecture.py`), and it is constructible with no provisioning service at all. The legacy `dependency_checker.py` auto-pip remains until Stage 16 (accepted-risk disposition unchanged).

## R-15 · Bare `except:` usage (silent failure class)
- **Severity:** MED. **Evidence:** multiple — `main.py` config loaders, `scanner.py` sensor fallbacks and hardware paths, `digital_forensics.py` parsers. Loosely counted ≥ 25 sites.
- **Impact:** hides operational errors, produces the dishonesty patterns that motivated R-04/R-05.
- **Fix:** lint rule (Ruff `E722`) gating new code Day-1 (Stage 02); legacy code branches are converted inside the ports during Stages 03/08 or exempted explicitly in the legacy shim freeze list.
- **Tests:** CI lint gate; per-module exemption list reviewed at each porting stage.

## R-16 · Scrcpy pinned-fallback URL drift (informational — see R-11)
- Covered under R-11; verified live release sanity is part of Stage 03 acceptance (provisioning smoke test against GitHub API, recorded in PROGRESS notes).
- **Stage 03 note (2026-10-18):** with the fallback removed entirely (R-11), drift is structurally impossible; the live-API sanity check was executed once during Stage 03 (network was touched only by this manual smoke — never by the test suite) and is recorded in `STAGE_03_IMPLEMENTATION_REPORT.md`.

---

## Ownership-by-stage matrix (§5.3 consistency requirement)

| Stage | Owns |
|---|---|
| 02 | pytest/Ruff/mypy scaffolding (R-15 lint gate); repo hygiene R-09 + R-08 untracking portion |
| 03 | R-01, R-02, R-06 groundwork decision (models), R-07 groundwork (binary ADB mode), R-08 migration portion, R-14, R-15 conversions in shared modules |
| 04 | logging/redaction foundation (R-12 log boundary), job-timeout policy table enforcement |
| 05–07 | no new defect families; confirmation-token plumbing groundwork (R-13 service-level), honest status surfacing test hooks |
| 08 | R-03, R-04, R-05, R-06 full, R-07 full, R-10 (legacy path gone via port), R-12 forensics outputs, R-13 UI confirmation flows |
| 09–13 | desktop-side repeats of R-13 confirmation + R-12 log boundary checks |
| 14 | R-10 final (setup.py retired by installer) |
| 15 | R-12 release QA sweep (secrets-in-logs scan), R-11 live revalidation, SEV gap audit vs docs |
| 16 | closure verification of all rows; per-row status table appended to PROGRESS |

No CRIT item is scheduled beyond Stage 08 except document-level crosschecks. Android sources are excluded from every row.
