# V-Scanner 3.0 — Testing Strategy

**Stage 02 deliverable.** Governs test design from Stage 02 onward. Updated by each stage that adds tests.

## 1. Development environment requirements

| Component | Version (validated on this stage) | Notes |
|---|---|---|
| Python | 3.12.10 | Dev machine version; legacy dep floor stricter-check task belongs to Stage 03 (T-01 follow-up) |
| pytest | 9.0.3 | Runner; config in `pyproject.toml` |
| pytest-cov | 7.1.0 | Coverage measurement (dev-only install, documented) |
| Ruff | 0.16.8 | Lint; config in `pyproject.toml` |
| mypy | 2.3.1 | Type check; narrowly scoped (see §5) |

`pytest-cov` was installed during this stage (`pip install pytest-cov`). It is a development tool: `cli/requirements.txt` is unchanged and no production dependency was touched.

## 2. Test categories and purpose

| Directory | Purpose | Contact with reality |
|---|---|---|
| `tests/unit/` | Pure-logic characterization: permission KB/scoring, report factories/templates, tool URL resolution, static module structure (AST), config-consumer behavior, defect evidence | No subprocess, no filesystem outside `tmp_path` except temp-time demos |
| `tests/integration/` | Component-through-subprocess paths: `ADBInterface._run_cmd` (mocked subprocess — one real local `python` process for decode semantics), Click CLI via `CliRunner`, tool extraction with generated archives, syntax baseline | Never launches `adb`/`scrcpy`; never touches network; one test intentionally runs `sys.executable` locally |
| test fixtures | Generated in-test (zip/tar writers, JSON payloads) for determinism | No checked-in binary fixtures |

Organization note: the smallest structure fit — `tests/unit` + `tests/integration` only; `tests/fixtures/` was intentionally omitted because fixtures are generated programmatically at test time (deterministic, no repo binaries).

## 3. Exact commands

```powershell
# Run the whole suite (no device, no network, no root):
python -m pytest

# Coverage of the legacy CLI package:
python -m pytest --cov=cli --cov-report=term

# Lint (new code only — cli/ excluded until its stages migrate):
python -m ruff check .

# Type check (scoped to tests, see §5):
python -m mypy

# Python syntax validation of all legacy modules (also asserted by tests/integration/test_syntax_baseline.py):
python -m pytest "tests/integration/test_syntax_baseline.py"
```

`pyproject.toml` sets `testpaths = ["tests"]`, `--strict-markers` and `xfail_strict = true`.

## 4. Mocking conventions

- **ADB subprocess:** patch `scanner.subprocess.run` (and `main`-equivalents) with `subprocess.CompletedProcess`, or reuse `tests/conftest.py::FakeAdb` for object-level fakes (`DeviceForensics` consumes `_run_cmd` tuples directly).
- **Network / tool downloads:** patch `tools_manager.download_file` or `urllib.request.urlopen`; a test fails by design if a download is attempted without being mocked ("network access attempted although tool present").
- **Filesystem:** every generated artifact goes under `tmp_path` (`tmp_cwd` fixture handles cwd-relative writers such as the demo's `reports/` and `ReportGenerator` output).
- **Machine-specific config:** `isolated_config` fixture repoints both legacy config loaders to a temp file; tests never read the developer's real `cli/adb_config.json`.
- Hard rule inherited by later stages: **no test may execute real ADB administrative (uninstall/open/force-stop) commands, real downloads, or read/write production device-data paths.**

## 5. Type-check scope and lint baseline (Stage 02 decision records)

- **mypy** runs on `tests/` only with `follow_imports = "silent"`: test code themselves must be sound, while errors inside the legacy `cli/` modules (untyped, ~3.3k statements with structural defects scheduled for remediation R-10/R-15) are suppressed until each module migrates. When `vscanner/core/` appears in Stage 03, its strict config is added there (T-07).
- **Ruff** selects a minimal fixable set (`E9/F63/F7/F82/E722/F811/F841/B006/B015/B018`) for new code, `cli/` and `android/` excluded until migrated. Baseline status: **all checks pass**.
- **Syntax validation** compiles all 11 legacy modules in CI-visible test output.

## 6. Current coverage result (honest, Stage 02)

| Module | Statements | Missed | Coverage |
|---|---:|---:|---:|
| permissions.py | 63 | 0 | 100% |
| report_generator.py | 95 | 7 | 93% |
| adb_setup.py | 81 | 50 | 38% |
| tools_manager.py | 256 | 161 | 37% |
| scanner.py | 1033 | 822 | 20% |
| ui_styles.py | 144 | 116 | 19% |
| dependency_checker.py | 75 | 59 | 21% |
| auto_setup.py | 34 | 26 | 24% |
| digital_forensics.py | 588 | 523 | 11% |
| main.py | 983 | 925 | 6% |
| **TOTAL** | **3352** | **2689** | **20%** |

Interpretation: the pure analysis/decision layers are well anchored (the exact layers Stage 03 extracts), while interactive menus and rich-UI paths are not yet exercised — that coverage arrives with TUI/desktop service decomposition (Stages 05–12), not by writing brittle UI tests against legacy print flows. Do **not** claim "good coverage" from the 20% number; claim the anchored surfaces instead.

## 7. Stage 02 suite facts

- **106 passed, 7 xfailed, 0 skipped** (pytest 9.0.3, Python 3.12, Windows).
- Runtime < 2 s; no device, no network, no root; all artifacts under pytest temp dirs.
- All 11 legacy modules byte-compile (`test_syntax_baseline.py`).

## 8. Known expected failures (strict xfails, all mapped to remediation rows)

`xfail_strict` is ON: when remediation flips behavior, the XPASS becomes a hard failure and the stage must remove the marker and update the plan row.

| Test | Defect | Owning stage |
|---|---|---|
| `TestR01...::test_required_single_definition` (duplicate `admin_operations_menu`) | R-01 | 03 |
| `TestR02...::test_required_typed_error_on_malformed_config` | R-02 | 03 |
| `TestTarExtraction::test_required_tar_traversal_prevention` | R-11 | 03 |
| `TestR04...::test_no_sensor_data_means_no_invented_rows` | R-04 | 08 |
| `TestR05...::test_failed_detection_must_not_report_root` | R-05 | 08 |
| `TestR06...::test_credential_patterns_are_actually_applied` | R-06 | 08 |
| `TestR07...::test_requirement_byte_safe_binary_extraction` | R-07 | 08 |

Characterization-only defect records (passing tests that document current buggy behavior, never bless it): R-01 dup-definition count, R-02 redefinition map, R-03 silent `extract_call_logs` failure, R-04 fabricated sensor dict equality, R-05 optimistic `is_rooted is True`, R-06 "patterns present but zero usages", R-07 byte-corruption mechanism, R-10 `shell=True` presence, tools-manager leftover-archive cleanup gap, stale scrcpy v2.4 fallback URL.

## 9. Guidance for adding tests (Stages 03–16)

1. New services in Stage 03+ live beside a faked transport: write tests against `AdbClientProtocol` fakes, not `monkeypatch`ed globals, when the new code allows constructor injection.
2. Golden files produced in Stage 02 (report suite) are the byte-stability baseline for Stage 03 parity — extend them, never regenerate silently.
3. Every remediated defect: remove the xfail marker in the same commit as the fix, add the code-behavior test, and update `SECURITY_AND_REMEDIATION_PLAN.md` + this section.
4. Pure functions added to `vscanner/core/` are unit-testable without fixtures; services need the fake transport; UI stages (05+) use headless harnesses (Textual run tests, Qt offscreen platform) — never interactive.
5. Keep the no-device/no-network/no-root promise: any test needing hardware must live in an opt-in marker (`@pytest.mark.hardware`) and default-skip; none exist yet.
6. When the test count changes materially, update §7 and `PROGRESS.md` in the same stage.
