"""Shared fixtures for the V-Scanner regression suite (Stage 02).

All tests are device-free: ADB subprocesses, downloads and network access are
mocked. No test requires a connected Android device, root, or ADB/scrcpy.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

# Make the legacy CLI modules importable by bare name (they import each
# other with flat imports such as "from tools_manager import ...").
CLI_DIR = Path(__file__).resolve().parents[1] / "cli"
if str(CLI_DIR) not in sys.path:
    sys.path.insert(0, str(CLI_DIR))


def adb_completed(stdout: str = "", stderr: str = "", code: int = 0) -> subprocess.CompletedProcess:
    """Build a subprocess.CompletedProcess shaped like an ADB result."""
    return subprocess.CompletedProcess(args=[], returncode=code, stdout=stdout, stderr=stderr)


class FakeAdb:
    """Stand-in for ADBInterface recording commands and replaying responses.

    ``responses`` is a list of ``(stdout, stderr, code)`` tuples.  When one
    entry is left it is repeated for every subsequent call, so a single
    response can back an unbounded command sequence.
    """

    def __init__(self, responses: list[tuple[str, str, int]] | None = None, rooted: bool = True):
        self.calls: list[list[str]] = []
        self.responses = list(responses or [])
        if rooted and not self.responses:
            # Default to the root-detection success signature used by
            # digital_forensics._check_root_safe: first probe is
            # ["shell", "su", "-c", "echo", "rooted"].
            self.responses = [("rooted", "", 0)]

    def _run_cmd(self, cmd: list[str], timeout: int = 30):
        self.calls.append(list(cmd))
        if not self.responses:
            return "", "", 1
        if len(self.responses) == 1:
            return self.responses[0]
        return self.responses.pop(0)

    def run_text(self, cmd, timeout: float = 30.0):
        """Engine-shaped text execution (Stage 08 delegation seam):
        Engine services read ``stdout``/``stderr``/``returncode`` off the
        transport; legacy fakes replay through the same responses."""
        stdout, stderr, code = self._run_cmd(list(cmd), int(timeout))
        return subprocess.CompletedProcess(
            args=cmd, returncode=code, stdout=stdout, stderr=stderr)

    def run_bytes(self, cmd, timeout: float = 30.0) -> bytes:
        """Engine-shaped byte execution for fakes: binary-safe payloads are
        simulated by re-encoding the queued text (adequate for the seams
        legacy tests exercise; real bytes go through ADBInterface/
        SubprocessAdbClient in the engine tests)."""
        stdout, _, _ = self._run_cmd(list(cmd), int(timeout))
        return (stdout or "").encode("utf-8", errors="surrogateescape")

    def call_strings(self) -> list[str]:
        return [repr(call) for call in self.calls]


@pytest.fixture
def fake_adb_rooted() -> FakeAdb:
    """Fake ADB whose root detection succeeds (device reports `rooted`)."""
    return FakeAdb(responses=[("rooted", "", 0)])


@pytest.fixture
def fake_adb_detection_fails() -> FakeAdb:
    """Fake ADB where both root probes fail (su probe and /system/xbin/su)."""
    return FakeAdb(responses=[("", "permission denied", 1)])


@pytest.fixture
def tmp_cwd(tmp_path, monkeypatch):
    """Run a test with the current working directory inside a temp dir."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def isolated_config(monkeypatch, tmp_path):
    """Point the legacy config loader at a temp config path.

    Used to prove the CLI works without the tracked cli/adb_config.json
    (Stage 02 hygiene rule: untracking must not break consumers). After
    R-02 (Stage 03) only ``adb_setup.CONFIG_FILE`` exists — main.py no
    longer carries its own config state.
    """
    import adb_setup

    cfg = tmp_path / "adb_config.json"
    monkeypatch.setattr(adb_setup, "CONFIG_FILE", str(cfg))
    return cfg
