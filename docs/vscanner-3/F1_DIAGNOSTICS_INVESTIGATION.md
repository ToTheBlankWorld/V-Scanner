# F-1 Investigation — Packaged Doctor Diagnostics Honesty (2026-10-23)

Resolution of checklist item #24 (finding F-1): the packaged Windows
application's Doctor surface reported a source-environment failure that
does not exist for the packaged executable ("Runtime packages — 1 of 3
present / FAILING", rows `rich NOT INSTALLED`, `click NOT INSTALLED`,
`jinja2 installed`, with the remediation hint "Reinstall the engine
environment (pip install -e .)").

## 1. Final status

**FIXED at the engine + desktop-surface layers and validated on the
final candidate's installed layer.** The defect was diagnosed as a
presentation/semantics defect of the diagnostics, exactly as the
readiness finding recorded: no functional impact, but the diagnostics
screen misled packaged users by (a) reporting CLI-surface packages as
missing/failed even though the packaged desktop executable is complete
by design without them, and (b) offering a source-environment
remediation (`pip install -e .`) that is meaningless for a packaged
app. Investigation side-finding: the first packaged attempt exposed
that Nuitka does not set `sys.frozen` — the frozen detection was
corrected to Nuitka's documented `__compiled__` mechanism and
re-validated (see §7/§8).

## 2. Original finding and reproduction (packaged layer, before the fix)

- Finding source: `RELEASE_READINESS_REPORT.md` §8 (F-1) and
  `RELEASE_CHECKLIST.md` item #24.
- Reproduction on the installed candidate of the previous build
  (standard user, this host): the Doctor page shows
  `Summary: 1 of 3 packages present` with a **FAILING** chip,
  `rich: NOT INSTALLED`, `click: NOT INSTALLED`, `jinja2: installed`,
  and the hint `Missing: rich, click. Reinstall the engine environment
  (pip install -e .). …`. The dashboard's "Engine packages" panel showed
  the same verdict shape. Evidence captured before the fix (UIA dump +
  screenshot, broken-build behavior preserved for the record).

## 3. Root cause and evidence (what the check actually verifies)

- The engine service (`vscanner/services/doctor.py`) probes each runtime
  package with `importlib.util.find_spec(name)` for the three proven
  runtime deps (`rich`, `click`, `jinja2`).
- Repository truth (grep-verifiable, locked by a regression test): the
  compiled-in surface of the packaged desktop exe is
  `vscanner` + `ui_desktop` (the packaging pipeline passes
  `--include-package=vscanner`, `--include-package=ui_desktop` and
  `--nofollow-import-to=cli`, `ui_terminal`, `tests`, `android`).
  Within that surface, the **only third-party runtime import is
  `jinja2`** (reports service). `rich`/`click` are imports of the CLI
  surface (`cli/*.py`) only.
- Therefore in the packaged desktop executable:
  - `jinja2` is compiled in → the probe correctly reports it present.
  - `rich`/`click` are genuinely not part of the desktop build → the
    `find_spec` probe reports absent. In a frozen (Nuitka-compiled)
    build, `find_spec` probing is the wrong instrument anyway (frozen
    packages expose no importlib metadata), so the *column* could not
    even be trusted for packages that ARE compiled in.
- The defect is not the per-row fact ("rich is not importable in this
  executable" is true) but the **semantics attached**: a global FAILING
  verdict + "missing packages" + a source-only remediation for a state
  that is by design. A diagnostics screen that cannot distinguish
  "not needed in this build" from "required and broken" is the honesty
  defect, and the frozen runtime state was never made explicit.

## 4. The fix (smallest justified correction, honest typing of states)

`vscanner/services/doctor.py`:

- `is_frozen()` — true under Nuitka compiled execution (`sys.frozen`).
- Frozen-mode probe `_package_importable()` resolves through the *real
  import machinery* (`importlib.import_module`): in a frozen build this
  is the direct, honest evidence of presence in the executable
  (ModuleNotFoundError ⇒ genuinely not part of this build;
  metadata-free `find_spec` blind-spots no longer apply). Source runs
  keep the established side-effect-free `find_spec` probe unchanged.
- `DESKTOP_REQUIRED_PACKAGES = ("jinja2",)` — the truth embed sanctioned
  by the checklist acceptance ("make the frozen build state explicit in
  Doctor (or embed the diagnostic truth at build time)"; grep-verifiable
  and regression-locked).
- Frozen reports carry an explicit note: runtime packages are compiled
  into the executable; source-environment statuses do not apply.
  Report-only semantics (R-14) preserved in every mode.

`ui_desktop/screens/doctor.py` (Doctor page) and
`ui_desktop/screens/dashboard.py` (Engine packages panel):

- Frozen mode renders the frozen truth:
  - summary becomes `packaged build - N of M compiled in`;
  - per-row states become `compiled into this executable` /
    `not part of this packaged build` (no "NOT INSTALLED"++);
  - the "Engine packages" status chip judges **only the required
    packages**: `ok` for the genuine by-design state (CLI deps absent),
    `error` only if a required package is not importable in the build —
    with an actionable, truthful hint ("Broken build: … must be part of
    this packaged executable but is not importable there — rebuild from
    the approved packaging pipeline");
  - the CLI-absent hint states the by-design truth and that nothing is
    to be reinstalled; no `pip install -e .` remediation is ever shown
    in a packaged build.
- Source mode rendering is unchanged (locked by the "semantics
  preserved" tests): the reinstall hint remains available to source
  users where it is actually applicable.
- The TUI Doctor screen is deliberately untouched: the TUI is not
  packaged (the pipeline `--nofollow`s it), so a frozen TUI build does
  not exist; its source-mode display remains accurate.

## 5. Regression tests

`tests/unit/test_services_doctor.py` (class `TestFrozenRuntimeHonesty`):
- source runs are not frozen (pins the availability of the frozen
  branch);
- `DESKTOP_REQUIRED_PACKAGES` equals the grep-derived engine truth
  `("jinja2",)`;
- frozen probing goes through the real import machinery (import calls
  recorded; simulated frozen-importer refusal for `rich`/`click`);
- frozen reports name the frozen state explicitly;
- report-only (R-14) marker survives frozen mode.

`tests/unit/test_stage09_desktop.py` (class `TestDoctorFrozenHonesty`):
- source-mode Doctor keeps the current verdict + reinstall hint (and no
  hint when all present) — semantics-preservation locks;
- frozen Doctor: `packaged build - 1 of 3 compiled in`, per-row
  `not part of this packaged build`, no `NOT INSTALLED`, no `pip
  install` hint, chip **OK** for the by-design state;
- frozen Doctor with a required package missing: `Broken build` +
  `rebuild` remedy (honest actionable failure);
- frozen Dashboard Engine-packages panel: same truth (+ required-
  missing stays a failure).

## 6. Quality gates (exact)

- Focused service tests: `pytest tests/unit/test_services_doctor.py -q`
  → **12 passed**.
- Focused desktop tests:
  `pytest tests/unit/test_stage09_desktop.py::TestDoctorFrozenHonesty`
  → 6 passed (after the fix; 4 failed first, per the failing-first
  sequence).
- Neighbor regression sweep: `test_stage09_desktop.py +
  test_stage10_desktop.py + test_tui_services_screens.py +
  test_services_doctor.py + test_stage11_desktop.py` → **190 passed**.
- `ruff check .` → exit 0.
- `mypy` → exit 0 ("Success: no issues found in 134 source files").
- `compileall -q …` → exit 0.
- Desktop smoke `python -m ui_desktop --smoke` → `DESKTOP_SMOKE_OK`,
  exit 0.
- Full suite, fresh process → run 1: 1 failed / 991 passed / 2 skipped;
  the single failure is the pre-existing suite-load timing flake family
  in the Stage 11 desktop scan lifecycle
  (`test_duplicate_submission_is_refused_while_active`; standalone
  4/4 green; the F-1 diff touches no scan/job code). Fresh full-suite
  runs and the coverage run are recorded with the commit (see §8).

## 7. Establishing the frozen detection at the packaged layer (empirical)

The frozen detection was **not** assumed. The first candidate used the
conventional `sys.frozen` detection; its installed build still rendered
the source-mode verdict, i.e. the hypothesis "Nuitka sets `sys.frozen`"
was **disproven empirically** on the real packaged layer. Nuitka's own
documentation confirms it: *Nuitka does not set `sys.frozen`* — the
documented run-time detection is the module-level `__compiled__` marker
injected into every compiled module ("Detecting Nuitka at run time",
Nuitka README). The mechanism was independently verified with a minimal
standalone probe compiled by the same Nuitka toolchain
(`"__compiled__" in globals()` true in the compiled executable, absent
from source runs), `is_frozen()` was corrected, and a new candidate was
built and validated for the installed-layer proof below (§8).

## 8. New candidate builds (artifact policy)

The fix lives in `vscanner/services/doctor.py` and
`ui_desktop/screens/{doctor,dashboard}.py` — all compiled into the
packaged binary → candidates were built with the approved pipeline
(`python -m packaging_windows.build_windows`, full
`stage,nuitka,installer` steps, embedded smoke `DESKTOP_SMOKE_OK`, exit
0) into **separate** work directories; the Stage 14 historical
artifacts and the F-2 candidate remain untouched at their original
hashes.

- **work-f1candidate1 (superseded)** — first candidate with the
  conventional `sys.frozen` detection. Its installed layer still
  rendered the source verdict, empirically disproving the
  `sys.frozen` hypothesis on the real packaged layer (the driver of
  §7). exe `82e173aca073765907fd015f8bb0c824bad1ed0d6c928f4068a5d80ae0281dd2`
  (17,179,136 B); installer
  `8489a1e623dcf5949bdbe08c73c7a2053212c146650d40614322ba9b17463f1c`
  (25,022,458 B). **Not** the fixed packaged build; retained for the
  evidence trail.
- Frozen-detection probe (same Nuitka 4.3.1 toolchain, minimal
  standalone module): `sys.frozen` absent in the exe;
  `"__compiled__" in globals()` true in the compiled module — the
  documented Nuitka mechanism (`is_frozen()` correct as committed).
- **work-f1candidate2 (final, validated)** — corrected `is_frozen()`.
  exe `6b6d7242f064a41e01e4766f20f3b005a365ce9586f70434c1ca3f749cdb892b`
  (17,179,648 B); installer
  `05568f84492af3bace0a23cba54002fd375764dccb9b4d040968713748c95289`
  (25,020,269 B).
- Preserved earlier hashes (re-hashed this phase, byte-unchanged):
  F-2 candidate installer
  `1a9f315f5ee6e70f933908fcd8a58530613b3c574988c0bc61bcc2658459e5cb`,
  historical exe
  `1bf3eb42fa0fb5007e8c8b8f4b6c54db9cb76a4fcb7569cdabd1ebae2b27c637`
  (17,127,936 B), historical installer
  `ac9229aedb574ec052686779b864fb95d592b218133365f7b93bb2245dae25bc`
  (25,010,550 B).

Installed-layer validation (final candidate, affected host, standard
user, real saved configuration untouched):

1. Silent install (`/VERYSILENT /SUPPRESSMSGBOXES /NORESTART`) → exit
   0; the on-disk exe re-hashed **byte-identical to the candidate exe**
   (`6b6d7242…892b`).
2. Fresh launch: the Dashboard "Engine packages" panel rendered the
   frozen truth — `Report: packaged build - 1 of 3 compiled in`,
   rich/click rows `not part of this packaged build`, `jinja2` row
   `compiled into this executable`, status chip **OK**, and the
   by-design hint ("rich, click belong to the CLI surface only …
   nothing to reinstall") — with **no** FAILING verdict and **no**
   `pip install` remediation (screenshot + UIA dump recorded).
3. The Doctor page (rail-walk driven non-invasively) rendered the same
   truth: `Summary: packaged build - 1 of 3 compiled in`, chip **OK**,
   per-row honest states (screenshot + UIA dump recorded).
4. The application closed gracefully (CloseMainWindow; no force kill).

Post-fix source gates (exact):

- Full suite, fresh process, run 2 → **992 passed, 2 skipped**
  (0:02:47, exit 0).
- Full suite, fresh process, run 3 → **992 passed, 2 skipped**
  (0:02:44, exit 0).
- Full suite + coverage → **992 passed, 2 skipped**, TOTAL 75%
  (0:04:51, exit 0).
- Stage 16 doc-contract + lockfile tests → **22 passed** after all
  documentation updates; no machine-local drive paths in any committed
  document.

## 9. Remaining limitations

- The real "required package missing from the build" state cannot be
  produced in a real candidate (a broken build is not constructible in
  the approved pipeline); that honesty path is covered by regression
  tests at the source layer.
- The candidate pipeline runs its own validated staging + content
  checks + smoke on this build; the F-2 ADB installed-layer probe was
  not re-driven in this F-1 window (the F-2 fix's installed-layer
  evidence stands on its own candidate validation). No other diagnostic
  checks were found relying on source-tree or pip metadata in the
  packaged exe beyond the Doctor/package rows fixed here.
- Reproduction evidence artifacts (screenshots/UIA dumps of the
  broken and fixed packaged Doctor/Dashboard) live on the validation
  host's temp evidence folder; the committed document records their
  textual contents rather than storing binaries in the repository.

## 10. Recommended F-1 disposition

Checklist #24 (F-1): **PASS** for the candidate build — frozen-state
explicit, statuses honest, remediation actionable and truthful. The
historical Stage 14 artifacts (and the F-2 candidate) remain recorded
with their own hashes and do not contain this fix; publication must use
the newest validated candidate hashes, and the release disposition
stays NOT READY until the standing owner decisions and publication
authorization are resolved.
