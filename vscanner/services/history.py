"""T-08 scan history store (Stage 07).

Durable local scan history as plain JSON files — one file per finished
scan — per ARCHITECTURE_DECISIONS T-08/A-07:

* location: ``history_dir()`` (``%LOCALAPPDATA%\\vscanner\\history``;
  the dev-repo override keeps it under the repo; tests inject ``tmp_path``);
* capped retention: the newest ``CAP`` records survive, older ones are
  pruned on append (nothing silently regrows forever);
* every record embeds ``schema_version`` and the epoch id ``created_by``
  (DATA_MODELS §10) and tolerates unknown fields on read;
* **no secret material**: records carry only counters, state words,
  timestamps and target identifiers that the UI already displays — no
  findings text, no evidence excerpts, no device payload (the finding
  corpus itself lives only in the in-memory scan bundle / exported reports);
* reads are tolerant: corrupt/foreign files are skipped loudly in a
  counter sense (redacted reason), never crash the UI.

The store is synchronous and cheap (small JSON files); callers that need
non-blocking behavior (the TUI) run appends/reads on worker threads.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Union

from vscanner.core.errors import VScannerError

__all__ = ["HistoryEntry", "ScanHistoryStore", "HistoryStoreError"]

HISTORY_SCHEMA_VERSION = 1
HISTORY_CREATED_BY = "vscanner/3.0"
CAP = 30
"""T-08 retention cap (plain-JSON regime; SQLite would need justification)."""

_SEVERITY_KEYS = ("critical", "high", "medium", "low", "info")


class HistoryStoreError(VScannerError):
    """Typed failure for unwritable/undecodable history locations."""


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True, slots=True)
class HistoryEntry:
    """One finished-scan summary; intentionally secrets-free (T-08)."""

    scan_id: str
    """The engine-generated ScanRequest id (stable cross-reference)."""
    kind: str
    """``full_device`` or ``single_app`` (ScanKind values)."""
    status: str
    """Honest terminal word: ``completed`` | ``cancelled`` | ``failed``."""
    device_serial: Optional[str] = None
    finished_at_utc: str = field(default_factory=_utcnow_iso)
    total_apps: int = 0
    findings_total: int = 0
    severity_counts: Optional[dict] = None
    """Mapping severity word → count, always all five keys (0 padded)."""
    schema_version: int = HISTORY_SCHEMA_VERSION
    created_by: str = HISTORY_CREATED_BY

    def severity_counts_complete(self) -> dict:
        counts = dict(self.severity_counts or {})
        return {key: int(counts.get(key, 0)) for key in _SEVERITY_KEYS}


class ScanHistoryStore:
    """Append/read face over one JSON file per scan (T-08)."""

    def __init__(self, directory: Union[str, Path]) -> None:
        self._dir = Path(directory)

    # -- write face ---------------------------------------------------------- #

    def append(self, entry: HistoryEntry) -> Path:
        """Write one record and prune beyond :data:`CAP`.

        File name ``<UTC stamp>-<scan id prefix>.json`` — sortable and
        collision-resistant. Returns the written path; raises
        :class:`HistoryStoreError` only when the location itself is not
        writable (the TUI surfaces that honestly instead of pretending)."""
        try:
            from vscanner.core.paths import ensure_dir

            ensure_dir(self._dir)
            stamp = (entry.finished_at_utc or _utcnow_iso()).replace(":", "")
            path = self._dir / f"{stamp}-{entry.scan_id[:8]}.json"
            payload = asdict(entry)
            path.write_text(
                json.dumps(payload, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        except OSError as exc:
            raise HistoryStoreError(
                "scan history could not be written; the scan outcome is "
                "still applied in the UI",
                {"directory": str(self._dir), "cause": str(exc)},
            ) from exc
        self._prune()
        return path

    def _prune(self) -> None:
        try:
            files = sorted(p for p in self._dir.glob("*.json"))
            excess = len(files) - CAP
            for path in files[:max(0, excess)]:
                path.unlink(missing_ok=True)
        except OSError:
            pass  # pruning is best-effort; the append itself already succeeded

    # -- read face ----------------------------------------------------------- #

    def recent(self, limit: int = CAP) -> tuple:
        """Newest-first tolerant read; unknown fields are ignored,
        corrupt files counted as unreadable (never crash the caller)."""
        try:
            files = sorted(self._dir.glob("*.json"), reverse=True)
        except OSError:
            return ()
        entries: list = []
        unreadable = 0
        for path in files:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                unreadable += 1
                continue
            if not isinstance(data, dict) or not data.get("scan_id"):
                unreadable += 1
                continue
            counts = data.get("severity_counts")
            entries.append(HistoryEntry(
                scan_id=str(data["scan_id"]),
                kind=str(data.get("kind", "unknown")),
                status=str(data.get("status", "unknown")),
                device_serial=data.get("device_serial"),
                finished_at_utc=str(data.get("finished_at_utc", "")),
                total_apps=int(data.get("total_apps", 0) or 0),
                findings_total=int(data.get("findings_total", 0) or 0),
                severity_counts=counts if isinstance(counts, dict) else None,
                schema_version=int(data.get("schema_version", 1) or 1),
                created_by=str(data.get("created_by", "unknown")),
            ))
            if len(entries) >= limit:
                break
        self.last_unreadable = unreadable
        return tuple(entries[:limit])

    def clear(self) -> int:
        """Remove every history file; returns how many were deleted."""
        try:
            files = list(self._dir.glob("*.json"))
        except OSError:
            return 0
        removed = 0
        for path in files:
            try:
                path.unlink(missing_ok=True)
                removed += 1
            except OSError:
                pass
        return removed
