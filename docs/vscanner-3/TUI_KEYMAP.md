# V-Scanner 3.0 - TUI Keymap & Design Tokens (Stages 05-08)

This document is the human-readable contract for the terminal interface
introduced in Stage 05 and extended in Stages 06 (device workspace) and
07 (scanning, findings, reports). The screen-level tests
(`tests/unit/test_tui_entry.py`, `tests/unit/test_tui_app.py`) verify it
against the *actual* navigation registry and app bindings, so it cannot
silently drift from the code.

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
| f | Scanning & findings | live (Stage 07) |
| h | Reports & history | live (Stage 07) |
| m | Live monitoring | live (Stage 08) |
| o | Forensics | live (Stage 08) |
| i | Mirroring | live (Stage 08) |
| b | Demo data | live (Stage 08) |
| e | Doctor | live (Stage 05) |
| s | Settings | live (Stage 05) |
| f1 | Help & keys | live (Stage 05) |

There are no placeholder destinations left as of Stage 08: every planned
TUI section is a real screen, and each one still follows the honesty
contract (honest banners, never fake device state or pretend controls).
Pressing escape from any screen returns to the Dashboard.

Per-screen key collisions with global navigation keys are resolved by
screen priority (Textual): while a screen rebinds a letter (for example
`m` toggles the live poll on the monitoring screen, `o` sorts findings on
the scanning screen) the screen-level action wins there, and the global
navigation still works from every screen through the command palette
(ctrl+p) or by first pressing escape.

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

## Scanning & findings keys (Stage 07)

| Key | Action |
|-----|--------|
| r | Refresh the device list on the scanning screen (one explicit discovery per press) |
| enter / space on a device row | Select that scan target (never implicit when several are connected) |
| a | Start a full-device scan for the selected device (cancellable job) |
| n | Scan one app — asks for a package name, validated before any work starts |
| t | Toggle system apps on/off for the next scan |
| u | Toggle deep-scan mode on/off for the next scan |
| c | Cancel the running scan (a cancel REQUEST — the terminal state decides what is shown) |
| v | Cycle the findings severity threshold (any → critical+ → … → any) |
| g | Cycle the findings category filter |
| o | Cycle the findings sort order (deterministic orders only) |
| [ / ] | Previous / next findings page (100 findings per page) |
| (filter input) | Narrow the findings table by title, detail, or package while typing |
| enter on a finding row | Open the finding detail (kind, evidence sources, remediation, provenance) |

Honesty behavior on the scanning screen (also enforced by tests):

- Progress is only ever reported from real engine events; unknown counts
  are shown as unknown, never estimated.
- A cancelled or failed scan keeps whatever findings actually streamed,
  explicitly labeled as PARTIAL — it never claims a completed assessment.
- The device target is re-validated immediately before each scan starts;
  a stale target fails the scan request instead of silently switching.
- A completed scan appends one counters-only entry to the local scan
  history (T-08); nothing secret or findings-text is stored.

## Reports & history keys (Stage 07)

| Key | Action |
|-----|--------|
| r | Refresh the local scan-history table (T-08 store) |
| x | Export the last COMPLETED scan bundle through the shared report service |
| (input) | Output directory for the export (empty = legacy `reports` default) |

- Only the last completed scan of this session is exportable; cancelled
  or failed scans have no bundle and the panel says so instead of
  pretending.
- Successful export lists exactly the paths the service reported
  (`ExportResult.formats_written`) — nothing is claimed as saved that the
  service did not write.

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

## Stage 08 sections (monitoring / forensics / mirroring / demo)

- Live monitoring (m): r refresh devices · select a row · m start/stop the
  live poll session · v one honest sensor read. NOT_OBSERVED is always
  worded "not observed in this poll" — never "not in use".
- Forensics (o): r refresh · n new case (typed name) · 1 extract app data
  · 2 system logs · 3 installed packages · 4 running processes · 5 WiFi
  redacted · 6 WiFi CLEARTEXT (needs the exact typed acknowledgement
  `I ACCEPT CLEARTEXT PSK`) · 7 write report.json · o open an existing
  case by name. Root status is the tri-state probe with evidence rows.
- Mirroring (i): l launch scrcpy (refused honestly until the tool is
  validated) · r list running mirror handles · k stop mirrors.
- Demo data (b): r rebuilds the deterministic demo fixture (unchanged
  output). The DEMO banner is unmissable; no device is ever contacted.

## Non-goals through Stage 08

Remediation application and the Windows desktop GUI are deliberately NOT
implemented — the scanning screen reports and exports findings, but it
never *changes* the device. Animation polish remains Stage 13.
