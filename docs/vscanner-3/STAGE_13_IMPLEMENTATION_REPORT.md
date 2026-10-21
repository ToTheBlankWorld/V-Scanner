# Stage 13 Implementation Report — Desktop motion, accessibility and UI polish

Branch `main`, baseline `80fbc19` (Stage 12 completion, pushed and verified).
This stage delivered a **small, coherent improvement set** over the existing
desktop architecture: no feature rewrites, no new frameworks, no Stage 14
work, no functional changes to any service contract.

---

## 1. Audit findings and the decisions taken from them

Repeated reads + greps of `ui_desktop/` (theme, widgets, shell, app entry,
all 14 screens, the settings dialog) before touching anything produced these
facts; every implemented change traces to one of them:

| # | Finding (verified) | Decision |
|---|---|---|
| A1 | Focus visibility was inconsistent by control class: `QLineEdit`/`QPushButton`/`QTabBar`/table items had accent `:focus` rules, but **no QPlainTextEdit/QTextEdit rules and no QComboBox rules at all** (5 `QComboBox`es exist in `scan.py` ×4, `reports.py` ×1) | New QSS for both control classes (§2) |
| A2 | Horizontal `QScrollBar` was unstyled while vertical was fully styled | Mirrored horizontal rules (§2) |
| A3 | Dialog default buttons (`QDialogButtonBox` OK) had no distinguishing style despite `setDefault(True)` | `QPushButton:default` accent outline (§2) |
| A4 | Inline feedback colors were ad-hoc fragments scattered in `dashboard.py:156`, `reports.py:459/465`, `settings_dialog.py:98` | Centralized `theme.feedback_qss(kind)`; all four call sites refactored (§2) |
| A5 | QLineEdit placeholder color unreachable via QSS | Palette `QPalette.PlaceholderText` from `TEXT_MUTED` in `app.py` (§2) |
| A6 | `widgets.button()` only set an accessible name when a tooltip or explicit name existed | Always set (auto `"{text} button"` fallback) (§4) |
| A7 | Dynamic state banners (labels whose text changes at runtime) sit with empty/stale auto-derived accessible names: mirroring ×4, monitoring ×2, dashboard ×1, demo ×1, reports export ×1, settings validate/error ×2 | Stable accessible names on exactly those labels (§4) |
| A8 | Admin/cleartext confirmation dialog buttons had no explicit accessible names | Honest names incl. "Cancel — dispatches nothing" (§4) |
| A9 | Navigation switched sections instantly with no transition; no reduced-motion surface existed anywhere | New `ui_desktop/motion.py` with OS-level reduced-motion detection + one-shot navigation fade (§3) |
| A10 | WCAG-AA text contrast of the DARK tokens was never measured | Measured: **TEXT_MUTED (3.07–3.89:1) and white-on-primary-button (3.28:1) FAILED AA**; both retuned + automated contrast matrix added (§2.1) |
| A11 | Light theme does not exist (Stage 09 dark-first decision) | Documented as N/A; no visual regressions expected; not in scope |
| A12 | Dialogs use `setFixedWidth(520)` (`devices.py:376`, `forensics.py:249`) vs a 960×640 minimum window | Kept — 520 ≪ 960, no clipping possible; regression-locked in tests |
| A13 | No icon-only controls exist anywhere in the desktop | No text-alternative work needed; documented |

Explicitly **not** done (with reasons): QSS `QComboBox::down-arrow` /
`QCheckBox::indicator` styling — styling pseudo-elements switches off native
Fusion rendering and requires shipping images; the native arrow/indicator and
their native focus behavior remain intact (asserted in tests). No global QSS
selectors beyond the new control-class rules (scope kept narrow, verified by
the full-suite runs).

---

## 2. Design-system changes (all colors still live only in `ui_desktop/theme.py`)

### 2.1 Contrast audit and token retunes (A10)

Automatable WCAG 2.x relative-luminance math over the token matrix:

| Pair (before Stage 13) | Ratio | Verdict |
|---|---|---|
| TEXT_PRIMARY on SURFACE/ELEVATED/WINDOW/SELECTION | 10.5–15.0:1 | AA ✓ |
| TEXT_SECONDARY on SURFACE/ELEVATED | 5.86–6.67:1 | AA ✓ |
| TEXT_MUTED on SURFACE/ELEVATED | 3.07–3.50:1 | **AA ✗** |
| TEXT_ON_ACCENT (white) on primary fill `#5B8AF5` | 3.28:1 | **AA ✗** |
| ACCENT on SIDEBAR/SURFACE (identity/decorative) | 4.87–5.20:1 | AA ✓ |
| SUCCESS/WARNING/INFO/ERROR on SURFACE | 4.76–7.10:1 | AA ✓ |

Retunes (same hue families, visually gentle, both regression-locked):

* `TEXT_MUTED`: `#6E7686` → `#8A93A6` (4.55:1 on ELEVATED, 5.18:1 on
  SURFACE, 5.76:1 on WINDOW — AA everywhere, still measurably behind
  `TEXT_SECONDARY` so the readability hierarchy is preserved).
* Primary interactive fill split out of the identity accent:
  `ACCENT` (`#5B8AF5`) stays for decorative/identity roles (focus ring,
  brand mark, chip glyphs, scrollbar); new tokens
  `ACCENT_CONTROL #3E6ED8` / `ACCENT_CONTROL_HOVER #4171DB` /
  `ACCENT_CONTROL_PRESSED #3A63C6` drive the primary button ramp
  (white label 4.74 / 4.56 / 5.56:1 — AA on every state).

New test class `TestStage13Contrast` locks the full matrix (primary,
secondary, muted, all three muted surfaces, the three button states, the
four status colors as text, brand-mark positions, and the
muted-below-secondary hierarchy).

### 2.2 QSS / palette additions (A1–A5)

`theme.build_app_stylesheet()` gained: `QPlainTextEdit, QTextEdit` rules
(with focus/disabled states), `QComboBox` + its popup
(`QComboBox QAbstractItemView`; native arrow untouched),
`QPushButton:default` accent outline, horizontal scrollbar rules mirroring
the vertical ones. `app.py` applies `QPalette.PlaceholderText = TEXT_MUTED`
(QSS cannot style placeholder text; the palette can). Deliberate
non-overrides asserted in tests: `"QComboBox::down-arrow"` and
`"QCheckBox::indicator"` do NOT appear in the stylesheet.

`theme.feedback_qss(kind)` maps `success|warning|error|info` → semantic
token fragments; unknown kinds raise `ValueError` (no silent fallback).
Refactored call sites: `dashboard.py` (config-read error),
`reports.py` (export ok/failed), `settings_dialog.py` (error label).

---

## 3. Motion and reduced motion (A9)

New module `ui_desktop/motion.py` (69 statements, coverage 90%), the single
home of application motion policy:

* `reduced_motion()` — resolution order: explicit
  **`VSCANNER_REDUCED_MOTION` environment override** (`1`/`true`/`yes` →
  reduce; `0`/`false`/`no` → allow; anything else falls through), then the
  **OS accessibility preference** via
  `QApplication.styleHints().accessibility().motionPreference()`
  (`Qt.MotionPreference.ReducedMotion`) — the Qt 6.12 API that is populated
  from OS accessibility settings on **Windows, macOS and GNOME** (Qt
  change-note verified). Runtime-verified against the installed PySide6
  6.12.0 (offscreen: `NoPreference`; both attribute and the
  `motionPreferenceChanged` signal present). Older bindings degrade to
  environment-only detection (defensive `getattr`).
* `fade_in(widget)` — ONE short (140 ms) opacity fade, Qt-owned
  (`QPropertyAnimation` on the normal event loop — no timers, no threads,
  no GUI-thread blocking); `OutCubic` easing; effect **removed on
  completion** so long-lived pages return to native rendering; restart-safe
  (a second call stops the previous animation and replaces the effect; the
  stale handler can never remove a newer effect — the guard is an identity
  check plus a widget-side bookkeeping property `_vsMotionFade`);
  returns `False` without touching the widget when reduced motion is active.

Integration (`main_window.py::switch_to`): the fade runs **only on genuine
user navigation** — not on the constructor's initial switch (window still
hidden), not on a same-section re-selection, never under reduced motion.
Never the sole state signal (state keeps text + glyph + status bar copy),
never fabricated progress, security confirmations and errors have no motion
at all. `QApplication` shutdown is unaffected (animation dies with its
owner widget).

---

## 4. Accessibility pass — performed vs unverified (practical, no WCAG claim)

**Performed and regression-locked in `test_stage13_desktop.py`:**

* `widgets.button()` always exposes an accessible name (auto
  `"{text} button"`; explicit wins) — every button in the app now has one.
* Stable accessible names on the dynamic state banners: mirroring
  (`devices/target/tool/lifecycle` banners), monitoring
  (`devices/scope` banners), dashboard (ADB tool status), demo (dataset
  status), reports (export status), settings (validation result, error).
* Honest names on destructive-dialog buttons:
  `AdminConfirmDialog` Proceed = `"{op_word} {package} proceed"`, Cancel =
  `"Cancel — dispatches nothing"`; `CleartextConfirmDialog` Proceed =
  `"Write clear-text PSKs proceed"`, Cancel = `"Cancel — writes nothing"`.
* Real-dialog Escape semantics (QTest key events): Admin confirm
  (armed Proceed + Esc ⇒ **rejected, never accepted**, no accepted
  emission), cleartext confirm (Esc ⇒ rejected; accept is the only
  dispatch channel), settings (Esc edits an altered path ⇒ **rejected,
  config file byte-identical — never saved**).
* Keyboard/focus: initial focus reaches the nav rail after `show()`
  (offscreen) and the rail is StrongFocus; findings/devices tables keep
  StrongFocus; navigation/re-selection/rebuild (`_invalidate_dashboard`)
  semantics re-locked.
* Contrast matrix (§2.1) — the only WCAG item asserted automatically.
* Dialogs fit the minimal window: 520 px fixed-width confirm dialogs vs
  the unchanged 960×640 minimum (asserted).

**Desktop surface already covered by earlier stages and NOT regressed:** Qt
native Fusion focus rings for `QCheckBox`/`QRadioButton` (native
rendering kept — see §1), tooltips on non-obvious actions, glyph+label
status chips (never color alone), selectable metadata/evidence text
(`TextSelectableByMouse`), honest-word copy (Stage 12 parity strings
untouched — the locked wording tests re-ran green).

**Not performed — recorded honestly:**

* **No assistive technology tested.** Full screen-reader conformance is
  NOT claimed. Accessible names/descriptions were verified at the Qt
  accessibility-object property level only (`accessibleName()`).
* **No real-window visual verification on Windows.** This environment runs
  Qt offscreen only; no screenshots were taken or archived (the
  ACCEPTANCE_CRITERIA "[M] manual checklist screenshots archived under
  `docs/vscanner-3/qa/`" item remains [M], unperformed here).
* Windows "reduce motion" OS flip was not exercised live (the Qt API
  contract is runtime-verified; the environment override is tested).
* High-DPI/larger-font scaling was not exercised on a real display (Qt 6
  default DPI handling applies; no fixed pixel coordinates beyond the two
  audited 520 px dialog widths).
* Light theme N/A (only the dark theme exists by design).

---

## 5. Screen-by-screen review (shared fixes; no screen rewrites)

| Screen | Stage 13 deltas |
|---|---|
| Shell/nav | 140 ms content fade on user navigation only (reduced-motion aware, restart-safe); no initial-switch fade; no duplicate subscriptions (Stage 12 locks re-ran green) |
| Dashboard | feedback color via helper; ADB tool status banner named |
| Devices | `AdminConfirmDialog` button accessible names; combo/QSS generalization applies |
| Scan | 4 combos now styled consistently (box+popup, accent focus ring); findings filter inputs already named |
| Reports | export state colors via helper; export status banner named |
| Monitoring | discovery + scope banners named |
| Forensics | cleartext dialog button names; evidence styling (multi-line QSS) applies |
| Mirroring | 4 status banners named; combos n/a |
| Demo | dataset-status banner named; page-level "Demo data" name re-locked |
| Admin (in Devices) | dialog grid §2; confirm typed-exact gate untouched |
| Settings dialog | error/validation labels named + helper-driven colors |
| Doctor/Help/Placeholder | no changes needed (static headings auto-derive names; page-level names exist) |
| Window sizing | minimums unchanged and re-locked (960×640); no new fixed coordinates |

Demo appearance honesty was re-checked: the demo banner remains the
textual `[DEMO]` labeling (text+color, never color alone) — no visual
similarity risk introduced by Stage 13.

---

## 6. Tests added (`tests/unit/test_stage13_desktop.py`, 37 tests)

Theme/QSS/feedback-helper/placeholder-palette/window-minimums (6), contrast
matrix (7), motion (5: short duration bound, env-override precedence over
the platform, fade lifecycle incl. effect removal + bookkeeping, reduced
refusal, noop guards, restart safety), shell (7: initial no-fade,
navigation single-fade cleanup, same-section no-refade, reduced-motion
navigation no-fade, rebuild intact, nav-rail initial focus, table focus
policies), accessibility (8), real-dialog Escape semantics (4). No
screenshots, no sleeps — `pump_until` predicate-driven only.

**Existing-suite fix investigated, not masked** (§7).

---

## 7. Intermittent Stage 12 flake — investigation and resolution

`TestMonitoringPage::test_poll_session_streams_snapshots_on_gui_thread`
failed in 2 of 4 instrumented coverage runs (never in 7 plain runs) with
"snapshot delivery must land on the GUI thread exactly once". Investigation
against the actual mechanics:

* The poll session streams one typed snapshot per 2.0 s tick by design;
  `pump_until`'s post-predicate drain (`qapp.processEvents()`) can, under
  coverage tracing overhead, drain tick 2 queued behind tick 1 in a single
  event-loop iteration — two REAL, distinct, correctly-delivered snapshots.
* The old assertion `idents == [GUI_THREAD]` therefore asserted a
  test-timing coincidence (that the pump exits before tick 2), not a
  product property. The per-event exactly-once contract is owned and
  asserted by the Stage 10 bridge tests.
* Fix: the assertion now checks what the test name promises —
  `idents` non-empty, **every delivery on the GUI thread** (`set(idents) ==
  {GUI_THREAD}`), **and** bridge fan-out consistency
  (`len(idents) == page._poll_count`, one delivery per counted snapshot).
  This is strictly about delivery LANE and consistency; no product code
  was changed for this; no assertion was weakened where a product
  guarantee exists.

Post-fix: the module passes 62/62, and two consecutive full instrumented
runs are green where the flake previously appeared.

---

## 8. Performance and lifecycle safeguards

* Fade runs only during user navigation; ≤140 ms; one effect per widget;
  effect deleted on completion; no global raster transparency persists; no
  timers/threads created; shutdown unaffected (animation parented to the
  page widget).
* No duplicate signal connections introduced (navigation subscription locks
  re-run green; fade bookkeeping lives on the widget as a dynamic property).
* No blocking operations added to the GUI thread; all services untouched;
  shared engine free of UI imports (unchanged).
* QSS additions are control-class scoped (`QComboBox`, `QPlainTextEdit,
  QTextEdit`, `QPushButton:default`, horizontal scrollbars) — no
  unrelated-selector blast radius (full suite re-run proves behavior).
* Bounded rendering/pagination (findings 100-row pages, history counters)
  untouched.

---

## 9. Quality gates — exact commands and observed results

| Gate | Command | Result |
|---|---|---|
| Full suite (plain, fresh process) | `python -m pytest tests -q` | **864 passed, 0 failed, 0 xfailed, 0 skipped** (38 files) ×2 fresh-process runs (91.26 s, 85.24 s) post-final-code; two earlier runs pre-contrast-retune were 857 passed ×2 |
| Full suite (instrumented, fresh process) | `python -m pytest tests -q --cov=vscanner --cov=ui_terminal --cov=ui_desktop --cov=cli --cov-report=term` | **864 passed** ×2 consecutive runs (136.03 s, 134.57 s); TOTAL **74%** (13854 stmts) |
| Pre-fix flake record | see §7 | the same instrumented job flaked 2× before the §7 fix; never after |
| Ruff | `python -m ruff check .` | All checks passed |
| mypy | `python -m mypy` | **Success: no issues found in 123 source files** (was 121 pre-stage) |
| compileall | `python -m compileall -q ui_desktop vscanner tests` | exit 0 |
| Desktop smoke | `python -m ui_desktop --smoke` (offscreen) | `DESKTOP_SMOKE_OK` |

No assertion was weakened and no threshold lowered. The only existing-test
change is the §7 assertion repair (which additionally nets a
fan-out-consistency assertion that did not exist before).

---

## 10. Coverage

Same measurement as Stage 12; TOTAL **74%** (13854 statements). Stage 13
anchors:

* new `ui_desktop/motion.py` **90%** (misses are the defensive
  RuntimeError/older-binding guards by design)
* `ui_desktop/theme.py` **98%**, `main_window.py` **94%**,
  `settings_dialog.py` **98%**, `screens/dashboard.py` **94%**,
  `screens/devices.py` **90%**, `screens/monitoring.py` **90%**,
  `screens/mirroring.py` **88%**, `screens/reports.py` **87%**,
  `screens/forensics.py` **85%**, `screens/demo.py` **83%**,
  `app.py` 52% (entry-point category, unchanged since Stage 09),
  `widgets.py` 77% (page-state classes exercised via screens).

---

## 11. Files changed (complete list; staged diff inspected)

* `ui_desktop/theme.py` — tokens (TEXT_MUTED retune, ACCENT_CONTROL ramp),
  feedback_qss, QSS additions
* `ui_desktop/app.py` — placeholder palette role
* `ui_desktop/widgets.py` — button() accessible-name fix
* `ui_desktop/motion.py` — NEW
* `ui_desktop/main_window.py` — navigation fade hook
* `ui_desktop/screens/{dashboard,reports,monitoring,mirroring,demo,devices,forensics}.py`,
  `ui_desktop/settings_dialog.py` — helper refactor + accessible names
* `tests/unit/test_stage13_desktop.py` — NEW (37 tests)
* `tests/unit/test_stage12_desktop.py` — §7 assertion repair
* docs: this report, ROADMAP, ACCEPTANCE_CRITERIA, TESTING_STRATEGY,
  PROGRESS
* FEATURE_PARITY_MATRIX — reviewed, **no change** (Stage 13 adds no feature
  cells).

Unrelated pre-existing user items remain untouched and unstaged: modified
`.gitignore`, untracked `cli/python usb_charging_control.py`. No
`android/**`, no machine-local config, no secrets, no generated artifacts.

---

## 12. [M] / [UNVERIFIED] limitations carried forward

* Real-window (non-offscreen) visual review on Windows incl. the fade in
  practice — [M], unperformed (no such environment here). Stage 14's
  installer/VM runs are the natural follow-up host for it.
* Assistive-technology (screen reader) verification — [M], unperformed; no
  WCAG conformance is claimed.
* Windows OS reduce-motion live flip — [UNVERIFIED] (API contract verified
  at runtime; env override tested).
* Screenshots under `docs/vscanner-3/qa/` — [M], not archived here.
* TUI animations/hints polish clause of the ROADMAP Stage 13 row —
  descoped with rationale: this stage's binding brief scope is the desktop
  experience; the TUI is functionally complete and its UX-copy/inventory
  polish was delivered in Stages 05–08. Recorded in ROADMAP.
* Contrast math covers text tokens on their actual surfaces; complex
  overlaid states (e.g. stylesheet-composited hover shades on borders) are
  approximated by their component tokens.

---

## 13. Git record

* Code commit: `feat(desktop): polish motion accessibility and UX`
  (source/tests only; staged diff inspected before commit).
* Docs commit: `docs(progress): record Stage 13 completion`
  (PROGRESS, ROADMAP, ACCEPTANCE_CRITERIA, TESTING_STRATEGY + this report).
* Push: HTTPS-only `git push origin main` after both commits; verified via
  `git fetch origin` + `git rev-parse main origin/main` equality and both
  commits present on `origin/main`.
