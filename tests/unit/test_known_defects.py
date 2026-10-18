"""Known-defect regression tests (Stage 02 — section F; Stage 08 updates).

Each test explicitly distinguishes:
  (a) characterization — records current behavior (never asserts it is correct);
  (b) required behavior — which was originally written as narrowly scoped
      ``xfail`` and flips when the remediation lands.

Stage 08 (2026-10-18): the R-03/R-04/R-05/R-06/R-07 pairs collapsed, per
the Stage 03 precedent, into fixed-behavior assertions in the same commit
as the fixes. The R-04 section additionally documents the removed legacy
fabrication fallback; R-05 covers both dishonest directions plus the
confirmed-rooted and confirmed-not-rooted semantics; R-07 keeps the
text-mode characterization (still the legitimate text contract) and flips
the byte-identity requirement onto the new byte-safe path.

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
        """R-03 remediated (Stage 08): the phantom helper stays absent."""
        assert not hasattr(df.DeviceForensics, "_extract_all_dbs_from_dir")

    def test_phantom_extractors_removed(self):
        """R-03 remediated (Stage 08): the four silent-failure extractors
        and their dead sqlite parsers no longer exist anywhere on the
        legacy adapter — a phantom op is unreachable by construction. The
        legacy menu carries exactly the eight honest operations; the
        shared-engine implementation is ``vscanner.services.forensics``.
        (Replaces the Stage 02 characterization pair, which recorded the
        old silent-failure behavior of a now-removed feature.)"""
        removed_ops = ("extract_call_logs", "extract_contacts",
                       "extract_messages", "extract_browser_history")
        for name in removed_ops:
            assert not hasattr(df.DeviceForensics, name), name
        source = _module_source("digital_forensics")
        for parser in ("_parse_call_logs", "_parse_contacts",
                       "_parse_messages", "_parse_browser_history"):
            assert parser not in source, parser


class TestR04FabricatedSensorFallback:
    """R-04 remediated (Stage 08): ``get_sensor_values_live`` delegates to
    the engine MonitoringService (honest rows only)."""

    def test_no_sensor_data_means_no_invented_rows(self, monkeypatch):
        """Empty/failing device output yields NO rows (an honest empty
        dict) — the legacy invented-unit fallback is gone."""
        values = self._sensor_interface(monkeypatch).get_sensor_values_live()
        assert values == {}

    def test_reported_rows_are_device_rows(self, monkeypatch):
        """When the device DOES report rows, exactly those rows come back
        (values carried through, nothing baked-in)."""
        fake = FakeAdb(responses=[
            ("0: Accelerometer: x=1.0,y=2.0\n1: Light sensor", "", 0)])
        monkeypatch.setattr(
            scanner.ADBInterface, "_run_cmd",
            lambda self, cmd, timeout=30: fake._run_cmd(cmd, timeout),
        )
        values = scanner.ADBInterface().get_sensor_values_live()
        assert values == {
            "Accelerometer": ["x=1.0", "y=2.0"],           # device-reported
            "Light Sensor": ["Detected and available"],     # legacy Method-2
        }                                                   # detection, kept

    @staticmethod
    def _sensor_interface(monkeypatch):
        fake = FakeAdb(responses=[("", "", 1)])
        monkeypatch.setattr(
            scanner.ADBInterface, "_run_cmd",
            lambda self, cmd, timeout=30: fake._run_cmd(cmd, timeout),
        )
        return scanner.ADBInterface()


class TestR05RootDefaultsToRooted:
    """R-05 remediated (Stage 08): verified tri-state probing end to end."""

    def test_failed_detection_must_not_report_root(self, fake_adb_detection_fails):
        """UNKNOWN is distinguishable from rooted: failed detection ⇒
        ``is_rooted`` False AND the honest tri-state word "unknown"."""
        fns = df.DeviceForensics(fake_adb_detection_fails)
        assert fns.is_rooted is not True
        assert fns.root_status == "unknown"

    def test_failed_detection_must_not_claim_not_rooted_either(self, fake_adb_detection_fails):
        """Fully failed probes must surface UNKNOWN, never a confirmed
        "not-rooted" claim (both dishonest directions removed)."""
        fns = df.DeviceForensics(fake_adb_detection_fails)
        assert fns.root_status == "unknown"

    def test_confirmed_root_is_reported(self):
        fake = FakeAdb(responses=[("uid=0(root) gid=0(root) groups=0(root)", "", 0)])
        fns = df.DeviceForensics(fake)
        assert fns.is_rooted is True
        assert fns.root_status == "rooted"

    def test_confirmed_not_rooted_when_detector_supports_it(self):
        fake = FakeAdb(responses=[
            ("", "sh: su: inaccessible or not found", 127),
            ("", "", 1),       # command -v su → absent
            ("", "", 0),       # pm list packages → no manager packages
        ])
        fns = df.DeviceForensics(fake)
        assert fns.is_rooted is False
        assert fns.root_status == "not-rooted"


class TestR06SecretPatternsNeverExecuted:
    """R-06 remediated (Stage 08): the documented credential-class
    patterns are now executed by the engine deep-scan stage
    (``vscanner.services.scanning.deep_scan``) against host-side
    extracted APK strings; findings carry redacted presentations only
    (the raw matched value never enters any artifact)."""

    def test_patterns_exist(self):
        assert permissions.INSECURE_URL_PATTERNS  # the patterns exist

    def test_patterns_actually_applied_in_deep_scan(self):
        """The deep-scan consumer executes the documented bundle (AST
        check — the legacy shim delegates; the engine stage consumes)."""
        import vscanner.services.scanning.deep_scan as deep_scan

        tree = ast.parse(Path(deep_scan.__file__).read_text(encoding="utf-8"))
        uses = sum(
            1 for node in ast.walk(tree)
            if isinstance(node, ast.Name) and node.id == "INSECURE_URL_PATTERNS"
            and isinstance(node.ctx, ast.Load)
        )
        assert uses > 0

    def test_synthetic_credential_is_detected_and_redacted(self):
        """Positive/negative behavioral pair: a synthetic secret is
        detected; ordinary non-secret text yields nothing; and the
        matched value never lands in the returned presentation."""
        from vscanner.services.scanning.deep_scan import find_credential_matches

        text = (
            'config = "plain words without credentials"\n'
            'password="CorrectHorseBatteryStaple-Alpha"\n'
        )
        hits = find_credential_matches(text)
        assert any(h.pattern_name == "password" for h in hits)
        for hit in hits:
            assert "CorrectHorseBatteryStaple" not in hit.snippet
            assert hit.value_len == len("CorrectHorseBatteryStaple-Alpha")
        assert not find_credential_matches("no secrets here; just text")


class TestR07TextModeDatabaseRewrite:
    def test_binary_stream_decoded_as_text_corrupts_bytes(self):
        """Characterization of the TEXT-mode contract (kept honest):
        ``_run_cmd`` legitimately returns text with errors='replace' — the
        extractor no longer uses it for binary payloads."""
        raw = b"SQLite\x00\x89PNG\xff\xfe binary"
        ai = scanner.ADBInterface(adb_path=sys.executable)
        stdout, _, code = ai._run_cmd(["-c", BIN_SCRIPT])
        assert code == 0
        written = stdout.encode("utf-8", errors="replace")  # old extractor's transform
        assert written != raw, "round-trip unexpectedly lossless — R-07 evidence needs update"
        assert b"\xef\xbf\xbd" in written  # U+FFFD replacements baked into the "database"

    def test_requirement_byte_safe_binary_extraction(self):
        """R-07 remediated (Stage 08): the byte-safe path
        (``_run_cmd_bytes`` / engine ``run_bytes`` adapter, exec-out
        semantics) preserves payloads byte-identically. The database
        extraction path now uses this (with sha256 verification records),
        not the text mode above."""
        raw = b"SQLite\x00\x89PNG\xff\xfe binary"
        ai = scanner.ADBInterface(adb_path=sys.executable)
        data = ai.run_bytes(["-c", BIN_SCRIPT])
        assert data == raw
