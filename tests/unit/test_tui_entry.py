"""Entry-point, non-interactive, and documentation-consistency tests.

Covers the Stage 05 contract areas that are not screen interactions:

* ``main()`` refuses safely to run without a TTY (no UI attempt, exit 0,
  concise explanation, nothing probed or changed).
* ``python -m ui_terminal`` is wired to the same entry function.
* The ``vscanner-tui`` entry point is declared in pyproject (packaging
  metadata is verified statically here because the package is not
  installed in the development environment).
* The keymap document stays in sync with the REAL bindings — the registry
  constants and app bindings drive both, so help text cannot drift.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


class TestNonInteractive:
    def test_main_without_tty_prints_guidance_and_exits_zero(
        self, monkeypatch
    ) -> None:
        from ui_terminal.app import main

        fake_stdout = io.StringIO()
        fake_stdin = io.StringIO()
        monkeypatch.setattr(sys, "stdout", fake_stdout)
        monkeypatch.setattr(sys, "stdin", fake_stdin)
        rc = main()
        output = fake_stdout.getvalue()
        assert rc == 0
        assert "interactive" in output.lower()
        assert "python cli/main.py" in output  # points at the real CLI
        # No traceback, no device/network wording implying action was taken
        assert "Traceback" not in output
        assert "probed" in output and "chore" not in output

    def test_main_module_wired_to_app_main(self) -> None:
        import ui_terminal.__main__ as entry_mod
        from ui_terminal.app import main

        assert entry_mod.main is main


class TestPackagingMetadata:
    def test_pyproject_declares_tui_entry_point_and_dependency(self) -> None:
        text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        assert 'vscanner-tui = "ui_terminal.app:main"' in text
        import re

        dep = re.search(r'"textual>=([\d.]+),<(\d+)"', text)
        assert dep is not None, "textual dependency must be declared"
        assert dep.group(2) == "9"

    def test_tui_packages_are_listed_for_packaging(self) -> None:
        text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        assert '"ui_terminal"' in text
        assert '"ui_terminal.screens"' in text


class TestKeymapDocumentation:
    """Help text must match actual bindings (AC: shortcut/help consistency)."""

    def _doc(self) -> str:
        return (REPO_ROOT / "docs" / "vscanner-3" / "TUI_KEYMAP.md").read_text(
            encoding="utf-8"
        )

    def test_every_direct_binding_is_documented(self) -> None:
        from ui_terminal.app import VScannerApp

        doc = self._doc()
        for binding in VScannerApp.BINDINGS:
            if isinstance(binding, tuple):
                key = binding[0]
                description = binding[1] if len(binding) > 1 else key
                shown = True
            else:
                key = binding.key
                description = binding.description
                shown = binding.show
            if not shown:
                assert key == "escape"
                assert "escape" in doc.lower()
                continue
            assert key in doc or description.lower() == key, (
                f"binding {key} ({description}) missing from keymap doc"
            )
        # inherited core bindings
        assert "ctrl+p" in doc, "command palette binding must be documented"
        assert "ctrl+q" in doc, "quit binding must be documented"

    def test_documented_sections_match_the_registry(self) -> None:
        from ui_terminal import sections as reg

        doc = self._doc()
        for section in reg.SECTION_REGISTRY:
            assert section.title in doc, f"{section.title} missing from keymap doc"
            if section.kind == "future":
                assert f"Stage {section.owner_stage}" in doc

    def test_workspace_screen_bindings_are_documented(self) -> None:
        """Stage 06: every device-workspace keybinding has a keymap row."""
        from ui_terminal.screens.workspace import DeviceWorkspaceScreen

        doc = self._doc()
        for binding in DeviceWorkspaceScreen.BINDINGS:
            if isinstance(binding, tuple):
                key, description = binding[0], binding[1]
                shown = True
            else:
                key, description = binding.key, binding.description
                shown = binding.show
            if not shown:
                continue
            assert key in doc, (
                f"device workspace binding {key} ({description}) missing "
                "from keymap doc"
            )
        assert "Device workspace keys" in doc, (
            "the Stage 06 workspace key section must exist"
        )

    def test_global_keys_table_matches_help_screen_constants(self) -> None:
        from ui_terminal.screens.help import GLOBAL_KEYS

        doc = self._doc()
        for key, action in GLOBAL_KEYS:
            assert key in doc, f"{key} missing from keymap doc"
            # the first words of the action description must appear too
            assert action.split("—")[0].strip() in doc
        # the documented rail breakpoint must match the code constant
        from ui_terminal.screens.shell import RAIL_MIN_WIDTH

        assert str(RAIL_MIN_WIDTH) in doc

    def test_accessibility_limitations_documented(self) -> None:
        doc = self._doc()
        assert "screen-reader" in doc.lower()
        assert "not" in doc.lower()
