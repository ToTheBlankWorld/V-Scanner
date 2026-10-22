"""Stage 15 (release QA) tests — security, compatibility and artifact audit.

Toolchain-free: every test here runs without Nuitka or ISCC. The runtime and
artifact checks that need real compiled outputs are executed by the Stage 15
build-host audit and recorded in ``STAGE_15_IMPLEMENTATION_REPORT.md`` (what
these tests lock is the *policy* behind those checks).

Covers: the D1 staging link-refusal fix (a planted junction/symlink must
never silently pull foreign content into a release tree), the D2
distribution content policy (exactly one exe, zero stray Python files), the
Inno script's machine-independence (no baked drive-letter paths, define-only
version inputs, staging dir as the single source), spaced ADB/scrcpy paths
kept whole through every argv seam, the documentation-consistency pass, and
the version-authority chain that names the release artifacts.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import List, Optional

import pytest

from packaging_windows import EXECUTABLE_NAME
from packaging_windows import staging as staging_module
from packaging_windows import validation as validation_module
from packaging_windows import versioning as versioning_module

_PACKAGING_ROOT = Path(__file__).resolve().parents[2] / "packaging_windows"
ISS_PATH = _PACKAGING_ROOT / "installer.iss"
REPO_ROOT = Path(__file__).resolve().parents[2]
_DOCS = REPO_ROOT / "docs" / "vscanner-3"


def _write(path: Path, text: str = "x = 1\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# D1 regression: staging never follows links (junction/symlink refusal)
# ---------------------------------------------------------------------------


class TestStagingLinkPolicy:
    def _repo(self, tmp_path: Path) -> Path:
        repo = tmp_path / "repo"
        _write(repo / "vscanner" / "__init__.py")
        _write(repo / "vscanner" / "core" / "paths.py")
        _write(repo / "ui_desktop" / "__init__.py")
        _write(repo / "packaging_windows" / staging_module.LAUNCHER_NAME)
        return repo

    def _stage(self, tmp_path: Path, index: int) -> Path:
        stage = tmp_path / f"stage{index}"
        stage.mkdir()
        return stage

    def test_junction_inside_package_tree_is_refused(self, tmp_path: Path) -> None:
        # A real NTFS junction (creatable without elevation on Windows)
        # planted inside a staged package tree, pointing at an outside
        # directory that holds content no release may carry.
        repo = self._repo(tmp_path)
        outside = tmp_path / "outside"
        _write(outside / "secret.txt", "MACHINE_SECRET")
        junction = repo / "vscanner" / "core" / "vendor_link"
        proc = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(junction), str(outside)],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            pytest.skip(f"junction creation unavailable: {proc.stderr.strip()}")
        stage = self._stage(tmp_path, 1)
        with pytest.raises(ValueError, match="link"):
            staging_module.stage_release_tree(repo, stage)
        if stage.exists():
            names = {path.name for path in stage.rglob("*")}
            assert "secret.txt" not in names

    def test_detector_is_negative_on_plain_trees(self, tmp_path: Path) -> None:
        repo = self._repo(tmp_path)
        assert staging_module.first_link_entry(repo / "vscanner") is None
        assert staging_module.first_link_entry(repo / "ui_desktop") is None

    def test_detector_finds_a_real_symlink(self, tmp_path: Path) -> None:
        # File/symlink creation usually needs privileges or developer mode
        # on Windows; skip when the OS refuses, the detector contract is
        # what the test locks.
        target = tmp_path / "target"
        _write(target / "contested.txt", "foreign")
        link = tmp_path / "linkdir"
        try:
            os.symlink(target, link, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            pytest.skip(f"symlink creation unavailable: {exc}")
        found = staging_module.first_link_entry(tmp_path)
        assert found is not None
        assert found.name == "linkdir"

    def test_launcher_link_is_refused(self, tmp_path: Path) -> None:
        repo = self._repo(tmp_path)
        launcher = repo / "packaging_windows" / staging_module.LAUNCHER_NAME
        foreign = tmp_path / "foreign_launcher.py"
        foreign.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
        try:
            os.remove(launcher)
            os.symlink(foreign, launcher)
        except (OSError, NotImplementedError) as exc:
            pytest.skip(f"symlink creation unavailable: {exc}")
        with pytest.raises(ValueError, match="regular file"):
            staging_module.stage_release_tree(repo, self._stage(tmp_path, 2))

    def test_clean_repo_stages_normally(self, tmp_path: Path) -> None:
        repo = self._repo(tmp_path)
        report = staging_module.stage_release_tree(
            repo, self._stage(tmp_path, 3)
        )
        assert report.copied_files >= 4  # three package files + launcher


# ---------------------------------------------------------------------------
# D2 regression: exactly one exe, zero stray Python files in a distribution
# ---------------------------------------------------------------------------


def _make_dist(tmp_path: Path) -> Path:
    dist = tmp_path / "V-Scanner.dist"
    dist.mkdir()
    (dist / "V-Scanner.exe").write_bytes(b"MZ" + b"\x00" * 16)
    for dll in ("python3.dll", "python312.dll", "Qt6Core.dll",
                "Qt6Gui.dll", "Qt6Widgets.dll"):
        (dist / dll).write_bytes(b"MZ" + b"\x00" * 4)
    pyside = dist / "PySide6" / "plugins" / "platforms"
    pyside.mkdir(parents=True)
    (pyside / "qwindows.dll").write_bytes(b"MZ" + b"\x00" * 4)
    (dist / "PySide6" / "shiboken6.abi3.dll").write_bytes(b"MZ" + b"\x00" * 4)
    return dist


class TestDistributionContentPolicy:
    def test_valid_minimal_dist_passes(self, tmp_path: Path) -> None:
        dist = _make_dist(tmp_path)
        report = validation_module.validate_distribution(dist)
        assert report.executable.name == EXECUTABLE_NAME

    def test_extra_executable_is_rejected(self, tmp_path: Path) -> None:
        dist = _make_dist(tmp_path)
        (dist / "mystery.exe").write_bytes(b"MZ" + b"\x00" * 8)
        with pytest.raises(
            validation_module.ValidationError, match="mystery.exe"
        ) as excinfo:
            validation_module.validate_distribution(dist)
        assert "unexpected executable" in str(excinfo.value)

    def test_stray_python_source_is_rejected(self, tmp_path: Path) -> None:
        dist = _make_dist(tmp_path)
        _write(dist / "leftover_module.py")
        with pytest.raises(
            validation_module.ValidationError, match="leftover_module.py"
        ):
            validation_module.validate_distribution(dist)

    def test_stray_bytecode_is_rejected(self, tmp_path: Path) -> None:
        dist = _make_dist(tmp_path)
        (dist / "cached.pyc").write_bytes(b"")
        with pytest.raises(
            validation_module.ValidationError, match="cached.pyc"
        ):
            validation_module.validate_distribution(dist)


# ---------------------------------------------------------------------------
# Installer input confinement: nothing machine-specific in the ISS text
# ---------------------------------------------------------------------------


class TestInstallerMachineIndependence:
    def test_no_drive_letter_paths_in_installer_script(self) -> None:
        # The ISS references defines and Inno runtime constants only; a
        # drive letter would mean a build-machine path got baked in.
        # ({localappdata}, {app}, {group} are Inno constants, not paths.)
        text = ISS_PATH.read_text(encoding="utf-8")
        assert not re.search(r"[A-Za-z]:\\", text)

    def test_installer_version_inputs_come_from_defines_only(self) -> None:
        text = ISS_PATH.read_text(encoding="utf-8")
        assert "{#VSCANNER_VERSION}" in text
        assert "{#VSCANNER_RESOURCE_VERSION}" in text
        assert not re.search(r"AppVersion=[\d]", text)

    def test_only_the_stage_dir_is_a_file_source(self) -> None:
        text = ISS_PATH.read_text(encoding="utf-8")
        sources = re.findall(r'^Source:\s*"([^"]+)"', text, re.M)
        assert sources == ["{#VSCANNER_STAGE_DIR}\\*"]


# ---------------------------------------------------------------------------
# ADB/scrcpy paths containing spaces: argv-list discipline at both seams
# ---------------------------------------------------------------------------


class TestSpacedToolPaths:
    SPACED_ADB = "C:/Program Files (x86)/platform tools/adb.exe"
    SPACED_SCRCPY = "C:/Users/some user/tools/scrcpy.exe"

    def test_adb_command_keeps_spaced_binary_path_whole(self) -> None:
        from vscanner.services.adb.client import build_adb_command

        argv = build_adb_command(self.SPACED_ADB, ["shell", "getprop"])
        assert argv[0] == self.SPACED_ADB
        assert isinstance(argv, list)
        assert all(isinstance(part, str) for part in argv)

    def test_adb_client_argv_carries_spaced_path_and_serial(self) -> None:
        from vscanner.services.adb.client import SubprocessAdbClient

        client = SubprocessAdbClient(self.SPACED_ADB, serial="EMU-1")
        argv = client._full(["install", "/tmp/app.apk"])
        assert argv[:4] == [self.SPACED_ADB, "-s", "EMU-1", "install"]

    def test_mirroring_spawn_preserves_spaced_scrcpy_path(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from vscanner.core.models import ToolState
        from vscanner.services.mirroring import (
            MirrorOptions,
            ScreenMirrorService,
        )

        spaced_scrcpy = self.SPACED_SCRCPY

        class FakeToolStatus:
            state = ToolState.VALIDATED
            path = spaced_scrcpy

        spawned: List[List[str]] = []

        class FakeProc:
            def __init__(self, cmd: List[str], **kwargs: object) -> None:
                spawned.append(list(cmd))
                self.pid = 99

            def poll(self) -> Optional[int]:
                return None

            def terminate(self) -> None:
                return None

        monkeypatch.setattr(
            "vscanner.services.mirroring.subprocess.Popen", FakeProc
        )
        service = ScreenMirrorService(
            adb_path=lambda: self.SPACED_ADB,
            scrcpy_path=lambda: self.SPACED_SCRCPY,
            tool_status=lambda: FakeToolStatus(),
        )
        handle = service.launch(MirrorOptions())
        assert spawned[0][0] == self.SPACED_SCRCPY
        assert handle.command[0] == self.SPACED_SCRCPY
        assert all(isinstance(part, str) for part in spawned[0])
        service.stop()


# ---------------------------------------------------------------------------
# Documentation consistency (Stage 15 roadmap scope)
# ---------------------------------------------------------------------------


class TestDocumentationConsistency:
    def test_stage_reports_referenced_by_trackers_exist(self) -> None:
        # Every STAGE_xx_IMPLEMENTATION_REPORT reference inside the tracker
        # docs must point at a real file (a doc referencing a ghost file
        # would make the release-consistency pass dishonest).
        trackers = [
            "FEATURE_PARITY_MATRIX.md", "ROADMAP.md", "PROGRESS.md",
            "TESTING_STRATEGY.md", "ACCEPTANCE_CRITERIA.md",
        ]
        referenced: set[str] = set()
        for doc in trackers:
            text = (_DOCS / doc).read_text(encoding="utf-8")
            referenced.update(
                match.group(0)
                for match in re.finditer(r"STAGE_\d{2}_\w+\.md", text)
            )
        for name in sorted(referenced):
            assert (_DOCS / name).is_file(), f"missing doc: {name}"

    def test_stage09_through_14_reports_exist_and_are_substantial(self) -> None:
        for number in ("09", "10", "11", "12", "13", "14"):
            report = _DOCS / f"STAGE_{number}_IMPLEMENTATION_REPORT.md"
            assert report.is_file() and report.stat().st_size > 2000

    def test_roadmap_stage15_acceptance_is_recorded(self) -> None:
        text = (_DOCS / "ROADMAP.md").read_text(encoding="utf-8")
        assert "zero known security findings without owners" in text


# ---------------------------------------------------------------------------
# Version authority still derives every artifact name (release integrity)
# ---------------------------------------------------------------------------


class TestVersionAuthorityIntegrity:
    def test_quad_matches_pyproject_authority(self) -> None:
        version = versioning_module.parse_pyproject_version(
            REPO_ROOT / "pyproject.toml"
        )
        from ui_desktop import APP_VERSION

        assert version == APP_VERSION == "3.0.0a0"
        assert versioning_module.derive_version_quad(version) == "3.0.0.0"

    def test_installer_output_name_derives_from_version(self) -> None:
        text = ISS_PATH.read_text(encoding="utf-8")
        assert re.search(
            r"OutputBaseFilename=V-Scanner-\{#VSCANNER_VERSION\}-Setup", text
        )
        assert not re.search(r"3\.0\.0a0", text)
