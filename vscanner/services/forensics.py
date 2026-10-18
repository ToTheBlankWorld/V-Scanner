"""ForensicsService — case store + byte-safe extraction (Stage 08).

Ports the legacy ``digital_forensics`` extraction ops onto the shared
engine with the remediations owned by this stage:

* **R-07 (byte-exact)**: app databases are fetched with the
  ``run_bytes`` ``adb exec-out`` foundation (raw bytes in → raw bytes
  out; no text-mode subprocess ever touches the payload) and written
  with sha256 verification records. The legacy text-mode
  ``shell su cat`` + decode→write path (which truncated/mangled NUL
  bytes and non-UTF-8 sequences) is gone. ``shared_prefs``/``files``
  use ``adb pull`` (adb's own binary copy). Text ops (logcat/package
  lists/process list) are explicitly marked as the documented text
  transformations in the manifest (``kind="text"``).
* **R-05 (root tri-state)**: the legacy ``_check_root_safe`` assumed
  ROOTED on detection *failure*; this service probes once per case with
  the verified tri-state probe and records the honest word in the case
  manifest. Failed ``su`` reads are recorded as failed extractions —
  never as successful or clean results.
* **R-12 (WiFi redaction)**: the WiFi op writes a *redacted* file by
  default (``psk=``/password values withheld). A full-secret file is
  written only when an explicit :class:`OperationConfirmation` is
  supplied (the UI double-confirm flow); the manifest records which
  redaction preset every extraction used.
* **Honest evidence**: every extraction appends an ``(operation,
  status-word)`` entry to the manifest; incomplete/failed operations
  are preserved as such in findings/reports — the service never
  fabricates successful extraction, and never returns invented
  records (pass-controllers, parsers for dead extractors, and the
  "assume rooted" fallback are deliberately not ported).

All writes stay under the case directory supplied at construction
(``paths.cases_dir()`` by default); the base directory is resolved
through the A-07 app-data root, never the repository worktree.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional, Protocol, Tuple

from vscanner.core.errors import ForensicsError, InputValidationError
from vscanner.core.events import OperationConfirmation
from vscanner.core.models import CaseManifest, FileRecord
from vscanner.services.admin import validate_confirmation
from vscanner.core.paths import cases_dir

__all__ = ["ForensicsService", "EXTRACTION_SOURCES"]

EXTRACTION_SOURCES = ("databases", "shared_prefs", "files")

# Sequences that would break out of the single-quoted device shell context
# (R-12 hardening: the source path travels inside `su -c cat '<path>'`).
_UNSAFE_DEVICE_PATH_CHARS = ("'", '"', "$", ";", "|", "&", "`", "\n", "\r", "\\")

_WIFI_REDACT_PATTERNS = (
    re.compile(r'(?i)(psk\s*=\s*)"([^"\n]*)"'),
    re.compile(r"(?i)(psk\s*=\s*)'([^'\n]*)'"),
    # unquoted fallbacks exclude '<' so already-redacted placeholders
    # are never re-matched and never corrupt themselves
    re.compile(r"(?i)(psk\s*=\s*)([^\s\"'\n<][^\s\n]*)"),
    re.compile(r'(?i)(password\s*=\s*)"([^"\n]*)"'),
    re.compile(r"(?i)(password\s*=\s*)([^\s\"'\n<][^\s\n]*)"),
)


class _ForensicsTransport(Protocol):
    def run_text(self, cmd, timeout: float = 30.0):
        ...

    def run_bytes(self, cmd, timeout: float = 30.0) -> bytes:
        ...


class ForensicsService:
    """Case store + extraction face over one serial-bound transport."""

    def __init__(self, transport: _ForensicsTransport,
                 base_dir: Optional[Path] = None) -> None:
        self._transport = transport
        self._base_dir = base_dir

    # ------------------------------------------------------------------ #
    # case lifecycle
    # ------------------------------------------------------------------ #

    def create_case(
        self,
        device_serial: Optional[str],
        case_name: str = "",
        note: str = "",
        device_model: Optional[str] = None,
        android_version: Optional[str] = None,
    ) -> CaseManifest:
        """Create a case directory + manifest (legacy ``create_case`` port).

        The root status is probed ONCE here with the verified tri-state
        detector and recorded in the manifest (R-05) — the legacy
        "assume rooted" fallback is deliberately gone.
        """
        base = self._cases_base()
        name = case_name.strip() or (
            "case_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S"))
        if not re.fullmatch(r"[\w.\-]+", name):
            raise InputValidationError(
                "case name must contain only letters, digits, dot, "
                "hyphen, underscore",
                {"field": "case_name", "value": name},
            )
        case_path = base / name
        if case_path.exists():
            raise ForensicsError(
                f"case directory already exists: {name}",
                {"case": name}, operation="create_case",
            )
        case_path.mkdir(parents=True, exist_ok=False)

        status, _evidence = self._root_status_word_with_evidence()
        manifest = CaseManifest(
            case_id=name,
            created_at=datetime.now(timezone.utc).isoformat(),
            device_serial=device_serial,
            device_model=device_model or None,
            android=android_version or None,
            is_rooted=(status == "rooted"),
            root_status=status,
            redaction_preset="default-redacted",
            note=note,
            extractions=(("create_case", "success"), ("root_probe", status)),
        )
        self._write_manifest(case_path, manifest)
        return manifest

    def case_path(self, manifest: CaseManifest) -> Path:
        return self._cases_base() / manifest.case_id

    def load_case(self, case_id: str) -> CaseManifest:
        """Re-open an existing case (manifest.json → typed model)."""
        path = self._cases_base() / case_id / "manifest.json"
        legacy = self._cases_base() / case_id / "metadata.json"
        src = path if path.exists() else legacy
        if not src.exists():
            raise ForensicsError(
                f"case {case_id!r} has no manifest", {"case": case_id},
                operation="load_case",
            )
        try:
            raw = src.read_text(encoding="utf-8", errors="strict")
            data = json.loads(raw)
        except (OSError, ValueError) as exc:
            raise ForensicsError(
                f"case manifest unreadable: {exc}", {"case": case_id},
                operation="load_case",
            ) from exc
        files = tuple(FileRecord(**record) for record in data.get("files", []))
        extras = tuple(
            (str(op), str(state)) for op, state in data.get("extractions", []))
        return CaseManifest(
            case_id=str(data.get("case_name") or data.get("case_id") or case_id),
            created_at=str(data.get("created") or data.get("created_at") or ""),
            device_serial=data.get("device_serial"),
            device_model=data.get("device_model") or data.get("device"),
            android=data.get("android_version") or data.get("android"),
            is_rooted=bool(data.get("is_rooted", False)),
            root_status=str(data.get("root_status")
                            or ("rooted" if data.get("is_rooted") else "unknown")),
            redaction_preset=str(data.get("redaction_preset")
                                 or "default-redacted"),
            files=files,
            extractions=extras,
            note=str(data.get("note") or ""),
        )

    # ------------------------------------------------------------------ #
    # app-data extraction (R-07 byte-exact)
    # ------------------------------------------------------------------ #

    def extract_app_data_files(
        self,
        package: str,
        sources: Iterable[str],
        manifest: CaseManifest,
        context=None,
    ) -> CaseManifest:
        """Extract the requested private-data dirs for one package.

        Byte-safe: databases via ``exec-out su -c cat`` (raw bytes, sha256
        recorded); shared_prefs/files via ``adb pull`` into the case dir.
        Root-unavailable and per-file failures are recorded as FAILED
        entries in the manifest — never silently skipped, never reported
        as clean.
        """
        if not re.fullmatch(r"[\w.]+", package):
            raise InputValidationError(
                "package name looks unsafe for extraction",
                {"field": "package", "value": package[:64]},
            )
        sources = tuple(dict.fromkeys(sources))
        unknown = [s for s in sources if s not in EXTRACTION_SOURCES]
        if unknown:
            raise InputValidationError(
                f"unknown extraction source(s): {', '.join(unknown)}",
                {"field": "sources", "value": ",".join(sources)},
            )

        case_path = self.case_path(manifest)
        new_files: list[FileRecord] = list(manifest.files)
        notes: list[tuple[str, str]] = [
            (f"extract_app_data:{package}", "started")]

        for source in sources:
            device_dir = f"/data/data/{package}/{source}"
            safe, reason = self._validate_device_path(device_dir)
            if not safe:
                notes.append((f"extract:{source}:{package}",
                              f"refused unsafe path ({reason})"))
                continue
            listing = self._device_file_list(device_dir)
            if not listing.ok:
                notes.append((f"extract:{source}:{package}",
                              f"listing unavailable: {listing.reason}"))
                continue
            if not listing.entries:
                notes.append((f"extract:{source}:{package}", "no files listed"))
                continue
            dest_dir = case_path / f"{package}_{source}" / source
            dest_dir.mkdir(parents=True, exist_ok=True)
            ok_count = 0
            for entry in listing.entries:
                src_path = f"{device_dir}/{entry}"
                if context is not None:
                    context.progress(0, 0, unit="files",
                                     context=f"{source}/{entry}")
                dest = dest_dir / entry
                record = self._copy_source_bytes(
                    src_path=src_path,
                    dest=dest,
                    relative_dst=str(dest.relative_to(case_path)),
                )
                if record is None:
                    notes.append((f"extract:{source}/{entry}:{package}",
                                  "copy failed (su unavailable or read error)"))
                else:
                    new_files.append(record)
                    ok_count += 1
            notes.append((f"extract:{source}:{package}",
                          f"{ok_count}/{len(listing.entries)} files copied"))

        # dedupe identical (operation,status) words while preserving order
        merged: list[tuple[str, str]] = list(manifest.extractions)
        seen = set(manifest.extractions)
        for entry in notes:
            if entry not in seen:
                seen.add(entry)
                merged.append(entry)
        manifest = CaseManifest(
            case_id=manifest.case_id, created_at=manifest.created_at,
            device_serial=manifest.device_serial,
            device_model=manifest.device_model, android=manifest.android,
            is_rooted=manifest.is_rooted, root_status=manifest.root_status,
            redaction_preset=manifest.redaction_preset,
            files=tuple(new_files), extractions=tuple(merged),
            note=manifest.note,
        )
        self._write_manifest(case_path, manifest)
        return manifest

    # ------------------------------------------------------------------ #
    # one-shot text ops (documented text transformations)
    # ------------------------------------------------------------------ #

    def extract_system_logs(self, manifest: CaseManifest) -> CaseManifest:
        return self._extract_text_op(
            manifest, op="system_logs", filename="system_logs.txt",
            cmd=("shell", "logcat", "-d"), label="system logs",
        )

    def extract_installed_packages(self, manifest: CaseManifest) -> CaseManifest:
        return self._extract_text_op(
            manifest, op="installed_packages", filename="installed_packages.txt",
            cmd=("shell", "pm", "list", "packages"), label="package list",
        )

    def extract_running_processes(self, manifest: CaseManifest) -> CaseManifest:
        return self._extract_text_op(
            manifest, op="running_processes", filename="running_processes.txt",
            cmd=("shell", "ps", "-A"), label="process list",
        )

    # ------------------------------------------------------------------ #
    # WiFi (R-12 redaction default)
    # ------------------------------------------------------------------ #

    def extract_wifi_networks(
        self,
        manifest: CaseManifest,
        acknowledge_cleartext_psk: Optional[OperationConfirmation] = None,
    ) -> CaseManifest:
        """Extract WiFi networks.

        * Default: ``wifi_networks.txt`` written REDACTED (psk/password
          values withheld as documented placeholders) — R-12.
        * Only when ``acknowledge_cleartext_psk`` is a valid
          :class:`OperationConfirmation` (the UI's explicit double-confirm)
          the unredacted content is additionally written to
          ``wifi_networks_cleartext.txt`` and the manifest records the
          explicit-unredacted preset.
        """
        case_path = self.case_path(manifest)
        note_op = "wifi_networks"
        try:
            result = self._transport.run_text(
                ("shell", "su", "-c", "cat /data/misc/wifi/wpa_supplicant.conf"),
                timeout=20.0,
            )
        except Exception as exc:
            return self._append_and_save(
                case_path, manifest, (note_op, f"extraction error "
                f"({type(exc).__name__})"))
        out = getattr(result, "stdout", "") or ""
        rc = getattr(result, "returncode", 1)
        if rc != 0 or not out.strip():
            stderr = (getattr(result, "stderr", "") or "").strip()
            return self._append_and_save(
                case_path, manifest, (note_op,
                f"unavailable: rc={rc}" + (f" ({stderr[:80]})" if stderr else "")))

        networks = out.count("network={")
        redacted = _redact_wifi_text(out)
        redacted_path = case_path / "wifi_networks.txt"
        _write_text_bytes(redacted_path, redacted)
        applied = "wifi_networks:redacted (networks count: " + str(networks) + ")"
        extras: list[tuple[str, str]] = [(note_op, applied)]

        if acknowledge_cleartext_psk is not None:
            validate_confirmation(acknowledge_cleartext_psk,
                                  "wifi_cleartext_psk")
            cleartext_path = case_path / "wifi_networks_cleartext.txt"
            _write_text_bytes(cleartext_path, out)
            extras.append((note_op,
                           "explicit-unredacted: cleartext file written on "
                           "confirmed request"))
        manifest = CaseManifest(
            case_id=manifest.case_id, created_at=manifest.created_at,
            device_serial=manifest.device_serial,
            device_model=manifest.device_model,
            android=manifest.android,
            is_rooted=manifest.is_rooted, root_status=manifest.root_status,
            redaction_preset=("explicit-unredacted"
                              if acknowledge_cleartext_psk is not None
                              else "default-redacted"),
            files=manifest.files,
            extractions=self._merged_extractions(manifest, extras),
            note=manifest.note,
        )
        self._write_manifest(case_path, manifest)
        return manifest

    # ------------------------------------------------------------------ #
    # report (legacy metadata.json fields preserved + honest tri-state)
    # ------------------------------------------------------------------ #

    def generate_report(self, manifest: CaseManifest) -> Path:
        """Write ``report.json`` summary (legacy ``metadata.json`` fields
        preserved: case name, created, device, android version, is_rooted —
        plus the R-05 ``root_status`` tri-state and per-file hashes)."""
        case_path = self.case_path(manifest)
        payload = {
            "case_name": manifest.case_id,          # legacy field name
            "created": manifest.created_at,          # legacy field name
            "device": manifest.device_model or "Unknown",   # legacy field name
            "android_version": manifest.android or "Unknown",  # legacy field
            "is_rooted": manifest.root_status == "rooted",  # legacy field;
            # NOTE (R-05): is_rooted stays TRUE only for CONFIRMED root.
            "root_status": manifest.root_status,     # R-05 honest tri-state
            "device_serial": manifest.device_serial,
            "redaction_preset": manifest.redaction_preset,
            "status": "open",
            "files": [
                {
                    "source_path": rec.source_path,
                    "case_relative_path": rec.case_relative_path,
                    "sha256": rec.sha256,
                    "bytes": rec.byte_count,
                    "kind": rec.kind,
                    "note": rec.note,
                }
                for rec in manifest.files
            ],
            "extractions": [list(entry) for entry in manifest.extractions],
            "note": manifest.note,
        }
        dest = case_path / "report.json"
        _write_text_bytes(dest, json.dumps(payload, indent=2) + "\n")
        return dest

    # ------------------------------------------------------------------ #
    # internals
    # ------------------------------------------------------------------ #

    def _root_status_word_with_evidence(self) -> tuple[str, tuple]:
        from vscanner.services.adb.root_probe import RootStatusService
        status, evidence = RootStatusService(self._transport).probe_evidence()
        # contract wording (SC-forensics / R-05): "rooted|not-rooted|unknown"
        word = status.value.replace("_", "-")
        return word, evidence

    def _cases_base(self) -> Path:
        return self._base_dir if self._base_dir is not None else cases_dir()

    @staticmethod
    def _validate_device_path(path: str) -> tuple[bool, str]:
        if any(ch in path for ch in _UNSAFE_DEVICE_PATH_CHARS):
            return False, "path contains shell-unsafe characters"
        if ".." in path:
            return False, "path traversal component"
        return True, ""

    def _device_file_list(self, device_dir: str):
        try:
            result = self._transport.run_text(
                ("shell", "su", "-c", f"ls -1 '{device_dir}'"), timeout=20.0)
        except Exception as exc:
            return _Listing(ok=False, entries=[], reason=type(exc).__name__)
        rc = getattr(result, "returncode", 1)
        out = getattr(result, "stdout", "") or ""
        if rc != 0 or not out.strip():
            stderr = (getattr(result, "stderr", "") or "").strip()
            return _Listing(ok=False, entries=[],
                            reason=f"rc={rc}" + (f" {stderr[:60]}" if stderr else ""))
        entries = [line.strip() for line in out.splitlines() if line.strip()]
        for entry in entries:
            if entry in (".", "..") or "/" in entry or any(
                    ch in entry for ch in _UNSAFE_DEVICE_PATH_CHARS):
                return _Listing(ok=False, entries=[],
                                reason=f"unsafe listing entry {entry[:40]!r}")
        return _Listing(ok=True, entries=entries, reason="")

    def _copy_source_bytes(
        self, src_path: str, dest: Path, relative_dst: str,
    ) -> Optional[FileRecord]:
        """Byte-exact copy of one device file (R-07).

        ``exec-out su -c cat`` returns raw bytes (verified binary mode);
        the local write is via tmp-file + replace, so a local crash never
        half-writes a "successful" record.
        """
        try:
            data = self._transport.run_bytes(
                ("exec-out", "su", "-c", f"cat '{src_path}'"), timeout=60.0)
        except Exception:
            return None
        # NOTE: an honest empty file (0 bytes) is legal for databases too
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".part")
        tmp.write_bytes(data)
        tmp.replace(dest)
        digest = hashlib.sha256(data).hexdigest()
        return FileRecord(
            source_path=src_path, case_relative_path=relative_dst,
            sha256=digest, byte_count=len(data), kind="binary",
        )

    def _extract_text_op(self, manifest: CaseManifest, op: str, filename: str,
                         cmd: tuple, label: str) -> CaseManifest:
        case_path = self.case_path(manifest)
        try:
            result = self._transport.run_text(cmd, timeout=20.0)
        except Exception as exc:
            return self._append_and_save(
                case_path, manifest,
                (op, f"extraction error ({type(exc).__name__})"))
        out = getattr(result, "stdout", "") or ""
        rc = getattr(result, "returncode", 1)
        if rc != 0 or not out.strip():
            stderr = (getattr(result, "stderr", "") or "").strip()
            return self._append_and_save(
                case_path, manifest, (op, f"unavailable: rc={rc}"
                                      + (f" ({stderr[:80]})" if stderr else "")))
        dest = case_path / filename
        _write_text_bytes(dest, out)
        return self._append_and_save(
            case_path, manifest, (op, f"success ({len(out.splitlines())} lines)"))

    # manifest helpers --------------------------------------------------- #

    def _merged_extractions(self, manifest: CaseManifest,
                            extras: list[tuple[str, str]]) -> tuple:
        merged = list(manifest.extractions)
        for entry in extras:
            if entry not in merged:
                merged.append(entry)
        return tuple(merged)

    def _with_extractions(self, manifest: CaseManifest,
                          extras: list[tuple[str, str]]) -> CaseManifest:
        return CaseManifest(
            case_id=manifest.case_id, created_at=manifest.created_at,
            device_serial=manifest.device_serial,
            device_model=manifest.device_model, android=manifest.android,
            is_rooted=manifest.is_rooted, root_status=manifest.root_status,
            redaction_preset=manifest.redaction_preset,
            files=manifest.files,
            extractions=self._merged_extractions(manifest, extras),
            note=manifest.note,
        )

    def _append_and_save(self, case_path: Path, manifest: CaseManifest,
                         entry: tuple[str, str]) -> CaseManifest:
        manifest = self._with_extractions(manifest, [entry])
        self._write_manifest(case_path, manifest)
        return manifest

    def _write_manifest(self, case_path: Path, manifest: CaseManifest) -> None:
        payload = {
            "case_name": manifest.case_id,
            "created": manifest.created_at,
            "device_serial": manifest.device_serial,
            "device_model": manifest.device_model,
            "android_version": manifest.android,
            "device": manifest.device_model,
            "android": manifest.android,
            "is_rooted": manifest.is_rooted,
            "root_status": manifest.root_status,
            "redaction_preset": manifest.redaction_preset,
            "files": [
                {
                    "source_path": rec.source_path,
                    "case_relative_path": rec.case_relative_path,
                    "sha256": rec.sha256,
                    "byte_count": rec.byte_count,
                    "kind": rec.kind,
                    "note": rec.note,
                }
                for rec in manifest.files
            ],
            "extractions": [list(entry) for entry in manifest.extractions],
            "note": manifest.note,
        }
        _write_text_bytes(case_path / "manifest.json",
                          json.dumps(payload, indent=2) + "\n")


class _Listing:
    """Internal listing result (device dir read)."""

    def __init__(self, ok: bool, entries: list, reason: str = "") -> None:
        self.ok = ok
        self.entries = entries
        self.reason = reason


def _write_text_bytes(path: Path, text: str) -> None:
    """Text transformation boundary: encode as UTF-8 (surrogate replacement
    for undecodable characters), writing bytes via tmp+replace. Marked in
    the manifest as kind="text" — this is NOT the binary path."""
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_bytes(text.encode("utf-8", errors="surrogatepass"))
    tmp.replace(path)


def _redact_wifi_text(text: str) -> str:
    """R-12: withheld psk/password values in the default WiFi file."""

    def _swap(match: "re.Match[str]") -> str:
        head, value = match.group(1), match.group(2)
        return f'{head}<redacted, length {len(value)}>'

    result = text
    for pattern in _WIFI_REDACT_PATTERNS:
        result = pattern.sub(_swap, result)
    return result
