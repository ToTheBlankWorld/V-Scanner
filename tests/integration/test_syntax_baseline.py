"""Syntax baseline (Stage 02 — section 5 requirement).

Every legacy CLI module must byte-compile. This is the documented
"Python syntax validation" step and keeps regressions visible in CI output.
"""

from __future__ import annotations

import py_compile
from pathlib import Path

import pytest

import scanner  # for CLI_DIR discovery

CLI_DIR = Path(scanner.__file__).resolve().parent

MODULES = [
    "main", "scanner", "permissions", "report_generator",
    "tools_manager", "adb_setup", "auto_setup", "dependency_checker",
    "digital_forensics", "ui_styles", "setup",
]


@pytest.mark.parametrize("module", MODULES)
def test_module_compiles(module, tmp_path):
    py_compile.compile(str(CLI_DIR / f"{module}.py"), cfile=str(tmp_path / f"{module}.pyc"), doraise=True)
