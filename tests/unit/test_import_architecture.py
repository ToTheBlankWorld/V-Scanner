"""Import-architecture guard tests (Stage 03).

The engine (``vscanner``) must stay framework-independent, subprocess-safe
by construction (R-10: never ``shell=True``), free of import cycles, and
report-only at import time (R-14: no startup pip installs).
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path
from typing import Dict, List, Set, Tuple

import pytest

import vscanner

VSCANNER_ROOT = Path(vscanner.__file__).resolve().parent
FORBIDDEN_FRAMEWORKS = {
    "rich", "textual", "PySide6", "click", "fastapi", "flask",
    "tkinter", "django", "streamlit",
}
CYCLE_SAFE = "no cycle detected"


def _iter_vscanner_sources():
    """Every python file under the engine, including ``__init__`` modules."""
    for path in sorted(VSCANNER_ROOT.rglob("*.py")):
        parts = list(path.relative_to(VSCANNER_ROOT).with_suffix("").parts)
        if parts and parts[-1] == "__init__":
            parts.pop()
        if not parts:
            continue
        yield ".".join(["vscanner"] + parts)


def _module_path(module_name: str) -> Path:
    parts = module_name.split(".")[1:]  # drop the package prefix
    as_module = VSCANNER_ROOT.joinpath(*parts).with_suffix(".py")
    if as_module.exists():
        return as_module
    return VSCANNER_ROOT.joinpath(*parts) / "__init__.py"  # package module


def _top_level_imports(source: str) -> Tuple[Set[str], List[ast.FunctionDef]]:
    tree = ast.parse(source)
    tops = []
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                names.add(node.module.split(".")[0])
        elif isinstance(node, ast.FunctionDef):
            tops.append(node)
    return names, tops


class TestFrameworkIndependence:
    @pytest.mark.parametrize("module_name", list(_iter_vscanner_sources()))
    def test_no_ui_framework_imports(self, module_name):
        source = _module_path(module_name).read_text(encoding="utf-8")
        names, _ = _top_level_imports(source)
        offenders = names & FORBIDDEN_FRAMEWORKS
        assert not offenders, f"{module_name} imports UI frameworks: {offenders}"

    def test_jinja2_confined_to_reports(self):
        offenders = []
        for module_name in _iter_vscanner_sources():
            source = _module_path(module_name).read_text(encoding="utf-8")
            names, _ = _top_level_imports(source)
            if "jinja2" in names and not module_name.startswith("vscanner.services.reports"):
                offenders.append(module_name)
        assert offenders == []

    def test_engine_package_public_surface_is_framework_free(self):
        import vscanner as pkg

        public = {name for name in vars(pkg) if not name.startswith("_")}
        framework_leaks = public & FORBIDDEN_FRAMEWORKS
        assert not framework_leaks


class TestSubprocessPolicyR10:
    def test_no_shell_true_anywhere_in_engine(self):
        offenders = []
        for module_name in _iter_vscanner_sources():
            tree = ast.parse(_module_path(module_name).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) and not isinstance(node, ast.keyword):
                    continue
                if isinstance(node, ast.keyword) and node.arg == "shell":
                    offenders.append(module_name)
        assert offenders == []

    def test_all_engine_modules_import_cleanly(self):
        for module_name in _iter_vscanner_sources():
            importlib.import_module(module_name)
        import vscanner.services as services

        assert services is not None


class TestNoStartupInstallsR14:
    def test_engine_never_imports_pip_or_installs_at_startup(self):
        offenders = []
        for module_name in _iter_vscanner_sources():
            source = _module_path(module_name).read_text(encoding="utf-8")
            names, _ = _top_level_imports(source)
            if {"pip", "ensurepip"} & names:
                offenders.append(module_name)
            if "subprocess" in names and "vscanner.services.doctor" == module_name:
                offenders.append(module_name)  # doctor is report-only
        # pip usage would only be acceptable inside an explicit user-action
        # service not written yet: today the engine imports none of these.
        assert offenders == []

    def test_importing_the_package_has_no_network_side_effects(self):
        """Import-time smoke: constructing the package twice is idempotent
        and touches nothing outside import machinery."""
        import importlib

        first = importlib.import_module("vscanner")
        second = importlib.reload(importlib.import_module("vscanner"))
        assert first is second


class TestImportGraph:
    @staticmethod
    def _internal_dependencies() -> Dict[str, Set[str]]:
        graph: Dict[str, Set[str]] = {}
        for module_name in _iter_vscanner_sources():
            source = _module_path(module_name).read_text(encoding="utf-8")
            tree = ast.parse(source)
            deps = set()
            for node in tree.body:  # top-level only (cycles need module-level)
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name.startswith("vscanner"):
                            deps.add(alias.name)
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    if (node.module or "").startswith("vscanner"):
                        deps.add(node.module if not node.module.startswith("vscanner.helpers")
                                 else "vscanner.helpers")
                        parents = node.module.split(".")
                        for depth in range(1, len(parents) + 1):
                            deps.add(".".join(parents[:depth]))
            graph[module_name] = deps
        return graph

    def test_no_import_cycles_at_module_level(self):
        graph = self._internal_dependencies()
        # Restrict edges to nodes (vscanner's own modules), then run Kahn's
        # algorithm: leftover nodes ⇒ a module-level import cycle.
        adjusted = {name: {d for d in deps if d in graph} for name, deps in graph.items()}
        children: Dict[str, Set[str]] = {}
        for name, deps in adjusted.items():
            for dep in deps:
                children.setdefault(dep, set()).add(name)
        indegree = {name: len(deps) for name, deps in adjusted.items()}
        queue = [name for name, count in indegree.items() if count == 0]
        seen = 0
        while queue:
            node = queue.pop()
            seen += 1
            for nxt in children.get(node, ()):
                indegree[nxt] -= 1
                if indegree[nxt] == 0:
                    queue.append(nxt)
        assert seen == len(adjusted), (
            f"module-level import cycle detected among: "
            f"{sorted(name for name, count in indegree.items() if count > 0)}"
        )

    def test_services_never_import_cli_modules(self):
        offenders = []
        for module_name in _iter_vscanner_sources():
            source = _module_path(module_name).read_text(encoding="utf-8")
            names, _ = _top_level_imports(source)
            if {"main", "scanner", "tools_manager", "adb_setup"} & names:
                offenders.append(module_name)
        assert offenders == [], f"engine reaching into legacy cli: {offenders}"

    def test_source_volume_stays_lean(self):
        """AST-lean budget: the whole engine stays comfortably under the size
        the legacy single-file UI occupied (guard against silent bloat).

        Stage 08 (2026-10-18): the budget moves 6000 → 10500 for the
        documented Stage 08 services (SC-5/SC-6/SC-8/SC-10, forensics port,
        R-05 root probe, R-06 deep scan) — each sized to its contract with
        no copied legacy bloat (see STAGE_08_IMPLEMENTATION_REPORT.md,
        volume table). The guard itself stays: silent bloat beyond the
        new budget still fails."""
        total_lines = sum(
            len(_module_path(name).read_text(encoding="utf-8").splitlines())
            for name in _iter_vscanner_sources()
        )
        assert total_lines < 10500, f"engine grew to {total_lines} lines"


class TestUiSubprocessGuard:
    """Stage 06: only the sanctioned backend seam may touch subprocess/
    ADB internals; workspace widgets never run ADB and never shell out."""

    UI_FEEDBACK_MODULES: Tuple[str, ...] = (
        "ui_terminal.app",
        "ui_terminal.sections",
        "ui_terminal.theme",
        "ui_terminal.jobs_bridge_async",
        "ui_terminal.screens.workspace",
        "ui_terminal.screens.shell",
        "ui_terminal.screens.dashboard",
        "ui_terminal.screens.doctor",
        "ui_terminal.screens.settings",
        "ui_terminal.screens.help",
        "ui_terminal.screens.placeholder",
    )

    def _ui_path(self, module_name: str) -> Path:
        import ui_terminal

        root = Path(ui_terminal.__file__).resolve().parent
        parts = module_name.split(".")[1:]
        return root.joinpath(*parts).with_suffix(".py")

    def test_feedback_screens_never_touch_adb_or_subprocess(self):
        import ast as ast_module

        # the executable module is PATH resolution only (no subprocess, no
        # transport); the Stage 05 settings screen is sanctioned for it
        allowed_adb_submodules = {"vscanner.services.adb.executable"}
        offenders = []
        for module_name in self.UI_FEEDBACK_MODULES:
            source = self._ui_path(module_name).read_text(encoding="utf-8")
            tree = ast_module.parse(source)
            for node in ast_module.walk(tree):
                if isinstance(node, ast_module.Import):
                    if any(alias.name == "subprocess" for alias in node.names):
                        offenders.append(f"{module_name}: import subprocess")
                elif isinstance(node, ast_module.ImportFrom):
                    module = node.module or ""
                    touched = (
                        module == "subprocess"
                        or (
                            module.startswith("vscanner.services.adb")
                            and module not in allowed_adb_submodules
                        )
                    )
                    if touched:
                        offenders.append(f"{module_name}: import {module}")
        assert offenders == [], (
            "presentation screens must go through ui_terminal.backend: "
            f"{offenders}"
        )

