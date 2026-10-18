# V-Scanner 3.0 — Stage 09 Implementation Report

**Stage:** 09 — Desktop foundation and design system (PySide6)
**Scope:** Working PySide6/Qt-Widgets application shell: design system, main window, navigation registry, reusable components, settings dialog, Qt job bridge (wired seam), app entry point, offscreen test harness, architecture guard evolution.
**Status:** COMPLETE (code commit `058de46`, docs commit recorded below).
**Date:** 2026-10-18
**Branch:** `main` (base `512ad8e`, the Stage 08 docs head).

---

## 1. What was delivered

### 1.1 Application entry points

| Launch path | Command | Notes |
|---|---|---|
| Development launch | `python -m ui_desktop` | primary path (Stage 09 report + `__main__.py`) |
| Console script | `vscanner-desktop` (pyproject `[project.scripts]`) | requires the installed `[desktop]` extra |
| Startup smoke test | `python -m ui_desktop --smoke` | forces offscreen platform (unless the environment already chose one), shows the window, closes after 300 ms, prints `DESKTOP_SMOKE_OK`, exit 0 — verified in this stage |

`ui_desktop/app.py` owns the single `QApplication` (`create_application` refuses a second instance with a typed `RuntimeError`), applies the **Fusion** style, and applies the theme stylesheet once at app level. Startup is deterministic and device-free: nothing probes devices, launches processes, or touches the network; missing config is a valid first-run state; unreadable/invalid config renders an honest error state on the dashboard (the `ConfigError`/`OSError` is caught in `bootstrap_window`, never a blank window or a crash).

### 1.2 Package layout

```
ui_desktop/
├── __init__.py          package metadata (APP_NAME/APP_VERSION, boundary statement)
├── __main__.py          python -m launch; honest message when PySide6 is absent
├── app.py               QApplication bootstrap/ownership, Fusion + theme, run()/main()/--smoke
├── theme.py             the single source of desktop design tokens + generated app QSS
├── sections.py          navigation registry (11 sections; live/future/dialog kinds)
├── widgets.py           reusable components (Panel, SectionHeader, StatusChip, MetadataRow,
│                        EmptyState / ErrorState / LoadingState / PlaceholderState,
│                        NavRail, button factory)
├── main_window.py       the shell (QMainWindow): sidebar + header + QStackedWidget + status bar
├── settings_dialog.py   ADB-path editor persisting through ConfigService only
├── jobs_bridge_qt.py    Stage 04 stub (framework-free QtJobBridge) + Stage 09 signal layer
│                        (JobEventSignalHub / QtJobEventBridge / QT_AVAILABLE)
└── screens/
    ├── dashboard.py     live: honest environment-readiness skeleton (config + doctor data)
    ├── doctor.py        live: read-only dependency report (collect_dependency_report; R-14)
    ├── help.py          live: shortcuts table + about + boundaries
    └── placeholder.py   future sections: honest placeholders (no faked content)
```

### 1.3 Design system (`ui_desktop/theme.py`)

The desktop counterpart of `ui_terminal/theme.py`: shared product identity, desktop-appropriate mechanism (Qt stylesheet generation, not terminal CSS). **An AST test (`test_stage09_desktop.py::TestDesignSystem`) enforces that no hex color literal exists in any desktop module other than `theme.py`.**

Token groups (all named constants):

- **Layered surfaces:** `WINDOW_BG → SIDEBAR_BG → SURFACE_BG → ELEVATED_BG` with `BORDER`/`SEPARATOR` hairlines — a restrained dark-first developer/security-tool palette (no gradients, no glow outlines).
- **Text roles:** primary / secondary / muted, plus `TEXT_ON_ACCENT`.
- **Single accent family:** `ACCENT / ACCENT_HOVER / ACCENT_PRESSED` (blue), focus ring = accent.
- **Semantic statuses:** `ok / warning / error / info / neutral` — each with a color **and a textual label** ("OK", "ATTENTION", "FAILING", "INFO", "NOT SET") **and a typographic glyph** (status is never color alone); `STATUS_LABELS` are distinct by test.
- **Typography/spacing/sizing:** `FONT_FAMILY` ("Segoe UI" first with generic fallbacks), size roles (title 18px / heading 14px / body 12px / meta 11px), `SPACING` scale, `CONTROL_HEIGHT`, 4–6px radii, `NAV_WIDTH`, `MIN_WINDOW_WIDTH/HEIGHT` (960×640).
- **Style helpers:** `build_app_stylesheet()` (one QSS string applied once — dynamic-property selectors: `QPushButton[variant="primary"]`, `QListWidget#navRail::item:selected`, `:focus` accent borders, disabled states, subtle scrollbars, busy `QProgressBar`, tooltips); `status_chip_qss(severity)` per-severity styling.

Anti-slop rules honored: no emoji iconography, no decorative titles, no giant gradients, no controls that do nothing (the sidebar's single action button opens the real settings dialog).

### 1.4 Navigation registry (`ui_desktop/sections.py`)

One authoritative table drives the rail, section headers, tooltips, accessible descriptions, and placeholder honesty (mirrors the TUI's `ui_terminal/sections.py` pattern):

| Section | Kind | Owner | Notes |
|---|---|---|---|
| `dashboard` | live | Stage 09 | environment readiness skeleton (real config + doctor state) |
| `devices` | future | Stage 10 | honest placeholder |
| `scan`, `reports` | future | Stage 11 | honest placeholders |
| `monitoring`, `forensics`, `mirroring`, `demo` | future | Stage 12 | honest placeholders |
| `doctor` | live | Stage 09 | read-only dependency report (same service as TUI) |
| `settings` | dialog | Stage 09 | opens `SettingsDialog`; selection unchanged (tracked + tested) |
| `help` | live | Stage 09 | shortcuts (single authoritative `SHORTCUT_ROWS` table) + boundaries |

- `INITIAL_SECTION_ID = "dashboard"` — deterministic startup (asserted).
- Unknown ids raise the typed `UnknownSectionError(LookupError)` **before** any state mutation (test asserts both the raise and untouched state).
- Future sections render "Planned for Stage N" + "This section is not implemented in the desktop shell yet. No functionality, results, or device data is shown or faked here." — asserted per section.

### 1.5 Shell (`ui_desktop/main_window.py`)

- `QMainWindow` with `minimumSize(960, 640)`, layout-driven (no absolute positioning, no docking framework).
- Sidebar: brand block ("V" mark + name + version, all text/theme-driven), `NavRail` (one `QListWidget`, built once from the registry), the real **Settings** action button.
- Content column: `SectionHeader` (title + subtitle; future sections get "— planned for Stage N") + `QStackedWidget` cache — **one content widget per section, built lazily, never rebuilt on revisit** (dedup asserted: revisit returns the same widget instance; stack count stays exact; `section_changed` fires once per real change).
- Status bar: transient honest messages per switch ("Section: Devices (planned for Stage 10 — placeholder)") + permanent version label; settings-unavailable is reported honestly, never silently.
- Settings dialog opens via nav item, button, or `Ctrl+,`; on save the dashboard is rebuilt with the old widget `deleteLater()`-replaced (no leak).
- Keyboard: rail = Tab reach, arrows move, Enter/Space activate (native `QListWidget`; offscreen `QTest`-tested); `Ctrl+,` settings, `F1` help, `Ctrl+Q` close — the help screen renders the authoritative table.
- **Shutdown:** `closeEvent` detaches any attached job bridge, then accepts — deterministic teardown (double-close safe, tested).

### 1.6 Reusable components (`ui_desktop/widgets.py`)

`Panel` (surface frame + `body_layout` convention), `SectionHeader`, `StatusChip` (severity-validated; text+glyph+color), `MetadataRow` (selectable value; accessible value label), `EmptyState`, `ErrorState`, `LoadingState` (indeterminate `QProgressBar` owned by Qt — no custom timers), `PlaceholderState`, `NavRail` (registry-driven; selection guard prevents re-entrant emission; `UnknownSectionError` on unregistered select), `button()` factory (primary/secondary validated). Contrarian scope check: no dead/inert widgets; every component is used by a live screen.

### 1.7 Qt job bridge (Stage 04 stub → Stage 09 wired seam)

`ui_desktop/jobs_bridge_qt.py` keeps the framework-free `QtJobBridge` stub (its contract tests in `test_jobs_bridges.py` are untouched and passing) and adds, guarded by a documented `QT_AVAILABLE` flag (engine-only installs keep module importability):

- `JobEventSignalHub(QObject)` — one typed `Signal` per `event_category()` value (`started/progress/log/finding/snapshot/terminal`) + `any_event`; frozen `JobEvent` objects are carried as-is so no event type drifts from the shared contract (`deliver` rejects unknown categories).
- `QtJobEventBridge` — `attach(manager)`/`detach()` facade with a `(category, producing-thread-id)` trace; **delivery-only**: it creates no threads, timers, or managers (no speculative framework; real job submission is Stage 10).
- **GUI-thread rule proven [T]** (ACCEPTANCE_CRITERIA Stage 09 evidence): a `JobManager` job emits from worker threads; the trace records worker-thread ids while all connected slots ran on the GUI thread via Qt's auto queued connections (`QApplication.processEvents` pump in a real `QApplication` harness). `test_detach_stops_delivery` proves the shutdown half.
- Desktop-side wiring seam documented: Stage 10 connects real managers; the shell's `closeEvent` is the single ownership point (mission §10).

### 1.8 Threading decision (mission §10)

Stage 09 needs no background workers of its own, so none exist yet — no speculative framework was built. The established, tested rule for Stage 10+ integration is: workers live in the Stage 04 `JobManager`; the `QtJobEventBridge` marshals events to GUI-thread slots through queued signal connections; widgets are never touched from worker threads; the bridge is detached on window close. Documented explicitly rather than implemented speculatively.

### 1.9 Settings dialog (`ui_desktop/settings_dialog.py`)

Modal dialog persisting **only** through `ConfigService.save` (SC-11/R-02 — no settings I/O duplicated): pre-fills from the strict snapshot, empty ⇒ clears the saved path, primary Apply / Cancel, `Save` failure (typed `ConfigError`/`OSError`) shows truthful inline error text and keeps the dialog open. Deliberate non-feature documented in-dialog: live ADB validation launches a process — deferred to Stage 10 with device management. Persistence is regression-tested `[T]` (AC Stage 09 evidence).

### 1.10 Accessibility & desktop behavior

- Keyboard: full Tab traversal, named controls (`accessibleName` on the rail, section titles, status chips, buttons, dialog fields), buddy labels, tooltips (real ones, not decoration).
- Visible focus: `:focus` accent borders on controls and rail items (theme QSS).
- Status/errors always have text (chips; error states; status-bar messages) — never color-only, never hover-only.
- Resizing: min-size enforcement tested (`resize(200,150)` clamps to 960×640); laid out by layouts, DPI handled by Qt's high-DPI defaults in Qt 6 (see §4 known limitations for the [M] item).
- Manual accessibility conformance is **not** claimed: baseline is implemented and code-tested; screen-reader behavior on Windows is an [M] follow-up recorded in §4.

## 2. Dependencies and platform notes

- Added **`PySide6>=6.12,<7`** as the optional extra `[desktop]` (pyproject `[project.optional-dependencies]`) — NOT in the core runtime deps; the engine remains importable and testable without it. Verified installed in this stage: PySide6 6.12.0 (+ shiboken6/essentials/pdf/addons/webengine wheels) on Python 3.12.10 / Windows.
- Entry point `vscanner-desktop` added; `python -m ui_desktop` prints a single honest instruction line when PySide6 is missing instead of a traceback.
- No other dependency versions were touched; no Qt plugins bundled, no installer work (Stage 14).
- Platform limitation (honest): wheel set is universal for Python 3.10–3.12 on Windows; `requires-python = ">=3.10"` unchanged.

## 3. Architecture guard evolution (documented, test-locked)

- `test_jobs_integration.py::test_bridge_stubs_import_no_gui_frameworks` evolved from the Stage 04 rule ("no PySide6 anywhere in ui_desktop") to the Stage 09 rule (ARCHITECTURE_DECISIONS T-04): **ui_desktop may import PySide6 (its presentation framework) but not tkinter/streamlit/flask/textual/rich; ui_terminal must not import PySide6** — both halves enforced.
- New LocalDesktopTrace tests in `test_stage09_desktop.py::TestArchitecture`: no `subprocess`/`adb` imports or `os.system` anywhere in `ui_desktop`; no `ui_desktop`→`ui_terminal`/`textual` imports; no `ui_terminal`→`ui_desktop` imports; engine (`vscanner/**`) imports neither PySide6 nor ui_desktop; PySide6 imports exist only in `ui_desktop`.
- Engine purity guards (`test_import_architecture.py`: no UI frameworks in `vscanner/**`, incl. PySide6) unchanged and passing.
- pyproject `[tool.setuptools] packages` extended with `ui_desktop` + `ui_desktop.screens`; mypy `files` already included `ui_desktop` (109 files now checked); pytest/coverage already include the package.

## 4. Known limitations and deferred functionality (honest)

| Item | Status | Owner |
|---|---|---|
| Binary app icon (`.ico`/`.icns`) | Deliberately not committed (generated binary; packaging is Stage 14); brand mark is a themed text "V" drawn by the shell | Stage 14 |
| High-DPI verification on real Windows displays | Qt 6 defaults handle scaling; offscreen tests assert only min-size/layout invariants; no screenshot campaign ([M] item; nothing claimed) | Stage 13+ |
| Windows 10 + 11 launch profiles | [M]: this environment ran only the offscreen harness + code smoke; real-window launch needs physical verification | manual |
| Screen-reader (UIA) conformance | Baseline accessible names/focus implemented and code-tested; assistive-tech behavior unverified | Stage 13 |
| ADB path validation in settings | By design deferred: launches a process; arrives with Stage 10 device management | Stage 10 |
| Device workspace / scanning / findings / reports / monitoring / forensics / mirroring / demo on desktop | Placeholders by design | Stages 10–12 |
| Motion/polish palette review | Stage 13 owns UX polish (design tokens are review-ready there) | Stage 13 |
| `ui_desktop/__main__.py` coverage | Uncovered by design (thin launcher; safe module import is via subprocess smoke `--smoke`) | — |

## 5. Quality gates (exact results)

| Gate | Command | Result |
|---|---|---|
| Full suite ×2 | `python -m pytest tests -q` | **640 passed, 0 failed, 0 xfailed, 0 skipped** (34 files) — run 1 ≈ 59 s; run 2 under coverage instrumentation ≈ 93 s, identical counts, TOTAL coverage **68%** |
| Desktop offscreen tests | subset including `tests/unit/test_stage09_desktop.py` | **38 passed** (startup/lifecycle 8, navigation 10, design system 9, settings 5, bridge 3, architecture 5 — approx class counts) |
| Architecture/import guards | `test_import_architecture.py` + `test_jobs_integration.py` | **61 passed** |
| TUI/CLI/bridge regression | `test_tui_app.py`, `test_tui_entry.py`, `test_jobs_bridges.py` | **37 passed** (TUI runtime and the untouched Stage 04 stub contract unaffected) |
| Lint | `python -m ruff check .` | All checks passed (scope unchanged: `cli`, `android` excluded) |
| Types | `python -m mypy` | Success: no issues found in **109 source files** (was 96; +13 desktop modules — note: `[tool.mypy] files` already contained `ui_desktop` from Stage 04) |
| Byte-compile | `python -m compileall ui_desktop ui_terminal vscanner tests` | exit 0 |
| Desktop startup smoke | `python -m ui_desktop --smoke` | `DESKTOP_SMOKE_OK`, exit 0 (offscreen) |
| Coverage detail (ui_desktop) | `python -m coverage report` | theme 98%, settings_dialog 100%, screens 89–100%, main_window 89%, widgets 81%, jobs_bridge_qt 92%, app.py 48% (exec-loop paths run only in real `exec`), `__main__.py` 0% (thin launcher; smoke-run externally) |

No gate was skipped. No device, root, network, or ADB was required for any test.

## 6. Textual/Qt 6.12 pitfalls recorded for Stage 10+

- `QApplication.instance()` is typed `Optional[QCoreApplication]` — cast for typed reuse.
- `QApplication.exec()` vs `QCoreApplication.exec` parameter quirk: `app.exec()` takes no args on PySide6.
- Dynamic-property QSS needs `setProperty` before polish (sometime re-polish on later changes) — set variants at construction.
- Offscreen focus needs `show + activateWindow/setFocus + processEvents` before `QTest.keyClick` lands.
- Signal over `object` slot side channels: connect a callable that appends; tuple-returning lambdas are valid.
- `QWidget.resize()` immediately clamps to minimum size — usable as a determinism assertion without an event loop.
- Keep Qt imports out of module import paths for engine-only runs: `QT_AVAILABLE` guard pattern in bridge modules.

## 7. Git record

- Implementation commit: **`058de46`** — `feat(desktop): establish PySide6 application foundation` (17 files, +2480/−36; staged diff inspected: source/tests/metadata only — no binaries, no secrets, no device config; `.gitignore` NOT staged; `cli/adb_config.json` untouched; `cli/python usb_charging_control.py` left untracked; `android/**` untouched)
- Docs commit: *see `PROGRESS.md` commit record after the docs change* — `docs(progress): record Stage 09 completion`
- Push verification: recorded in `PROGRESS.md` (HTTPS only; local `main` == `origin/main` after push).

## 8. Stage boundaries honored (mission compliance)

- Ship only the shell/design/navigation/settings/bridge/tests — device workspace, scanning workflows, findings explorer, reports UI, mirroring, and installer work are NOT started (placeholders are honest).
- The engine consumes no Qt/PySide6 and no Textual; the TUI is independent of PySide6 and of `ui_desktop`; CLI/TUI entry points untouched and regression-passing.
- No new job manager/event bus/threading framework; Stage 04 contracts are the only bridge model; the Qt variant is delivery-only with explicit ownership/shutdown.
- Unrelated user changes preserved untouched throughout.
