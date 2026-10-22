"""Release-readiness: requirements-lock.txt fidelity checks (Stage 16+).

The lock file pins the exact dependency closure of the environment that
produced the verified ``3.0.0a0`` Windows artifacts.  These tests assert:

1. every non-comment lock row is a strict ``name==version`` pin;
2. every runtime/desktop dependency declared in ``pyproject.toml`` is
   present in the lock (nothing missing);
3. the lock's pinned set is exactly the transitive runtime closure of the
   declared direct dependencies as resolved from the executing
   environment's installed metadata (no stale rows, no extras);
4. the installed version of every pinned package equals the pin
   (drift detector: a failing run means the environment changed since the
   artifacts were produced and the recorded reproducibility numbers are
   stale until re-evaluated).

Environment markers referencing other Python versions are ignored the same
way the lock generator does (this suite targets the interpreter that runs
it, which is the environment whose versions the artifacts recorded).
"""

from __future__ import annotations

import importlib.metadata as md
import re
from pathlib import Path

import pytest

LOCK_PATH = Path(__file__).resolve().parents[2] / "requirements-lock.txt"
PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"

_REQ_LINE = re.compile(r"^([A-Za-z][A-Za-z0-9._-]*)==([A-Za-z0-9][A-Za-z0-9._+]*)$")


def _lock_pins() -> dict[str, str]:
    pins: dict[str, str] = {}
    for raw in LOCK_PATH.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = _REQ_LINE.match(line)
        assert match is not None, f"lock row is not a strict pin: {line!r}"
        pins[match.group(1).lower()] = match.group(2)
    assert pins, "requirements-lock.txt must contain at least one pin"
    return pins


def _declared_direct() -> "list[str]":
    text = PYPROJECT.read_text(encoding="utf-8")
    names: "list[str]" = []
    for header in ("dependencies", "desktop"):
        block = re.search(
            rf"{header} = \[(.*?)\]", text, re.S
        )
        assert block is not None, f"pyproject.toml section {header!r} missing"
        for line in block.group(1).splitlines():
            line = line.split("#")[0].strip().strip(",").strip('"').strip()
            if line:
                names.append(re.split(r"[<>=!~;\[ ]+", line)[0].strip())
    return names


def _installed_closure() -> dict[str, str]:
    closure: dict[str, str] = {}
    todo = [
        re.split(r"[<>=!~;\[ ]+", dep)[0].strip()
        for dep in _declared_direct()
    ]
    while todo:
        name = todo.pop()
        key = name.lower().replace("_", "-")
        if key in closure:
            continue
        dist = md.distribution(name)
        closure[key] = dist.version
        for req in dist.requires or []:
            marker = req.split(";", 1)[1].strip() if ";" in req else ""
            if "extra" in marker:
                continue
            if 'python_version < "3.11"' in marker:
                continue
            todo.append(re.split(r"[<>=!~;\[ ]+", req)[0].strip())
    return closure


def test_every_lock_row_is_a_strict_exact_pin() -> None:
    _lock_pins()


def test_every_declared_direct_dependency_is_locked() -> None:
    pins = _lock_pins()
    for direct in _declared_direct():
        key = direct.lower().replace("_", "-")
        assert key in pins, f"declared dependency {direct!r} missing from lock"


def test_lock_matches_the_installed_runtime_closure() -> None:
    pins = _lock_pins()
    closure = _installed_closure()
    assert set(pins) == set(closure), (
        "requirements-lock.txt is out of sync with the installed runtime "
        f"closure; lock-only={sorted(set(pins) - set(closure))}, "
        f"closure-only={sorted(set(closure) - set(pins))}"
    )


@pytest.mark.parametrize("record", sorted(
    (name, version) for name, version in _lock_pins().items()
))
def test_installed_version_matches_pin(record: "tuple[str, str]") -> None:
    name, version = record
    installed = md.distribution(name).version
    assert installed == version, (
        f"{name} installed {installed} != pinned {version}: the environment "
        "drifted from the artifact-producing one; regenerate the lock and "
        "re-validate the artifacts before quoting reproducibility"
    )
