"""Config-service tests (Stage 03): strict load/save, R-08 legacy migration."""

from __future__ import annotations

import json

import pytest

from vscanner.core.errors import ConfigError, ConfigSchemaOutdated, VScannerError
from vscanner.services.config import (
    LEGACY_CONFIG_FILENAME,
    ConfigService,
    ConfigSnapshot,
)


@pytest.fixture
def cfg_path(tmp_path):
    path = tmp_path / "config" / "adb_config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


class TestLoadHonesty:
    def test_missing_file_is_valid_first_run_state(self, cfg_path):
        snapshot = ConfigService(cfg_path).load()
        assert snapshot.adb_path is None
        assert snapshot.schema_version == 1 and not snapshot.has_path
        assert not cfg_path.exists()  # reading never creates state

    def test_malformed_json_raises_typed(self, cfg_path):
        cfg_path.write_text("{not valid json", encoding="utf-8")
        with pytest.raises(ConfigError) as exc:
            ConfigService(cfg_path).load()
        assert "malformed JSON" in exc.value.message

    def test_non_object_json_rejected(self, cfg_path):
        cfg_path.write_text("[1, 2, 3]", encoding="utf-8")
        with pytest.raises(ConfigError) as exc:
            ConfigService(cfg_path).load()
        assert "JSON object" in exc.value.message

    def test_empty_adb_path_string_rejected(self, cfg_path):
        cfg_path.write_text('{"adb_path": "   "}', encoding="utf-8")
        with pytest.raises(ConfigError):
            ConfigService(cfg_path).load()

    def test_non_string_adb_path_rejected(self, cfg_path):
        cfg_path.write_text('{"adb_path": 42}', encoding="utf-8")
        with pytest.raises(ConfigError):
            ConfigService(cfg_path).load()

    def test_oversize_file_refused(self, cfg_path):
        cfg_path.write_text('{"x": "' + "A" * 1_100_000 + '"}', encoding="utf-8")
        with pytest.raises(ConfigError) as exc:
            ConfigService(cfg_path).load()
        assert "implausibly large" in exc.value.message

    def test_unknown_future_schema_version_raises_outdated(self, cfg_path):
        cfg_path.write_text('{"schema_version": 99, "adb_path": "x"}', encoding="utf-8")
        with pytest.raises(ConfigSchemaOutdated):
            ConfigService(cfg_path).load()

    def test_non_integer_schema_version_raises_outdated(self, cfg_path):
        cfg_path.write_text('{"schema_version": "one"}', encoding="utf-8")
        with pytest.raises(ConfigSchemaOutdated):
            ConfigService(cfg_path).load()

    def test_config_schema_outdated_is_config_error_is_vscanner_error(self):
        assert issubclass(ConfigSchemaOutdated, ConfigError)
        assert issubclass(ConfigError, VScannerError)


class TestLegacyLayoutCompat:
    def test_legacy_envelope_less_file_is_accepted_as_v1(self, cfg_path):
        """R-08 read side: an untouched legacy ``cli/adb_config.json`` content
        keeps loading after the engine switch."""
        cfg_path.write_text('{"adb_path": "C:/platform-tools/adb.exe"}', encoding="utf-8")
        snapshot = ConfigService(cfg_path).load()
        assert snapshot.adb_path == "C:/platform-tools/adb.exe"
        assert snapshot.schema_version == 1


class TestSaveAndRoundtrip:
    def test_save_writes_envelope_and_roundtrips(self, cfg_path):
        service = ConfigService(cfg_path)
        returned = service.save("C:/adb/adb.exe")
        assert returned.adb_path == "C:/adb/adb.exe"
        data = json.loads(cfg_path.read_text(encoding="utf-8"))
        assert data == {"adb_path": "C:/adb/adb.exe", "schema_version": 1}

    def test_save_preserves_unknown_fields(self, cfg_path):
        cfg_path.write_text(
            json.dumps({"adb_path": "old", "user_theme": "dark"}), encoding="utf-8"
        )
        service = ConfigService(cfg_path)
        service.save("new")
        data = json.loads(cfg_path.read_text(encoding="utf-8"))
        assert data["adb_path"] == "new"
        assert data["user_theme"] == "dark"  # extras never silently vanish

    def test_save_none_writes_null(self, cfg_path):
        service = ConfigService(cfg_path)
        service.save("x")
        service.save(None)
        assert json.loads(cfg_path.read_text(encoding="utf-8"))["adb_path"] is None

    def test_save_blank_path_rejected(self, cfg_path):
        with pytest.raises(ConfigError):
            ConfigService(cfg_path).save("   ")

    def test_save_is_atomic_no_tmp_leftovers(self, cfg_path):
        service = ConfigService(cfg_path)
        service.save("x")
        leftovers = [p.name for p in cfg_path.parent.iterdir() if p.name != cfg_path.name]
        assert leftovers == []

    def test_save_over_too_new_schema_recovers(self, cfg_path):
        """schema_version 99 is unread-forward-rejected, but an explicit save
        recovers the file to v1 (read-modify-write with a fresh base)."""
        cfg_path.write_text('{"schema_version": 99}', encoding="utf-8")
        service = ConfigService(cfg_path)
        service.save("C:/adb/adb.exe")
        assert service.load().adb_path == "C:/adb/adb.exe"
        assert json.loads(cfg_path.read_text(encoding="utf-8"))["schema_version"] == 1


class TestLegacyMigrationR08:
    def test_import_legacy_config_valid(self, tmp_path, cfg_path):
        legacy = tmp_path / LEGACY_CONFIG_FILENAME
        legacy.write_text('{"adb_path": "C:/legacy/adb.exe"}', encoding="utf-8")
        snapshot = ConfigService(cfg_path).import_legacy_config(legacy)
        assert snapshot.adb_path == "C:/legacy/adb.exe"
        assert ConfigService(cfg_path).load().adb_path == "C:/legacy/adb.exe"

    def test_import_legacy_config_malformed_leaves_target_clean(self, tmp_path, cfg_path):
        legacy = tmp_path / LEGACY_CONFIG_FILENAME
        legacy.write_text("{broken", encoding="utf-8")
        ConfigService(cfg_path).save("C:/safe/adb.exe")
        with pytest.raises(ConfigError):
            ConfigService(cfg_path).import_legacy_config(legacy)
        # target file untouched by a failed migration
        assert ConfigService(cfg_path).load().adb_path == "C:/safe/adb.exe"

    def test_repo_legacy_macro_branches(self, tmp_path, monkeypatch, cfg_path):
        """Fresh-clone default: no ``cli/adb_config.json`` → None (no-op).
        When a legacy file exists beside the engine's default layout it is
        imported. Both branches are exercised against a fabricated repo root
        via the module's ``__file__`` seam (the real repo may or may not
        carry a local legacy file)."""
        import vscanner.services.config as config_module

        fake_root = tmp_path / "fake_repo"
        (fake_root / "cli").mkdir(parents=True)
        (fake_root / "vscanner" / "services").mkdir(parents=True)
        monkeypatch.setattr(
            config_module, "__file__",
            str(fake_root / "vscanner" / "services" / "config.py"),
        )

        # Absent → honest no-op:
        assert ConfigService(cfg_path).import_repo_legacy_config() is None

        # Present → imported into the engine config:
        (fake_root / "cli" / LEGACY_CONFIG_FILENAME).write_text(
            '{"adb_path": "C:/migrated/adb.exe"}', encoding="utf-8"
        )
        snapshot = ConfigService(cfg_path).import_repo_legacy_config()
        assert snapshot is not None
        assert snapshot.adb_path == "C:/migrated/adb.exe"

    def test_snapshot_is_frozen(self):
        snapshot = ConfigSnapshot(adb_path="x")
        with pytest.raises(AttributeError):
            snapshot.adb_path = "y"
