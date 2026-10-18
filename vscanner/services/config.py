"""ConfigService (SC-11 ADB-config half + R-02 single authoritative path).

Owns the only config read/write implementation in the codebase:

* strict typed errors — malformed or unsafe content raises
  :class:`ConfigError` (never silently degraded to None);
* schema envelope ``{"schema_version": 1, "adb_path": ...}`` with
  unknown-field tolerance on read (forward-compatible) and a
  ``ConfigSchemaOutdated`` guard for too-new/too-unknown versions;
* atomic writes: temp file + ``os.replace``, dirs created on demand;
* first-run migration import of the legacy ``cli/adb_config.json`` (R-08).

This service performs NO process launches; executable validation is a
separate concern (``services/adb/executable.py``) so config tests stay
subprocess-free by design.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Optional

from vscanner.core.errors import ConfigError, ConfigSchemaOutdated

__all__ = ["ConfigService", "ConfigSnapshot", "LEGACY_CONFIG_FILENAME", "SCHEMA_VERSION"]

SCHEMA_VERSION = 1
KNOWN_VERSIONS = (SCHEMA_VERSION,)
LEGACY_CONFIG_FILENAME = "adb_config.json"
_MAX_JSON_BYTES = 1_000_000  # guard against absurd files


@dataclass(frozen=True, slots=True)
class ConfigSnapshot:
    """Validated config view; unknown fields pass through unchanged."""

    adb_path: Optional[str] = None
    schema_version: int = SCHEMA_VERSION
    extras: Mapping[str, Any] = field(default_factory=dict)

    @property
    def has_path(self) -> bool:
        return bool(self.adb_path)


class ConfigService:
    """Strict read/write for the engine's JSON config file."""

    def __init__(self, config_path: Path) -> None:
        self.path = Path(config_path)

    # ------------------------------------------------------------------ #
    # read
    # ------------------------------------------------------------------ #

    def load(self) -> ConfigSnapshot:
        """Load + validate the config file.

        Missing file → empty snapshot (path None) — a missing config is a
        valid first-run state. Unreadable/malformed → ConfigError. Layout
        upgrades: legacy ``{"adb_path": ...}`` files are accepted as v1.
        """
        if not self.path.exists():
            return ConfigSnapshot()
        try:
            raw = self.path.read_bytes()
        except OSError as exc:
            raise ConfigError(
                f"config file {self.path} is not readable: {exc}",
                {"path": str(self.path), "cause": str(exc)},
            ) from exc
        if len(raw) > _MAX_JSON_BYTES:
            raise ConfigError(
                "config file is implausibly large (>1 MiB); refusing to load",
                {"path": str(self.path), "size": len(raw)},
            )
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ConfigError(
                f"config file {self.path} is malformed JSON: {exc}",
                {"path": str(self.path), "cause": str(exc)},
            ) from exc
        if not isinstance(payload, dict):
            raise ConfigError(
                "config file must contain a JSON object",
                {"path": str(self.path)},
            )
        return self._parse_payload(payload)

    def _parse_payload(self, payload: dict) -> ConfigSnapshot:
        version = payload.get("schema_version", SCHEMA_VERSION)
        if not isinstance(version, int) or version not in KNOWN_VERSIONS:
            raise ConfigSchemaOutdated(
                f"config schema_version {version!r} is not supported (known: {KNOWN_VERSIONS})",
                {"schema_version": version},
            )

        extras = {
            key: value for key, value in payload.items()
            if key not in ("schema_version", "adb_path")
        }

        adb_path = payload.get("adb_path")
        if adb_path is not None:
            if not isinstance(adb_path, str) or not adb_path.strip():
                raise ConfigError(
                    "config field 'adb_path' must be a non-empty string or null",
                    {"field": "adb_path"},
                )
            adb_path = adb_path.strip()
        return ConfigSnapshot(adb_path=adb_path or None, schema_version=version, extras=extras)

    # ------------------------------------------------------------------ #
    # write
    # ------------------------------------------------------------------ #

    def save(self, adb_path: Optional[str], *,
             schema_version: int = SCHEMA_VERSION) -> ConfigSnapshot:
        """Atomically write config (temp file in the same dir + ``os.replace``).

        Preserves previously-present unknown fields (forward compatibility):
        this is a validated read-modify-write that keeps ``extras`` from the
        last valid read; unknown fields never silently vanish from a config
        the engine owns.
        """
        if adb_path is not None and not str(adb_path).strip():
            raise ConfigError("adb_path must be a non-empty string or None",
                              {"field": "adb_path"})
        try:
            current = self.load()
        except ConfigSchemaOutdated:
            current = ConfigSnapshot()
        payload: dict = {key: value for key, value in current.extras.items()}
        payload["adb_path"] = adb_path
        payload["schema_version"] = schema_version
        _write_json_atomic(self.path, payload)
        return self._parse_payload(payload)

    def schema_version(self) -> int:
        return SCHEMA_VERSION

    # ------------------------------------------------------------------ #
    # legacy migration (R-08)
    # ------------------------------------------------------------------ #

    def import_legacy_config(self, legacy_path: Path) -> ConfigSnapshot:
        """First-run migration: import a pre-existing legacy config file.

        Malformed legacy content is NOT imported (import fails with the
        typed error; the target file is left untouched)."""
        legacy_reader = ConfigService(legacy_path)
        snapshot = legacy_reader.load()  # strict legacy parse
        return self.save(snapshot.adb_path)

    def import_repo_legacy_config(self) -> Optional[ConfigSnapshot]:
        """Import ``cli/adb_config.json`` living beside the default engine
        config when present (fresh-clone behavior: no-op when absent)."""
        repo_root = Path(__file__).resolve().parents[2]
        legacy_path = repo_root / "cli" / LEGACY_CONFIG_FILENAME
        if not legacy_path.exists():
            return None
        return self.import_legacy_config(legacy_path)


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    """Write JSON atomically: unique temp file in the same directory, then
    ``os.replace`` (atomic on Windows and POSIX alike). Creates dirs."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
    try:
        data = json.dumps(dict(payload), indent=2, ensure_ascii=False)
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)  # atomic
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
