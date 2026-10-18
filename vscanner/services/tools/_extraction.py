"""Extraction safety primitives (R-11).

Used by the engine's provisioning flow. Behaviors:

* ZIP: member names validated before anything is written — absolute paths,
  drive letters, ``..`` components and backslash-escaped traversal are
  rejected with :class:`ArchiveUnsafeError` (subclass of ``ValueError``).
  ( zipfile itself sanitizes such members today, but PEP 706 history shows
  sanitizers evolve — explicit validation keeps the guarantee local. )
* TAR: traversal members and link entries pointing outside the destination
  are rejected; when the interpreter provides the extraction-filter keyword
  (PEP 706), ``filter='data'`` runs as defense-in-depth on top.
* No member resolves outside the destination: an anchored resolve check
  re-validates every normalized path against the real destination.
* Extraction always happens into a caller-managed staging directory; a
  failed extraction leaves nothing that a later check could mistake for an
  installed tool.

A partially-written archive (interrupted download) never reaches these
functions — provisioning verifies the manifest sha256 first when available.
"""

from __future__ import annotations

import zipfile
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Protocol

import tarfile

__all__ = ["ArchiveUnsafeError", "validate_zip_members", "safe_extract_zip",
           "safe_extract_tar"]


class ArchiveUnsafeError(ValueError):
    """An archive contains a member that would escape the destination."""


def _validate_member_path(member_name: str, base: Path) -> Path:
    """Validate and resolve ``member_name`` relative to ``base``.

    Rejects: absolute paths (POSIX and Windows, including drive letters),
    explicit ``..`` components, and any resolution that leaves ``base``.
    Pure path math — no filesystem writes happen here.
    """
    name_posix = member_name.replace("\\", "/")
    win = PureWindowsPath(member_name)
    if win.is_absolute() or win.drive or ".." in win.parts:
        raise ArchiveUnsafeError(f"unsafe path member rejected: {member_name!r}")

    posix = PurePosixPath(name_posix)
    if posix.is_absolute() or ".." in posix.parts:
        raise ArchiveUnsafeError(f"unsafe path member rejected: {member_name!r}")

    destination = (base / posix).resolve()
    base_resolved = base.resolve()
    if destination != base_resolved and base_resolved not in destination.parents:
        raise ArchiveUnsafeError(f"member escapes destination: {member_name!r}")
    return destination


def validate_zip_members(zf: zipfile.ZipFile, base: Path) -> None:
    """Validate every ZIP member name against the slip rules before writing."""
    for name in zf.namelist():
        _validate_member_path(name, base)


def safe_extract_zip(zip_path: Path, dest: Path) -> None:
    """Extract ``zip_path`` into ``dest`` after member validation.

    Validation of the full member list happens before the first write, so a
    hostile archive cannot partially apply before being rejected.
    """
    dest = Path(dest)
    with zipfile.ZipFile(zip_path, "r") as zf:
        validate_zip_members(zf, dest)
        zf.extractall(dest)


def _validate_tar_members(tar: tarfile.TarFile, base: Path) -> None:
    """Reject traversal members and outside-pointing links."""
    for member in tar.getmembers():
        _validate_member_path(member.name, base)
        link_target = member.linkname
        if not link_target:
            continue
        frags = link_target.replace("\\", "/").split("/")
        if ".." in frags or link_target.startswith("/"):
            raise ArchiveUnsafeError(
                f"link target escapes destination: {member.name!r} -> {link_target!r}"
            )
    # member symlink/hardlink types themselves: validated above through their
    # targets; a device/fifo member cannot be present in the data filter and
    # is stripped by it.


def safe_extract_tar(tar_path: Path, dest: Path) -> None:
    """Extract a ``.tar.gz`` after validating members (R-11)."""
    dest = Path(dest)
    with tarfile.open(tar_path, "r:gz") as tar:
        _validate_tar_members(tar, dest)
        try:
            tar.extractall(dest, filter="data")
        except TypeError:
            # Interpreter without the filter keyword: the explicit member and
            # link validation above carries the guarantee.
            tar.extractall(dest)
