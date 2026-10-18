# Stage 05 — Premium TUI Foundation and Visual Design System — Implementation Report

**Stage status: implementation complete, verification green (see §7). Commit + push recorded in PROGRESS.md.**

This stage delivered the Textual 8 application shell: a single-source design-token theme, the navigation registry with live/placeholder sections, the five Stage 05 screens (dashboard, doctor, settings, help, future placeholders), the real command-palette source, the non-interactive launcher guard, packaging (`vscanner-tui` entry point, `textual>=8.2.8,<9` dependency), and a keymap/design-token document verified against the actual bindings. The engine (`vscanner`) stays framework-free; the legacy CLI is untouched and remains fully available.

---

## 1. Deliverables

### 1.1 Design system (`ui_terminal/theme.py` — single token source)

- One module owns every color: theme constants, the registered `Theme` object `VSCANNER_THEME` (name `vscanner-dark`), and the TCSS fragments `APP_TCSS` + `SECTION_TCSS` generated from those same constants. No screen module contains a raw color value.
- Custom tokens `$vs-muted` and `$vs-rail-width` ride in `Theme.variables`; `App.get_theme_variable_defaults()` returns them so CSS parsing never fails before theme registration (order-independent startup).
- Focus is always a visible frame (`:focus`), never color-only; status semantics are explicit word+class pairs (`status-ok` / `status-warn` / `status-error` / `status-muted`).

### 1.2 Navigation contract (`ui_terminal/sections.py`, `ui_terminal/app.py`)

- `Section` dataclass + `SECTION_REGISTRY`: live sections `dashboard` (key `d`), `doctor` (`e`), `settings` (`s`), `help` (`f1`); future placeholders `devices`/`scan`/`reports` (Stage 06/07) and `monitoring`/`forensics`/`mirroring` (Stage 08) — each honestly labeled with its owning stage, never fake state.
- All navigation uses `App.switch_screen` with a per-section instance cache (`_screen_cache`): duplicates impossible, per-screen state preserved, screen stack bounded ≤ 2.
- Startup pushes the dashboard onto Textual's internal default screen (`push_screen` in `App.on_mount`); this works around an upstream Textual 8.2.8 constraint (`switch_screen` on the `get_default_screen`-created screen crashes with `IndexError: pop from empty list` because that screen has no result callback). After the initial push, every stack entry carries a callback, so `switch_screen` is always valid.
- `escape` returns to the dashboard as a non-priority binding so the command palette's own escape handling keeps working; typed input (`Input`) consumes printable keys first, so typing `s` in Settings never navigates.
- Command palette: `VScannerCommands(Provider)` builds real entries from the registry (future sections carry the owning stage in their help text) plus "Refresh environment report" and "Quit V-Scanner". Search uses Textual's fuzzy `Matcher`; **empty queries short-circuit to `DiscoveryHit`s before any matcher construction** — Textual 8.2.8's fuzzy scorer crashes on `""` (verified against stock providers too; guarded at our boundary with a defensive `ValueError` catch).

### 1.3 Screens (`ui_terminal/screens/`)

| Screen | Contract | Honesty notes |
|---|---|---|
| `shell.py` | `ShellScreen` base: brand bar, nav rail, status line, footer; `refresh_status()` + `on_resize` responsive rules | Rail hidden < 72 cols (`RAIL_MIN_WIDTH`), tagline hidden < 96 — resize-event driven because Textual 8 has no CSS media queries. |
| `dashboard.py` | Current-section summary, doctor status card (quotes `app.last_doctor_summary` when the doctor ran; "not run yet" otherwise), navigation guidance, future-stage honesty list | No fake device state; device workspace named as a Stage 06 destination. |
| `doctor.py` | Runs `collect_dependency_report()` on entry and on every resume; renders Python/packages rows in a `DataTable` | Report-only: "installs happen only by explicit user action" is displayed; absence states are rendered (e.g. unavailable), never invented. |
| `settings.py` | Read → edit → save → verify through `ConfigService` only; explicit "Validate path" button is the ONLY caller of `check_adb_valid` (a subprocess) | R-08 first-run legacy import is attempted only on a genuinely first run AND only in repo-local dev mode (`VSCANNER_LOCAL`); outcome stated honestly either way; a real user profile never silently absorbs dev-repo values. Unreadable configs surface a typed honest error, never a crash or silent reset. |
| `help.py` | Key tables rendered from `SECTION_REGISTRY` and `GLOBAL_KEYS` constants — the same constants the keymap doc test reads | Cannot drift from actual bindings. |
| `placeholder.py` | `PlaceholderFutureScreen`: "not implemented yet — Stage N" banner, zero fake buttons | Future sections never pretend to act. |

- `ui_terminal/__main__.py` → `ui_terminal.app:main`; `pyproject.toml` adds `[project.scripts] vscanner-tui = "ui_terminal.app:main"`, the `textual>=8.2.8,<9` dependency, and both packages to the setuptools list.
- `main()` refuses non-TTY runs before constructing anything: concise exit-0 message ("this interface is interactive … Nothing was probed and nothing changed … python cli/main.py") — no UI attempt, no probing, no config writes.

### 1.4 Keymap + design-token document

- `docs/vscanner-3/TUI_KEYMAP.md`: navigation table, global keys, responsive thresholds, full token table, accessibility limitations (no screen-reader certification claimed; state always doubled as text). Locked to the code by `tests/unit/test_tui_entry.py::TestKeymapDocumentation` (every binding, section title, global key, and the `RAIL_MIN_WIDTH` breakpoint must appear).

---

## 2. Scope discipline

- Android app (`android/**`): zero modifications.
- Legacy CLI: zero modifications; `python cli/main.py` behavior covered by the unchanged Stage 02–04 regression suites (all green).
- Layering: `ui_terminal` may import Textual/Rich (A-03 refinement in `test_jobs_integration.py::TestLayering`); `vscanner/**` still may not import `ui_terminal`/`ui_desktop`; `ui_desktop` stays framework-free (forbidden list now includes textual/rich there); the generic engine framework-independence suite still passes unmodified.
- No new runtime dependency beyond Textual itself (rich already present at 15.0.0, satisfying Textual's `rich>=14.2` floor; the repo's `rich>=13.0.0` declaration remains valid). No PySide6/Qt, no packaging tooling.
- Pre-existing user items remain unstaged and untouched: modified `.gitignore` (trailing-whitespace hunk) and untracked `cli/python usb_charging_control.py` (and the untracked real `cli/adb_config.json` device config — never staged).
- Startup honesty: nothing probed (no ADB subprocess, no network, no filesystem config IO) until the user acts; the doctor screen is reached only by explicit navigation and its collection is import-scan based; the Settings validate button is the only subprocess path.
- Deliberately deferred: device workspace, scanning, reports, monitoring, forensics, mirroring (Stages 06–08 placeholders only); animation polish (Stage 13); desktop GUI (Stage 09+).

---

## 3. Implementation decisions recorded (for future stages)

1. **`switch_screen` on the default screen is unsafe** in Textual 8.2.8 (no result callback → `IndexError`). Pattern: push the first real screen in `on_mount`, then only `switch_screen`. Do not "simplify" this back to a single `switch_screen` call.
2. **`Matcher.match("")` crashes** (upstream, Textual 8.2.8, also affects stock providers). Any provider must short-circuit empty queries before constructing a matcher; we additionally catch `ValueError` defensively.
3. **No bracket key hints in markup-consuming widgets** (`Button`/`Label`/`Static` parse `[x]` as markup and swallow it; `\[x]` shows a literal backslash). Convention: `title · key` separators; brackets allowed only in `DataTable` cells (they don't parse markup).
4. **Never name a method `_render`** on a `Screen`/`Widget` — it collides with `Widget._render()` in the render pipeline (hard crash). Settings uses `_render_fields`.
5. Responsive collapse is resize-event based (media queries were removed from Textual); thresholds are single constants in `shell.py` mirrored into the keymap doc via test.
6. Tests never touch the developer's real config directory: every TUI test injects a `ConfigService` rooted in `tmp_path`; the real `%LOCALAPPDATA%\vscanner` path is only created by a genuine interactive production launch.

---

## 4. Test additions (33 → 36 Stage 05 tests, all headless)

| File | Coverage |
|---|---|
| `tests/unit/test_tui_app.py` | Startup/theme registration, honest dashboard content, navigation + escape + instance cache (no duplicates), unknown-section feedback via `notify`, every future placeholder honest (no fake action buttons), doctor report-only, focus/tab order, rail/tagline responsive collapse via `pilot.resize_terminal`, palette source search + execution (`ctrl+p`), `ctrl+q` exit code 0, registry contract. |
| `tests/unit/test_tui_services_screens.py` | Config round-trip through the engine (exact JSON `{"schema_version": 1, "adb_path": ...}`), state survives navigation round-trip, unreadable config honest error, validate button only user-initiated (monkeypatched `check_adb_valid`), doctor renders the real engine report rows, doctor honest failure state (monkeypatched `collect_dependency_report` raising), R-08 legacy import: attempted only first-run + `VSCANNER_LOCAL`, honest absence message, never runs in user-profile mode. |
| `tests/unit/test_tui_entry.py` | Non-TTY `main()` (exit 0, concise guidance, points at the real CLI, no probe), `__main__` wiring, pyproject entry-point/dependency/package-list guards, keymap-documentation consistency (bindings, sections, global keys, responsive threshold, accessibility limitations). |

All TUI tests run on Textual's headless `run_test` harness (`pytest-asyncio` auto mode added to `pyproject.toml`). Suite baseline moved 363 → **399 passed, 4 xfailed**.

---

## 5. Guard refinements

- `tests/unit/test_jobs_integration.py::TestLayering::test_bridge_stubs_import_no_gui_frameworks`: `ui_terminal` modules may now import `textual`/`rich` (Stage 05 implementation layer); `ui_desktop` keeps the full forbidden list; PySide6/tkinter/streamlit/flask remain forbidden everywhere.

---

## 6. Non-interactive + startup evidence

- `python -m ui_terminal` with piped stdio: exit 0, one-line honest message, empty stderr.
- Headless no-device launch (injected temp config): **0.097 s** cold `run_test` to rendered dashboard — AC budget ≤ 2 s.
- Navigation smoke: `d`/`e`/`s`/`f1`, `escape` home, placeholder honesty, narrow resize (rail collapse), palette open — all green (scripts kept out of the repo under the temp workspace).

---

## 7. Verification results (exact)

| Gate | Command | Result |
|---|---|---|
| Full suite | `python -m pytest -q` | **399 passed, 4 xfailed** (~22 s; device/network/root-free; xfails R-04…R-07 unchanged, strict) |
| Coverage | `python -m coverage run -m pytest -q` + `report` | **TOTAL 51%** (5838 stmts; up from 47%). Stage 05 anchors: theme/sections/dashboard/help/placeholder **100%**, app 90%, shell 94%, doctor 97%, settings 88% |
| Lint | `python -m ruff check .` | All checks passed |
| Types | `python -m mypy` | **Success: no issues found in 71 source files** (was 57 at Stage 04) |
| Bytecode | `python -m compileall -q ui_terminal tests vscanner` | exit 0 |
| Architecture guards | (within suite) import-cycle, framework-independence, no-`shell=True`, no-pip, layering AST tests | green |
| Startup AC | timed headless launch + non-interactive guard | 0.097 s ≤ 2 s; non-TTY exit 0 |
| Post-commit | suite re-run after the code commit | green (see PROGRESS commit record) |

---

## 8. Risks / follow-ups for later stages

- Stage 06 device screens will reuse `ShellScreen` + the registry; device status bar on the shell stays minimal until real device services are wired (Stage 06 owns it).
- The screen cache keeps instances alive for app lifetime (bounded by the 10 registry entries — negligible); Stage 08 monitoring screens must follow the same pattern rather than spawning duplicates.
- Textual 8.2.8 pinned `<9`; any Textual major bump must re-verify decisions §3.1–3.2 (known upstream crash surfaces).
