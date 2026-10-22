"""Stage 14 packaging tests — Windows distribution policy (T-05).

All tests are toolchain-free: they exercise the packaging policy modules
(``packaging_windows``) against temporary fixtures, the committed icon
asset, and the repository configuration. No Nuitka/Inno invocation happens
here except through stubbed ``subprocess.run`` (failure propagation); the
*real* artifact build is a separate, documented pipeline step
(``python -m packaging_windows.build_windows``) whose results are reported
in STAGE_14_IMPLEMENTATION_REPORT — a green test run must never be misread
as "the exe was built".

Covers: version sourcing (pyproject lockstep, numeric derivation), the
staging allowlist (secrets/machine-local config/tests/caches/VCS never
staged; source tree never mutated; non-empty destinations refused),
staged-tree and distribution validation (required inputs, forbidden
content, PE/Qt/Python DLL closure), the clean smoke-launch environment,
launcher purity (single delegation to ``ui_desktop.app:main``), Inno
Setup script contract (stable AppId, per-user low-privilege install,
default-retain user data, no network/PowerShell hooks), tool discovery
and failure propagation, and the committed icon asset.
"""

from __future__ import annotations

import ast
import re
import shutil
import struct
import subprocess
from pathlib import Path
from typing import Any, Iterator

import pytest

from packaging_windows import (
    APP_ID,
    EXECUTABLE_NAME,
)
from packaging_windows import (
    staging as staging_module,
    validation as validation_module,
    versioning as versioning_module,
)
from packaging_windows import build_windows as build_module
from packaging_windows.icon import assemble_ico

REPO_ROOT = Path(__file__).resolve().parents[2]
PYPROJECT_PATH = REPO_ROOT / "pyproject.toml"
PACKAGING_ROOT = REPO_ROOT / "packaging_windows"
LAUNCHER_PATH = PACKAGING_ROOT / staging_module.LAUNCHER_NAME
ISS_PATH = PACKAGING_ROOT / "installer.iss"
ICON_PATH = PACKAGING_ROOT / "assets" / "vscanner.ico"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


@pytest.fixture()
def synthetic_repo(tmp_path: Path) -> Path:
    """A repository-shaped fixture exercising the full staging policy."""
    root = tmp_path / "repo"
    root.mkdir()
    _write(root / "vscanner" / "__init__.py", "")
    _write(root / "vscanner" / "core" / "paths.py", "x = 1\n")
    _write(root / "ui_desktop" / "__init__.py", "")
    _write(root / "ui_desktop" / "app.py", "def main() -> int:\n    return 0\n")
    (root / "vscanner" / "__pycache__").mkdir()
    (root / "vscanner" / "__pycache__" / "paths.cpython-312.pyc").write_bytes(b"\x00")
    (root / ".git").mkdir()
    (root / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    # Must never enter the distribution:
    _write(root / "cli" / "adb_config.json", '{"adb_path": "C:/local"}')
    _write(root / "tests" / "test_thing.py", "def test_x() -> None: pass\n")
    _write(root / "android" / "app" / "AndroidManifest.xml", "<manifest/>")
    _write(root / "docs" / "note.md", "secret\n")
    _write(root / "vscanner" / "machine_local.pem", "PRIVATE KEY")
    _write(root / "ui_desktop" / "config.json", "{}")
    _write(root / "pyproject.toml", 'version = "3.0.0a0"\n')
    # The launcher source that the stager copies is searched under
    # ``<repo_root>/packaging_windows/`` — mirror the committed launcher.
    launcher_dir = root / "packaging_windows"
    launcher_dir.mkdir()
    shutil.copyfile(LAUNCHER_PATH, launcher_dir / staging_module.LAUNCHER_NAME)
    return root


@pytest.fixture()
def staged_synthetic(tmp_path: Path, synthetic_repo: Path) -> Path:
    """Stage the synthetic repository into a fresh destination."""
    destination = tmp_path / "work" / "stage"
    destination.parent.mkdir(parents=True)
    staging_module.stage_release_tree(synthetic_repo, destination)
    return destination


@pytest.fixture()
def fake_iscc_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    """Redirect every ``find_iscc`` discovery location to temporary dirs."""
    local = tmp_path / "localappdata"
    local.mkdir()
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.setenv("ProgramFiles(x86)", str(tmp_path / "pf86"))
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "pf"))
    monkeypatch.delenv("VSCANNER_INNO_SETUP", raising=False)
    yield


def _fake_dist(tmp_path: Path, *, with_closure: bool = True) -> Path:
    """A minimal distribution standing in for the compiled one.

    Mirrors the real Nuitka standalone shape (Stage 15 audit): compiled
    closures only — no ``.py``/``.pyc`` land inside the dist, exactly one
    ``.exe`` (the app itself), and the PySide6 bindings as native modules.
    """
    dist = tmp_path / "dist"
    (dist / "PySide6" / "plugins" / "platforms").mkdir(parents=True)
    (dist / "PySide6" / "__init__.pyd").write_bytes(b"")
    (dist / EXECUTABLE_NAME).write_bytes(b"MZ" + b"\x00" * 64)
    if with_closure:
        (dist / "python312.dll").write_bytes(b"PK")
        (dist / "Qt6Core.dll").write_bytes(b"PK")
        (dist / "Qt6Gui.dll").write_bytes(b"PK")
        (dist / "Qt6Widgets.dll").write_bytes(b"PK")
        (dist / "PySide6" / "plugins" / "platforms" / "qwindows.dll").write_bytes(b"PK")
    return dist


# ---------------------------------------------------------------------------
# Version sourcing
# ---------------------------------------------------------------------------


class TestVersionSourcing:
    def test_pyproject_version_is_the_single_source(self) -> None:
        version = versioning_module.parse_pyproject_version(PYPROJECT_PATH)
        assert version == "3.0.0a0", (
            "pyproject.toml is the authoritative version (lockstep with "
            "ui_desktop.APP_VERSION, Stage 09)"
        )

    def test_version_lockstep_with_app_version(self) -> None:
        from ui_desktop import APP_VERSION

        version = versioning_module.parse_pyproject_version(PYPROJECT_PATH)
        assert version == APP_VERSION

    def test_numeric_derivation(self) -> None:
        assert versioning_module.derive_numeric_version("3.0.0a0") == "3.0.0"
        assert versioning_module.derive_numeric_version("3.1.1") == "3.1.1"
        assert versioning_module.derive_numeric_version("2.3") == "2.3"
        assert versioning_module.derive_numeric_version("3.0.0") == "3.0.0"

    def test_numeric_derivation_rejects_non_numeric_version(self) -> None:
        with pytest.raises(ValueError):
            versioning_module.derive_numeric_version("beta-1")

    def test_quad_derivation(self) -> None:
        assert versioning_module.derive_version_quad("3.0.0a0") == "3.0.0.0"
        assert versioning_module.derive_version_quad("3.1.1") == "3.1.1.0"
        assert versioning_module.derive_version_quad("2.3") == "2.3.0.0"
        assert versioning_module.derive_version_quad("3.0.0") == "3.0.0.0"

    def test_quad_derivation_rejects_non_numeric_version(self) -> None:
        with pytest.raises(ValueError):
            versioning_module.derive_version_quad("beta-1")

    def test_missing_version_is_actionable(self, tmp_path: Path) -> None:
        path = _write(tmp_path / "pyproject.toml", "[project]\nname = 'x'\n")
        with pytest.raises(ValueError):
            versioning_module.parse_pyproject_version(path)

    def test_regex_fallback_parses_single_version(self) -> None:
        text = PYPROJECT_PATH.read_text(encoding="utf-8")
        parsed = versioning_module._parse_version_by_regex(text)
        assert parsed == "3.0.0a0"

    def test_regex_fallback_flags_ambiguity(self) -> None:
        text = 'version = "1.0"\nversion = "2.0"\n'
        with pytest.raises(ValueError):
            versioning_module._parse_version_by_regex(text)


# ---------------------------------------------------------------------------
# Staging policy
# ---------------------------------------------------------------------------


class TestStagingPolicy:
    def test_only_policy_entries_are_staged(self, staged_synthetic: Path) -> None:
        staged_files = {path.relative_to(staged_synthetic).as_posix()
                        for path in staged_synthetic.rglob("*") if path.is_file()}
        required = {
            "vscanner/__init__.py", "vscanner/core/paths.py",
            "ui_desktop/__init__.py", "ui_desktop/app.py",
            staging_module.LAUNCHER_NAME,
        }
        assert required <= staged_files
        assert staged_files == required  # the synthetic tree has nothing more
        staged_dirs = {path.relative_to(staged_synthetic).as_posix()
                       for path in staged_synthetic.rglob("*") if path.is_dir()}
        assert staged_dirs == {"vscanner", "vscanner/core", "ui_desktop"}

    def test_forbidden_content_never_staged(self, staged_synthetic: Path) -> None:
        names = {path.name for path in staged_synthetic.rglob("*")}
        assert "adb_config.json" not in names
        assert "machine_local.pem" not in names
        assert "config.json" not in names
        assert "AndroidManifest.xml" not in names
        assert "test_thing.py" not in names
        assert "paths.cpython-312.pyc" not in names

    def test_vcs_and_dev_dirs_never_staged(self, staged_synthetic: Path) -> None:
        dirs = {path.name for path in staged_synthetic.rglob("*") if path.is_dir()}
        assert not dirs & {"__pycache__", ".git", "tests", "docs", "android"}

    def test_pyproject_is_not_staged(self, staged_synthetic: Path) -> None:
        assert not (staged_synthetic / "pyproject.toml").exists()

    def test_no_ui_terminal_tree_is_staged(
        self, tmp_path: Path, synthetic_repo: Path
    ) -> None:
        _write(synthetic_repo / "ui_terminal" / "__init__.py", "")
        destination = tmp_path / "stage2"
        staging_module.stage_release_tree(synthetic_repo, destination)
        assert not (destination / "ui_terminal").exists()

    def test_source_tree_is_never_mutated_or_deleted(
        self, tmp_path: Path, synthetic_repo: Path
    ) -> None:
        def snapshot(root: Path) -> dict[str, bytes]:
            return {path.relative_to(root).as_posix(): path.read_bytes()
                    for path in root.rglob("*") if path.is_file()}

        before = snapshot(synthetic_repo)
        staging_module.stage_release_tree(synthetic_repo, tmp_path / "stage3")
        assert snapshot(synthetic_repo) == before

    def test_nonempty_destination_is_refused(
        self, tmp_path: Path, synthetic_repo: Path
    ) -> None:
        destination = tmp_path / "work" / "stage"
        destination.parent.mkdir(parents=True)
        destination.mkdir()
        (destination / "leftover.bin").write_bytes(b"\x00")
        with pytest.raises(ValueError, match="not empty"):
            staging_module.stage_release_tree(synthetic_repo, destination)
        assert (destination / "leftover.bin").exists()

    def test_stage_inside_repo_is_refused(
        self, tmp_path: Path, synthetic_repo: Path
    ) -> None:
        with pytest.raises(ValueError, match="outside the repository"):
            staging_module.stage_release_tree(
                synthetic_repo, synthetic_repo / "build" / "stage")


# ---------------------------------------------------------------------------
# Staged-tree validation
# ---------------------------------------------------------------------------


class TestStagedTreeValidation:
    def test_valid_staged_tree_passes(self, staged_synthetic: Path) -> None:
        assert validation_module.validate_staged_tree(staged_synthetic) == []

    def test_missing_required_file_is_actionable(self, staged_synthetic: Path) -> None:
        (staged_synthetic / "ui_desktop" / "app.py").unlink()
        with pytest.raises(validation_module.ValidationError, match="app.py"):
            validation_module.validate_staged_tree(staged_synthetic)

    def test_machine_local_config_in_stage_fails(
        self, staged_synthetic: Path
    ) -> None:
        _write(staged_synthetic / "vscanner" / "adb_config.json", "{}")
        with pytest.raises(
            validation_module.ValidationError, match="adb_config"
        ):
            validation_module.validate_staged_tree(staged_synthetic)

    def test_tests_directory_in_stage_fails(self, staged_synthetic: Path) -> None:
        (staged_synthetic / "tests").mkdir()
        _write(staged_synthetic / "tests" / "test_x.py", "")
        with pytest.raises(validation_module.ValidationError, match="forbidden"):
            validation_module.validate_staged_tree(staged_synthetic)

    def test_bytecode_in_stage_fails(self, staged_synthetic: Path) -> None:
        (staged_synthetic / "vscanner" / "mod.cpython-312.pyc").write_bytes(b"x")
        with pytest.raises(validation_module.ValidationError, match="forbidden"):
            validation_module.validate_staged_tree(staged_synthetic)

    def test_planted_test_file_in_package_fails(
        self, staged_synthetic: Path
    ) -> None:
        _write(staged_synthetic / "vscanner" / "test_leak.py", "")
        with pytest.raises(validation_module.ValidationError, match="forbidden"):
            validation_module.validate_staged_tree(staged_synthetic)

    def test_pyproject_in_stage_fails(self, staged_synthetic: Path) -> None:
        _write(staged_synthetic / "pyproject.toml", 'version = "3.0.0a0"\n')
        with pytest.raises(validation_module.ValidationError, match="pyproject"):
            validation_module.validate_staged_tree(staged_synthetic)

    def test_ui_terminal_in_stage_fails(self, staged_synthetic: Path) -> None:
        _write(staged_synthetic / "ui_terminal" / "__init__.py", "")
        with pytest.raises(validation_module.ValidationError, match="ui_terminal"):
            validation_module.validate_staged_tree(staged_synthetic)


# ---------------------------------------------------------------------------
# Distribution validation
# ---------------------------------------------------------------------------


class TestDistributionValidation:
    def test_complete_minimal_dist_passes(self, tmp_path: Path) -> None:
        dist = _fake_dist(tmp_path)
        report = validation_module.validate_distribution(dist)
        assert report.executable.name == "V-Scanner.exe"
        assert report.files > 0
        assert report.total_bytes > 0

    def test_missing_executable_fails(self, tmp_path: Path) -> None:
        dist = _fake_dist(tmp_path)
        (dist / EXECUTABLE_NAME).unlink()
        with pytest.raises(validation_module.ValidationError, match="executable"):
            validation_module.validate_distribution(dist)

    def test_non_pe_executable_fails(self, tmp_path: Path) -> None:
        dist = _fake_dist(tmp_path)
        (dist / EXECUTABLE_NAME).write_bytes(b"TIFFMARK")
        with pytest.raises(validation_module.ValidationError, match="PE"):
            validation_module.validate_distribution(dist)

    def test_missing_platform_plugin_fails(self, tmp_path: Path) -> None:
        dist = _fake_dist(tmp_path)
        (dist / "PySide6" / "plugins" / "platforms" / "qwindows.dll").unlink()
        with pytest.raises(validation_module.ValidationError, match="qwindows"):
            validation_module.validate_distribution(dist)

    def test_missing_qt_dll_fails(self, tmp_path: Path) -> None:
        dist = _fake_dist(tmp_path)
        (dist / "Qt6Core.dll").unlink()
        with pytest.raises(validation_module.ValidationError, match="Qt6Core"):
            validation_module.validate_distribution(dist)

    def test_missing_python_dll_fails(self, tmp_path: Path) -> None:
        dist = _fake_dist(tmp_path)
        (dist / "python312.dll").unlink()
        with pytest.raises(validation_module.ValidationError, match="python3"):
            validation_module.validate_distribution(dist)

    def test_missing_pyside6_fails(self, tmp_path: Path) -> None:
        dist = _fake_dist(tmp_path)
        shutil.rmtree(dist / "PySide6")
        with pytest.raises(validation_module.ValidationError, match="PySide6"):
            validation_module.validate_distribution(dist)

    def test_forbidden_content_in_dist_fails(self, tmp_path: Path) -> None:
        dist = _fake_dist(tmp_path)
        _write(dist / "vscanner" / "adb_config.json", "{}")
        with pytest.raises(validation_module.ValidationError, match="forbidden"):
            validation_module.validate_distribution(dist)

    def test_bytecode_or_tests_in_dist_fail(self, tmp_path: Path) -> None:
        dist = _fake_dist(tmp_path)
        (dist / "garbage.pyc").write_bytes(b"x")
        with pytest.raises(validation_module.ValidationError, match="forbidden"):
            validation_module.validate_distribution(dist)
        dist2 = _fake_dist(tmp_path / "second")
        (dist2 / "tests").mkdir()
        with pytest.raises(validation_module.ValidationError, match="forbidden"):
            validation_module.validate_distribution(dist2)


# ---------------------------------------------------------------------------
# Clean smoke environment
# ---------------------------------------------------------------------------


class TestCleanSmokeEnvironment:
    def test_engine_path_overrides_are_dropped(self) -> None:
        env = validation_module.clean_gui_environment({
            "SystemRoot": "C:/WINDOWS",
            "LOCALAPPDATA": "C:/Users/u/AppData/Local",
            "VSCANNER_LOCAL": "1",
            "VSCANNER_DATA_DIR": "D:/odd",
            "PYTHONPATH": "repo",
            "PYTEST_CURRENT_TEST": "tests",
        })
        for dropped in ("VSCANNER_LOCAL", "VSCANNER_DATA_DIR",
                        "PYTHONPATH", "PYTEST_CURRENT_TEST"):
            assert dropped not in env
        assert env["SystemRoot"] == "C:/WINDOWS"
        assert env["QT_QPA_PLATFORM"] == "offscreen"

    def test_non_os_variables_are_dropped(self) -> None:
        env = validation_module.clean_gui_environment({
            "SystemRoot": "C:/WINDOWS",
            "GIT_DIR": "somewhere",
            "MY_TOKEN": "secret",
        })
        assert "GIT_DIR" not in env
        assert "MY_TOKEN" not in env

    def test_smoke_launch_contract_on_missing_inputs(self, tmp_path: Path) -> None:
        with pytest.raises(validation_module.ValidationError, match="missing"):
            validation_module.smoke_launch(tmp_path / "no.exe", tmp_path)


# ---------------------------------------------------------------------------
# Launcher purity
# ---------------------------------------------------------------------------


class TestLauncherPurity:
    def _launcher_ast(self) -> ast.Module:
        return ast.parse(LAUNCHER_PATH.read_text(encoding="utf-8"))

    def test_launcher_imports_only_sys_and_the_real_entry(self) -> None:
        imports: list[str] = []
        for node in ast.walk(self._launcher_ast()):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                for alias in node.names:
                    imports.append(f"{module}:{alias.name}")
        assert imports == ["sys", "ui_desktop.app:main"]

    def test_launcher_delegates_to_real_main(self) -> None:
        text = LAUNCHER_PATH.read_text(encoding="utf-8")
        assert re.search(r"sys\.exit\(\s*main\(\)\s*\)", text)

    def test_launcher_has_no_environment_manipulation(self) -> None:
        text = LAUNCHER_PATH.read_text(encoding="utf-8")
        assert "environ" not in text
        assert "VSCANNER_LOCAL" not in text
        for forbidden in ("subprocess", "Popen", "argparse"):
            assert forbidden not in text

    def test_launcher_top_level_stays_minimal(self) -> None:
        tree = self._launcher_ast()
        keep = (ast.Import, ast.ImportFrom, ast.Expr)
        guard_blocks = [node for node in tree.body if isinstance(node, ast.If)]
        assert len(guard_blocks) == 1  # only the __main__ delegation guard
        assert "__name__" in ast.dump(guard_blocks[0].test)
        top_level = [node for node in tree.body if not isinstance(node, keep)]
        assert [node for node in top_level if node not in guard_blocks] == []


# ---------------------------------------------------------------------------
# Inno Setup script contract
# ---------------------------------------------------------------------------


class TestInstallerScript:
    def _iss_text(self) -> str:
        return ISS_PATH.read_text(encoding="utf-8")

    def test_stable_app_id(self) -> None:
        text = self._iss_text()
        assert APP_ID in text
        assert re.search(r"^AppId=\{\{[0-9A-Fa-f-]+\}$", text, re.M)

    def test_version_comes_from_defines_never_literal(self) -> None:
        text = self._iss_text()
        assert "AppVersion={#VSCANNER_VERSION}" in text
        assert "VersionInfoVersion={#VSCANNER_RESOURCE_VERSION}" in text
        assert "VersionInfoProductVersion={#VSCANNER_RESOURCE_VERSION}" in text
        assert not re.search(r"3\.0\.0a0", text)

    def test_per_user_low_privilege_install(self) -> None:
        text = self._iss_text()
        assert "PrivilegesRequired=lowest" in text
        assert "DefaultDirName={localappdata}\\Programs\\V-Scanner" in text

    def test_publisher_is_the_verified_github_org(self) -> None:
        text = self._iss_text()
        assert "AppPublisher=ToTheBlankWorld" in text
        assert "https://github.com/ToTheBlankWorld/V-Scanner" in text

    def test_desktop_shortcut_is_unchecked_by_default(self) -> None:
        text = self._iss_text()
        assert "Flags: unchecked" in text
        assert '"desktopicon"' in text

    def test_stage_dir_is_the_only_file_source(self) -> None:
        text = self._iss_text()
        assert 'Source: "{#VSCANNER_STAGE_DIR}\\*"' in text
        assert "recursesubdirs" in text

    def test_icon_and_executable_references(self) -> None:
        text = self._iss_text()
        assert "SetupIconFile=" in text and "vscanner.ico" in text
        assert "UninstallDisplayIcon={app}\\V-Scanner.exe" in text
        assert 'Filename: "{app}\\V-Scanner.exe"' in text

    def test_missing_parameters_are_hard_errors(self) -> None:
        text = self._iss_text()
        for directive in ("VSCANNER_VERSION", "VSCANNER_RESOURCE_VERSION",
                          "VSCANNER_STAGE_DIR", "VSCANNER_OUT_DIR",
                          "VSCANNER_REPO_ROOT"):
            assert f"#ifndef {directive}" in text

    def test_defines_avoid_ispp_collision_names(self) -> None:
        # Root-caused during Stage 14: /DPRODUCT_VERSION collides with an
        # ISPP built-in (expansion rendered "ProductVersion", which ISCC
        # rejects as an invalid VersionInfoVersion value).
        text = self._iss_text()
        for forbidden in ("{#PRODUCT_VERSION}", "{#StageDir}", "{#RepoRoot}"):
            assert forbidden not in text

    def test_uninstall_defaults_to_retaining_user_data(self) -> None:
        text = self._iss_text()
        assert "MB_DEFBUTTON2" in text  # "No" (retain) is the default answer
        assert "DelTree(" in text       # deletion only behind the explicit Yes
        assert "localappdata}\\vscanner" in text
        assert "usUninstall" in text

    def test_silent_uninstall_skips_the_data_question(self) -> None:
        # Root-caused during Stage 14: in silent uninstall runs Inno still
        # displays [Code] MsgBox dialogs (UninstallSilent := Silent or
        # VerySilent), so without the guard /VERYSILENT /UNINSTALL hangs on
        # the hidden prompt; silent runs take the retain-by-default path.
        text = self._iss_text()
        assert "if UninstallSilent() then" in text

    def test_no_network_or_shell_download_hooks(self) -> None:
        text = self._iss_text().lower()
        for forbidden in ("powershell", "iexplore", "wget", "curl",
                          "downloadplugin"):
            assert forbidden not in text

    def test_no_device_operations_in_hooks(self) -> None:
        text = self._iss_text().lower()
        assert "adb" not in text
        assert "scrcpy" not in text


# ---------------------------------------------------------------------------
# Tool discovery and failure propagation
# ---------------------------------------------------------------------------


class TestToolchainPlumbing:
    def test_find_iscc_fails_actionably(
        self, fake_iscc_env: None, tmp_path: Path
    ) -> None:
        with pytest.raises(build_module.BuildError, match=r"jrsoftware|ISCC"):
            build_module.find_iscc(tmp_path / "repo")

    def test_find_iscc_explicit_file(self, tmp_path: Path) -> None:
        iscc = tmp_path / "custom" / "ISCC.exe"
        iscc.parent.mkdir(parents=True)
        iscc.write_bytes(b"")
        assert build_module.find_iscc(tmp_path / "repo", iscc) == iscc.resolve()

    def test_find_iscc_explicit_directory(self, tmp_path: Path) -> None:
        iscc = tmp_path / "custom" / "ISCC.exe"
        iscc.parent.mkdir(parents=True)
        iscc.write_bytes(b"")
        found = build_module.find_iscc(tmp_path / "repo", tmp_path / "custom")
        assert found == iscc.resolve()

    def test_find_iscc_finds_portable_tools_dir(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        local = tmp_path / "localappdata"
        monkeypatch.setenv("LOCALAPPDATA", str(local))
        monkeypatch.delenv("VSCANNER_INNO_SETUP", raising=False)
        iscc = local / "vscanner-build" / "inno" / "innosetup-6.5.4" / "ISCC.exe"
        iscc.parent.mkdir(parents=True)
        iscc.write_bytes(b"")
        assert build_module.find_iscc(tmp_path / "repo") == iscc

    def test_nuitka_failure_propagates_and_logs(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        stage_root = tmp_path / "stage"
        stage_root.mkdir()
        (stage_root / "vscanner_desktop.py").write_text("", encoding="utf-8")

        def fake_run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess:
            sink = kwargs["stdout"]
            sink.write("fake compile error\n")
            return subprocess.CompletedProcess(args=[], returncode=7)

        monkeypatch.setattr(build_module.subprocess, "run", fake_run)
        with pytest.raises(build_module.BuildError, match="exit code 7"):
            build_module.run_nuitka(
                stage_root, tmp_path / "work",
                version="3.0.0a0", numeric_version="3.0.0",
                icon_path=ICON_PATH, log_dir=tmp_path / "work" / "logs")
        log = tmp_path / "work" / "logs" / "nuitka.log"
        assert log.is_file()
        assert "fake compile error" in log.read_text(encoding="utf-8")

    def test_nuitka_missing_dist_propagates(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        stage_root = tmp_path / "stage"
        stage_root.mkdir()
        (stage_root / "vscanner_desktop.py").write_text("", encoding="utf-8")
        monkeypatch.setattr(
            build_module.subprocess, "run",
            lambda *a, **k: subprocess.CompletedProcess(args=[], returncode=0))
        with pytest.raises(build_module.BuildError, match="dist"):
            build_module.run_nuitka(
                stage_root, tmp_path / "work",
                version="3.0.0a0", numeric_version="3.0.0",
                icon_path=ICON_PATH, log_dir=tmp_path / "work" / "logs")

    def test_installer_failure_propagates_and_logs(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        dist = _fake_dist(tmp_path)
        iscc = tmp_path / "ISCC.exe"
        iscc.write_bytes(b"")
        repo = tmp_path / "repo"
        repo.mkdir()
        _write(repo / "packaging_windows" / "installer.iss", "; iss\n")

        def fake_run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess:
            sink = kwargs["stdout"]
            sink.write("; ISCC exit 2\n")
            return subprocess.CompletedProcess(args=[], returncode=2)

        monkeypatch.setattr(build_module.subprocess, "run", fake_run)
        with pytest.raises(build_module.BuildError, match="exit code 2"):
            build_module.compile_installer(
                dist, tmp_path / "work",
                version="3.0.0a0", numeric_version="3.0.0",
                iscc_path=iscc, repo_root=repo,
                log_dir=tmp_path / "work" / "logs")

    def test_installer_missing_dist_fails_before_compile(
        self, tmp_path: Path
    ) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        _write(repo / "packaging_windows" / "installer.iss", "; iss\n")
        with pytest.raises(build_module.BuildError, match="distribution directory"):
            build_module.compile_installer(
                tmp_path / "absent", tmp_path / "work",
                version="3.0.0a0", numeric_version="3.0.0",
                iscc_path=tmp_path / "ISCC.exe", repo_root=repo,
                log_dir=tmp_path / "work" / "logs")

    def test_missing_installer_script_fails_before_compile(
        self, tmp_path: Path
    ) -> None:
        dist = _fake_dist(tmp_path)
        repo = tmp_path / "repo"
        repo.mkdir()
        with pytest.raises(build_module.BuildError, match="installer.iss"):
            build_module.compile_installer(
                dist, tmp_path / "work",
                version="3.0.0a0", numeric_version="3.0.0",
                iscc_path=tmp_path / "ISCC.exe", repo_root=repo,
                log_dir=tmp_path / "work" / "logs")

    def test_work_dir_must_be_outside_repo(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        with pytest.raises(build_module.BuildError, match="outside the repository"):
            build_module.guard_work_dir(repo, repo / "build")
        outside = build_module.guard_work_dir(repo, tmp_path / "work")
        assert outside == (tmp_path / "work").resolve()


# ---------------------------------------------------------------------------
# Icon asset
# ---------------------------------------------------------------------------


class TestIconAsset:
    def test_committed_icon_structure(self) -> None:
        assert validation_module.validate_icon_file(ICON_PATH) == [
            16, 24, 32, 48, 64, 128, 256]

    def test_icon_header(self) -> None:
        data = ICON_PATH.read_bytes()
        reserved, icon_type, count = struct.unpack_from("<HHH", data, 0)
        assert (reserved, icon_type, count) == (0, 1, 7)

    def test_256_entry_uses_size_sentinel(self) -> None:
        payloads = [(16, b"a" * 20), (64, b"b" * 20), (256, b"c" * 20)]
        assembled = assemble_ico(payloads)
        entry_256 = struct.unpack_from("<BBBBHHII", assembled, 6 + 2 * 16)
        assert entry_256[0] == 0 and entry_256[1] == 0  # 0 = 256 sentinel
        assert entry_256[6] == 20                       # payload length check


# ---------------------------------------------------------------------------
# Naming contract
# ---------------------------------------------------------------------------


class TestNamingContract:
    def test_executable_name_constant(self) -> None:
        assert EXECUTABLE_NAME == "V-Scanner.exe"

    def test_launcher_filename_matches_policy(self) -> None:
        assert staging_module.LAUNCHER_NAME == "vscanner_desktop.py"
        assert LAUNCHER_PATH.is_file()
