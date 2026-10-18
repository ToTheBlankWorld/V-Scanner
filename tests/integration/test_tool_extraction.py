"""Tool-provisioning hardening tests (Stage 02 → Stage 03 update).

Fake archives are generated programmatically (no binaries committed).
Stage 02 characterized extraction safety (zipfile sanitizes traversal;
legacy tarfile did not — R-11 evidence). Stage 03 hardened both legacy
extraction paths: member/link validation + PEP 706 filter='data'. The
tests below now assert the hardened behavior; the engine has its own
validated extractors (vscanner/services/tools/_extraction.py).
All temporary directories are pytest-managed; nothing under cli/ is written.
"""

from __future__ import annotations

import io
import tarfile
import zipfile
from pathlib import Path

import pytest

import tools_manager as tm


class TestZipExtraction:
    def test_valid_archive_contents_extracted(self, tmp_path):
        archive = tmp_path / "good.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("platform-tools/adb.exe", b"MZ stub")
        out = tmp_path / "out"
        out.mkdir()
        tm.extract_windows_zip(archive, out)
        assert (out / "platform-tools" / "adb.exe").read_bytes() == b"MZ stub"

    def test_corrupt_archive_raises_zipfile_error(self, tmp_path):
        archive = tmp_path / "bad.zip"
        archive.write_bytes(b"definitely not a zip file" * 4)
        out = tmp_path / "out"
        out.mkdir()
        with pytest.raises(zipfile.BadZipFile):
            tm.extract_windows_zip(archive, out)

    def test_zip_traversal_member_rejected_after_hardening(self, tmp_path):
        """R-11 remediated (Stage 03): the legacy zip path now validates
        members explicitly and rejects traversal before any write (the
        Stage 02 probe relied on zipfile's internal sanitization)."""
        archive = tmp_path / "slip.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("../escape_should_not_exist.txt", b"x")
        out = tmp_path / "out"
        out.mkdir()
        with pytest.raises(ValueError):
            tm.extract_windows_zip(archive, out)
        assert not (tmp_path / "escape_should_not_exist.txt").exists()


class TestTarExtraction:
    def test_valid_tar_contents_extracted(self, tmp_path):
        archive = tmp_path / "good.tar.gz"
        with tarfile.open(archive, "w:gz") as tf:
            data = b"\x7fELF stub"
            info = tarfile.TarInfo("scrcpy-3.1/scrcpy")
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
        out = tmp_path / "out"
        out.mkdir()
        tm.extract_unix_tar(archive, out)
        assert (out / "scrcpy-3.1" / "scrcpy").read_bytes() == data

    def test_tar_traversal_member_rejected_after_hardening(self, tmp_path):
        """R-11 remediated (Stage 03): the legacy tar path raises before any
        write for traversal members (Stage 02 characterization documented the
        escape; the paired xfail requirement now merges into this test)."""
        archive = tmp_path / "slip.tar.gz"
        with tarfile.open(archive, "w:gz") as tf:
            info = tarfile.TarInfo("../tar_escape_required.txt")
            info.size = 1
            tf.addfile(info, io.BytesIO(b"x"))
        out = tmp_path / "out"
        out.mkdir()
        with pytest.raises(ValueError):
            tm.extract_unix_tar(archive, out)
        assert not (tmp_path / "tar_escape_required.txt").exists()

    def test_tar_symlink_escape_rejected_after_hardening(self, tmp_path):
        """R-11 required behavior: link entries pointing outside the
        destination are rejected (R-11 of the mission's extraction tests)."""
        archive = tmp_path / "symlink.tar.gz"
        with tarfile.open(archive, "w:gz") as tf:
            info = tarfile.TarInfo("inside/link")
            info.type = tarfile.SYMTYPE
            info.linkname = "../../outside_target"
            tf.addfile(info)
        out = tmp_path / "out"
        out.mkdir()
        with pytest.raises(ValueError):
            tm.extract_unix_tar(archive, out)


class TestSetupFlowsOffline:
    def test_setup_adb_short_circuits_when_present(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(tm, "TOOLS_DIR", tmp_path)
        platform_tools = tmp_path / "platform-tools"
        platform_tools.mkdir()
        (platform_tools / "adb.exe").write_bytes(b"MZ stub")  # Windows current OS
        monkeypatch.setattr(tm, "OS_TYPE", "Windows")

        def no_download(url, dest_path):  # network access would fail the test
            raise AssertionError("network access attempted although tool present")

        monkeypatch.setattr(tm, "download_file", no_download)
        assert tm.setup_adb() is True
        assert not list(tmp_path.glob("adb.zip"))

    def test_setup_adb_failure_keeps_returning_false_with_kept_archive(self, tmp_path, monkeypatch):
        """Characterization (cleanup gap, R-11 adjacent): after a failed
        extraction the temp archive is NOT deleted."""
        monkeypatch.setattr(tm, "TOOLS_DIR", tmp_path)
        monkeypatch.setattr(tm, "OS_TYPE", "Windows")
        archive = tmp_path / "adb.zip"
        archive.write_bytes(b"corrupt" * 8)
        monkeypatch.setattr(tm, "download_file", lambda url, dest: True)  # fake success
        assert tm.setup_adb() is False
        assert archive.exists()  # documents the leftover archive

    def test_missing_executable_after_extraction(self, tmp_path, monkeypatch):
        """A valid archive that does not contain adb.exe reports failure."""
        monkeypatch.setattr(tm, "TOOLS_DIR", tmp_path)
        monkeypatch.setattr(tm, "OS_TYPE", "Windows")
        archive = tmp_path / "adb.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("whatever/readme.txt", "no adb here")
        monkeypatch.setattr(tm, "download_file", lambda url, dest: True)
        assert tm.setup_adb() is False
        assert not (tmp_path / "platform-tools" / "adb.exe").exists()

    def test_check_tool_exists_unknown_tool(self, tmp_path, monkeypatch):
        monkeypatch.setattr(tm, "TOOLS_DIR", tmp_path)
        assert tm.check_tool_exists("unknown-tool") is False
