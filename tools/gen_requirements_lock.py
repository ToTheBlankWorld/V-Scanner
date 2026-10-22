"""One-shot generator for requirements-lock.txt (release readiness phase).

Reads the direct dependencies from pyproject.toml (runtime + desktop extra),
resolves the full transitive closure from the currently installed environment
(the one that produced the verified release artifacts), and writes exact pins.

Run manually; not part of the shipped package.
"""
from __future__ import annotations

import importlib.metadata as md
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
pyproject = (REPO / "pyproject.toml").read_text(encoding="utf-8")
dep = re.search(r"dependencies = \[(.*?)\]", pyproject, re.S).group(1)
desk = re.search(r"desktop = \[(.*?)\]", pyproject, re.S).group(1)
direct: list[str] = []
for block in (dep, desk):
    for line in block.splitlines():
        line = line.split("#")[0].strip().strip(",")
        if line:
            direct.append(line.strip().strip('"').strip())
print("direct deps declared:", direct)


def resolve(seed: "list[str]") -> "dict[str, str]":
    out: "dict[str, str]" = {}
    todo = [re.split(r"[<>=!~;\[ ]+", d)[0].strip() for d in seed]
    while todo:
        name = todo.pop()
        key = name.lower().replace("_", "-")
        if key in out:
            continue
        dist = md.distribution(name)
        out[key] = dist.version
        for req in dist.requires or []:
            marker = req.split(";", 1)[1].strip() if ";" in req else ""
            if "extra" in marker:
                continue
            if "python_version < \"3.11\"" in marker:
                continue  # this environment is 3.12; the dep does not apply
            base = re.split(r"[<>=!~;\[ ]+", req)[0].strip()
            if base:
                todo.append(base)
    return out


closure = resolve(direct)
lines = [
    "# requirements-lock.txt : runtime dependency closure for V-Scanner 3.0.0a0",
    "# Generated from the environment that produced the verified release artifacts",
    "# (Windows 11 x64 host, Python 3.12.10; see RELEASE_READINESS_REPORT.md).",
    "# Exact pins; tests/unit/test_requirements_lock.py reports drift.",
    "",
]
for key in sorted(closure):
    lines.append(f"{key}=={closure[key]}")
(REPO / "requirements-lock.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
print("lock rows:", len(closure))
for key in sorted(closure):
    print(" ", key, closure[key])
