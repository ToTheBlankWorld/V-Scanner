"""Static structure + config-consumer characterization tests (Stage 02).

Covers repository-hygiene-adjacent behaviors: the tracked machine-specific
``cli/adb_config.json`` (R-08), ``shell=True`` subprocess use (R-10), and the
legacy architecture tangles (duplicate defs, shadowed config functions).
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

import adb_setup
import main as main_module
from conftest import adb_completed

CLI_DIR = Path(adb_setup.__file__).resolve().parent


class TestR10SubprocessPolicy:
    def test_setup_uses_shell_true(self):
        """R-10 characterization: cli/setup.py interpolates a command string and
        passes shell=True."""
        source = (CLI_DIR / "setup.py").read_text(encoding="utf-8")
        assert "shell=True" in source

    def test_adb_setup_invokes_subprocess_by_argument_list(self):
        """adb_setup (the config path actually exercised by tests) uses argument
        lists; safe pattern that Stage 03 will follow everywhere."""
        tree = ast.parse((CLI_DIR / "adb_setup.py").read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "run":
                keywords = {kw.arg for kw in node.keywords}
                assert "shell" not in keywords, "shell=True must not appear in adb_setup"
                args_are_lists = isinstance(node.args[0], (ast.List, ast.Name))
                assert args_are_lists, "subprocess.run must receive an argument list"


class TestAdbConfigConsumers:
    """§4.5 evidence: existing config consumers keep functioning when the
    tracked ``cli/adb_config.json`` is removed from Git tracking (the local
    copy may exist or not — both paths are exercised here)."""

    def test_missing_config_loads_to_none(self, isolated_config):
        assert not isolated_config.exists()
        import adb_setup

        assert adb_setup.load_adb_config() is None

    def test_malformed_config_loads_to_none(self, isolated_config, capsys):
        """R-02 seed behavior retained: load returns None on malformed data,
        but Stage 03 adds a VISIBLE warning - never a silent swallow."""
        import adb_setup

        isolated_config.write_text("{{{broken", encoding="utf-8")
        assert adb_setup.load_adb_config() is None
        console_out = capsys.readouterr().out
        assert "adb_config.json" in console_out or "config" in console_out.lower()

    def test_config_with_unverifiable_path_is_rejected(self, isolated_config):
        import adb_setup

        isolated_config.write_text(json.dumps({"adb_path": r"Z:\does\not\exist\adb.exe"}), encoding="utf-8")
        assert adb_setup.load_adb_config() is None

    def test_save_then_load_roundtrip(self, isolated_config, monkeypatch):
        import adb_setup
        from vscanner.services.config import ConfigService

        # Pretend the saved binary is a valid ADB executable (the legacy
        # adapter validates through its own seam; monkeypatch target unchanged).
        monkeypatch.setattr(adb_setup, "check_adb_valid", lambda path: True)
        assert not isolated_config.exists()
        adb_setup.save_adb_config(r"C:\platform-tools\adb.exe")
        data = json.loads(isolated_config.read_text(encoding="utf-8"))
        assert data["adb_path"] == r"C:\platform-tools\adb.exe"
        assert adb_setup.load_adb_config() == r"C:\platform-tools\adb.exe"
        # The service layer adds the schema envelope on every write (R-02);
        # typed ConfigError propagation is asserted against the authoritative
        # loader in test_known_defects. Unknown schema versions surface as a
        # visible warning here and still return None (compat contract).
        assert data["schema_version"] == 1
        isolated_config.write_text(
            json.dumps({"schema_version": 99, "adb_path": "x"}), encoding="utf-8"
        )
        assert adb_setup.load_adb_config() is None

    def test_main_module_loader_uses_existing_config(self, isolated_config, monkeypatch):
        main_module.load_adb_config()  # missing file → None (no crash)
        isolated_config.write_text(json.dumps({"adb_path": r"C:\x\adb.exe"}), encoding="utf-8")
        monkeypatch.setattr(adb_setup, "check_adb_valid", lambda path: True)
        assert main_module.load_adb_config() == r"C:\x\adb.exe"


class TestLegacyTangleEvidence:
    def test_single_adb_path_global(self):
        """R-02 remediated (Stage 03): main.py defines ADB_PATH exactly once
        (the duplicate at audit line 65 was removed with the shadowed defs)."""
        source = (CLI_DIR / "main.py").read_text(encoding="utf-8")
        assert source.count("ADB_PATH = None") == 1

    def test_interactive_setup_flow_requires_console(self):
        """Documents that interactive_adb_setup is console-driven — the reason
        Stage 02 does not exercise it (guard against accidental automation)."""
        import inspect

        src = inspect.getsource(adb_setup.interactive_adb_setup)
        assert "console.input" in src
