# V-Scanner 3.0 — TUI Keymap & Design Tokens (Stage 05)

This document is the human-readable contract for the Stage 05 terminal
interface. The screen-level tests (`tests/unit/test_tui_entry.py`,
`tests/unit/test_tui_app.py`) verify it against the *actual* navigation
registry and app bindings, so it cannot silently drift from the code.

- Launch: `vscanner-tui` (installed entry point) or `python -m ui_terminal`.
- Non-interactive terminals: the launcher prints a short explanation and
  exits 0 without attempting any UI, probing, or configuration changes;
  the legacy CLI (`python cli/main.py`) remains available.
- The TUI is presentation-only: all state lives in `vscanner` services
  (`ConfigService`, doctor report). Nothing is started automatically.

## Navigation destinations

| Key | Destination | Status |
|-----|-------------|--------|
| d | Dashboard | live (Stage 05) |
| w | Device workspace | live (Stage 06) |
| e | Doctor | live (Stage 05) |
| s | Settings | live (Stage 05) |
| f1 | Help & keys | live (Stage 05) |
| — | Scanning & findings | placeholder · Stage 07 |
| — | Reports & history | placeholder · Stage 07 |
| — | Live monitoring | placeholder · Stage 08 |
| — | Forensics | placeholder · Stage 08 |
| — | Mirroring & demo | placeholder · Stage 08 |

Placeholder screens are honest: they show an "not implemented yet" banner
with the owning roadmap stage, never fake device state or pretend controls.
Pressing escape from any screen returns to the Dashboard.

Command palette entries mirror this exact list (with the owning stage named
for future sections) plus "Refresh environment report" and
"Quit V-Scanner".

## Device workspace keys (Stage 06)

| Key | Action |
|-----|--------|
| r | Refresh the device list (explicit; opening the screen runs exactly one discovery) |
| enter / space on a device row | Select that device (never implicit when several are connected) |
| a | List installed apps for the selected device (cancellable job) |
| t | Toggle system apps on/off for the next listing |
| c | Cancel the running app listing |
| [ / ] | Previous / next inventory page (100 apps per page) |
| (filter input) | Narrow the app list by package or label while typing |

Honesty behavior in the workspace (also enforced by tests):

- No automatic refresh: only opening the screen (once) and pressing `r`
  run the single `adb devices` discovery command.
- A failed refresh keeps the last successful list on screen, explicitly
  marked "may be stale" — it never masquerades as a fresh result.
- Devices that are offline, unauthorized, or in recovery are listed with
  plain state words and are refused as selection targets with an
  explanation (details need an authorized, connected device).
- The details panel prints "unknown" for values the device did not report
  and "not determined" for root state — the engine's verified probe is a
  Stage 08 deliverable, so nothing claims rooted or not-rooted today.
- No phone-number row is displayed: the engine deliberately does not
  expose one (the legacy CLI showed a hardcoded `N/A` placeholder).
- App labels are derived from package names and are badged
  `derived (heuristic)` — no exact-label claim is made.
- Device info reflects configuration reads and is never presented as a
  security assessment.

## Global keys

| Key | Action |
|-----|--------|
| ctrl+p | Command palette — filter and run available actions |
| ctrl+q | Quit the application |
| escape | Return to the dashboard from any screen |
| tab / shift+tab | Move focus between controls (visible focus frame) |
| enter / space | Activate the focused control |

Binding precedence: a focused text input consumes printable keys first, so
typing `s` inside the Settings adb-path input never triggers navigation.
Standard Textual bindings (`ctrl+q` quit, `ctrl+p` palette) keep their
default semantics; the palette handles its own escape/enter keys.

## Responsive behavior

| Condition | Behavior |
|-----------|----------|
| width ≥ 72 columns | Navigation rail is shown on the left |
| width < 72 | Rail collapses; brand tagline also collapses below 96 columns |
| any size | Status line, footer, and body content remain; nothing overlaps |

Resizing an open terminal re-evaluates the rules immediately (a resize
event handler, since Textual 8 has no CSS media queries).

## Design tokens (single source: `ui_terminal/theme.py`)

All colors are defined once and consumed as Textual theme variables
(`$primary`, `$surface`, `$panel`, `$boost`, plus the custom `$vs-*`
tokens). No screen module contains a raw color value.

| Token | Value | Role |
|-------|-------|------|
| background | #0a0e14 | deep slate canvas |
| surface | #10161e | card / widget body |
| panel | #141c26 | raised chrome (rail, brand bar, footer) |
| boost | #1b2634 | hover / selection raise |
| foreground | #d4dde6 | primary text |
| primary | #3ecfc4 | restrained teal — actions, focus, current section |
| secondary | #8ba2b8 | muted slate — secondary text, rail items |
| accent | #c9a54a | sparing gold — brand marker only |
| success / warning / error | #47c07a / #e0a437 / #e05561 | status colors |

Conventions:

- Focus is always visible (`:focus` frames in the shared CSS) and is
  never conveyed by color alone; status text is written out in words
  ("installed"/"missing", "saved"/"not configured").
- Status text uses explicit semantics classes (`status-ok`, `status-warn`,
  `status-error`, `status-muted`) that set text and color together.
- Brand art is one text row (name · tagline · section) — no ASCII logos.

## Accessibility limitations (documented honestly)

- The interface relies on the terminal's own accessibility support; no
  dedicated screen-reader certification is claimed for this stage.
- Color is decorative only: state is always doubled as text, but monochrome
  terminals that drop colors will still show words such as "missing".
- Very narrow terminals (< 40 columns) are expected to be uncommon; below
  the collapse thresholds the rail is hidden rather than overlapped.

## Non-goals in Stage 05

Device discovery, scanning, findings exploration, remediation, mirroring,
forensics, and the Windows desktop GUI are deliberately NOT implemented —
represented only as placeholder navigation destinations owned by
Stages 06–08. Animation polish is Stage 13.
