"""Known-defect regression tests (Stage 02 — section F).

Each test explicitly distinguishes:
  (a) characterization — records current behavior (never asserts it is correct);
  (b) required behavior — written as narrowly scoped ``xfail`` so the suite
      stays green today and flips automatically when remediation lands.

All device access is mocked; no test blesses fabricated sensor readings,
incorrect root status, silent extraction failure or unsafe DB rewrites.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

import digital_forensics as df
import permissions
import scanner
from conftest import FakeAdb

CLI_DIR = Path(scanner.__file__).resolve().parent


def _module_source(name: str) -> str:
    return (CLI_DIR / f"{name}.py").read_text(encoding="utf-8")


BIN_SCRIPT = "import sys; sys.stdout.buffer.write(b'SQLite\\x00\\x89PNG\\xff\\xfe binary')"


class TestR01DuplicateAdminOperationsMenu:
    def test_admin_operations_menu_is_defined_exactly_once(self):
        """R-01 remediated (Stage 03): exactly one module-level definition.

        The Stage 02 pair (characterization + xfail requirement) collapses
        into this single assertion now that the defect is fixed; the
        duplicate was removed in the same commit that re-wired legacy config
        handling (see SECURITY_AND_REMEDIATION_PLAN R-01).
        """
        tree = ast.parse(_module_source("main"))
        defs = [n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == "admin_operations_menu"]
        assert len(defs) == 1


class TestR02ShadowedAdbConfigFunctions:
    def test_main_delegates_to_adb_setup_helpers(self):
        """R-02 remediated (Stage 03): main.py imports the adb_setup helpers
        and no longer redefines ``load_adb_config``/``save_adb_config`` — the
        single authority is the config service behind the adb_setup adapter.
        """
        tree = ast.parse(_module_source("main"))
        imported, defined = [], []
        for node in tree.body:
            if isinstance(node, ast.ImportFrom) and node.module == "adb_setup":
                imported.extend(a.name for a in node.names)
            if isinstance(node, ast.FunctionDef) and node.name in (
                "load_adb_config", "save_adb_config",
            ):
                defined.append(node.name)
        assert {"load_adb_config", "save_adb_config"} <= set(imported)
        assert not defined, "shadowing definitions must stay removed (R-02)"

    def test_authoritative_loader_raises_typed_error_on_malformed_config(self, isolated_config):
        """R-02 required behavior, now owned by the authoritative loader:
        the vscanner config service raises ConfigError on malformed input;
        the legacy adb_setup adapter prints a visible warning and returns
        None for compatibility (R-02 retention path documented in the plan).
        """
        from vscanner.services.config import ConfigService
        from vscanner.core.errors import ConfigError

        isolated_config.write_text("{not valid json", encoding="utf-8")
        with pytest.raises(ConfigError):
            ConfigService(isolated_config).load()


class TestR03MissingForensicsExtractor:
    def test_extract_all_dbs_from_dir_is_missing(self):
        """R-03 characterization: the method four extractors call has no definition."""
        assert not hasattr(df.DeviceForensics, "_extract_all_dbs_from_dir")

    def test_rooted_extractor_fails_silently(self, fake_adb_rooted):
        """R-03 characterization: extract_call_logs on a rooted device reaches
        the missing method; the broad ``except`` turns the latent
        AttributeError into a plain ``False`` (silent feature failure)."""
        fns = df.DeviceForensics(fake_adb_rooted)
        assert fns.is_rooted is True
        assert fns.extract_call_logs() is False  # documented: not a working feature


class TestR04FabricatedSensorFallback:
    @staticmethod
    def _sensor_interface(monkeypatch):
        fake = FakeAdb(responses=[("", "", 1)])
        monkeypatch.setattr(
            scanner.ADBInterface, "_run_cmd",
            lambda self, cmd, timeout=30: fake._run_cmd(cmd, timeout),
        )
        return scanner.ADBInterface()

    def test_empty_dumpsys_yields_fabricated_default_sensors(self, monkeypatch):
        """R-04 characterization: when dumpsys provides no data, the interface
        returns hardcoded plausible-looking entries (units as values)."""
        values = self._sensor_interface(monkeypatch).get_sensor_values_live()
        assert values == {
            "Accelerometer (X, Y, Z)": ["m/s²"],
            "Magnetometer (X, Y, Z)": ["µT"],
            "Gyroscope (X, Y, Z)": ["°/s"],
            "Light Sensor": ["Lux"],
            "Proximity Sensor": ["cm"],
        }, "fabricated fallback changed — update R-04 evidence"

    @pytest.mark.xfail(strict=False, reason="R-04 owned by Stage 08: SensorReading(UNAVAILABLE) model required")
    def test_no_sensor_data_means_no_invented_rows(self, monkeypatch):
        """R-04 required behavior: missing device data must yield no rows
        (an honest UNAVAILABLE state), never synthetic entries."""
        values = self._sensor_interface(monkeypatch).get_sensor_values_live()
        assert values == {}


class TestR05RootDefaultsToRooted:
    def test_failed_detection_assumes_rooted(self, fake_adb_detection_fails):
        """R-05 characterization: ``_check_root_safe`` returns True when both
        probes fail — the optimistic default that mislabels non-root devices."""
        fns = df.DeviceForensics(fake_adb_detection_fails)
        assert fns.is_rooted is True  # documents current behavior

    @pytest.mark.xfail(strict=False, reason="R-05 owned by Stage 08: tri-state ROOTED/NOT_ROOTED/UNKNOWN required")
    def test_failed_detection_must_not_report_root(self, fake_adb_detection_fails):
        """R-05 required behavior: UNKNOWN must be distinguishable from rooted."""
        fns = df.DeviceForensics(fake_adb_detection_fails)
        assert fns.is_rooted is not True


class TestR06SecretPatternsNeverExecuted:
    @staticmethod
    def _pattern_uses(module: str) -> int:
        tree = ast.parse(_module_source(module))
        return sum(
            1 for node in ast.walk(tree)
            if isinstance(node, ast.Name) and node.id == "INSECURE_URL_PATTERNS"
            and isinstance(node.ctx, ast.Load)
        )

    def test_credential_patterns_present_but_unwired(self):
        """R-06 characterization: permissions.py defines credential regexes;
        scanner.py imports the list but has zero runtime name usages."""
        assert permissions.INSECURE_URL_PATTERNS  # the patterns exist
        # Import-sites are ast.alias nodes, not ast.Name — count Name loads only.
        assert self._pattern_uses("scanner") == 0

    @pytest.mark.xfail(strict=False, reason="R-06 owned by Stage 08: host-side APK string extraction wiring")
    def test_credential_patterns_are_actually_applied(self):
        """R-06 required behavior: at least one consumer executes the patterns."""
        assert self._pattern_uses("scanner") > 0


class TestR07TextModeDatabaseRewrite:
    def test_binary_stream_decoded_as_text_corrupts_bytes(self):
        """R-07 characterization: the forensics DB path feeds binary bytes
        through text decoding (``_run_cmd`` uses errors='replace') and then
        re-encodes with the same lenient setting. A real subprocess emitting
        non-UTF-8 bytes shows the mechanism end-to-end."""
        raw = b"SQLite\x00\x89PNG\xff\xfe binary"
        ai = scanner.ADBInterface(adb_path=sys.executable)
        stdout, _, code = ai._run_cmd(["-c", BIN_SCRIPT])
        assert code == 0
        written = stdout.encode("utf-8", errors="replace")  # extractor's write transform
        assert written != raw, "round-trip unexpectedly lossless — R-07 evidence needs update"
        assert b"\xef\xbf\xbd" in written  # U+FFFD replacements baked into the "database"

    @pytest.mark.xfail(strict=False, reason="R-07 owned by Stage 08: byte-safe ADB client mode required (exec-out)")
    def test_requirement_byte_safe_binary_extraction(self):
        """R-07 required behavior: binary payloads survive the scan/extraction
        path byte-identically. Flips at Stage 08 (exec-out/pull + hashes)."""
        raw = b"SQLite\x00\x89PNG\xff\xfe binary"
        ai = scanner.ADBInterface(adb_path=sys.executable)
        stdout, _, _ = ai._run_cmd(["-c", BIN_SCRIPT])
        assert stdout.encode("utf-8", errors="replace") == raw
