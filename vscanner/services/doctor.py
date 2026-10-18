"""Doctor (SC-11): read-only environment report — NO side-effect installs.

Replaces the legacy ``cli/dependency_checker.py`` auto-pip behavior per
R-14: this service only *reports* — it never downloads, never pip-installs,
never touches the network beyond library import probing (which does no
network access; ``importlib.util.find_spec`` is file-system metadata).
"""

from __future__ import annotations

import importlib.util
import platform
import sys
from dataclasses import dataclass, field
from typing import Optional, Protocol, Tuple

from vscanner.core.models import ToolId, ToolState, ToolStatusReflected

__all__ = ["PackageStatus", "DependencyReport", "collect_dependency_report",
           "check_tool_status"]

# The three proven runtime dependencies (grep-verified in Stage 00; the six
# over-declared entries were removed from the dependency table this stage).
RUNTIME_PACKAGES = ("rich", "click", "jinja2")

_OWNED_TOOLS = (ToolId.ADB,)


@dataclass(frozen=True, slots=True)
class PackageStatus:
    name: str
    installed: bool


@dataclass(frozen=True, slots=True)
class DependencyReport:
    python_version: str
    packages: Tuple[PackageStatus, ...] = ()
    tools: Tuple[ToolStatusReflected, ...] = ()
    notes: Tuple[str, ...] = field(default_factory=tuple)

    @property
    def all_packages_present(self) -> bool:
        return all(p.installed for p in self.packages)

    def missing_packages(self) -> tuple:
        return tuple(p.name for p in self.packages if not p.installed)


def _package_installed(name: str) -> bool:
    """Import-probe without importing side effects (spec lookup only)."""
    try:
        return importlib.util.find_spec(name) is not None
    except Exception:
        return False  # broken namespace packages: report honestly as absent


class _ToolStatusService(Protocol):
    """Shape of the provisioning service the doctor reflects statuses from."""

    def tool_status(self, tool: ToolId) -> ToolStatusReflected:
        ...


_RUN_PACKAGES_NOTE = "doctor is report-only: installs happen only by explicit user action"


def check_tool_status(tool, service) -> ToolStatusReflected:
    """Reflect a tool's status through its provisioning service (read-only)."""
    try:
        return service.tool_status(tool)
    except Exception as exc:  # tool probing must never crash the doctor
        return ToolStatusReflected(
            tool=tool, state=ToolState.NOT_FOUND, notes=(f"probe failed: {exc}",)
        )


def collect_dependency_report(
    tools_service: Optional[_ToolStatusService] = None,
    extra_notes: Tuple[str, ...] = (),
) -> DependencyReport:
    """Build the doctor's data report.

    ``tools_service`` is an optional :class:`ToolProvisioningService` — the
    doctor stays constructible even when provisioning was never configured
    (an adb probe then shows the honest NOT_FOUND state).
    """
    packages = tuple(
        PackageStatus(name=name, installed=_package_installed(name))
        for name in RUNTIME_PACKAGES
    )
    tools: Tuple[ToolStatusReflected, ...] = ()
    if tools_service is not None:
        tools = tuple(check_tool_status(t, tools_service) for t in _OWNED_TOOLS)

    notes = list(extra_notes)
    notes.append("doctor is report-only: installs happen only by explicit user action")
    return DependencyReport(
        python_version=f"{platform.python_implementation()} {sys.version.splitlines()[0].strip()}",
        packages=packages,
        tools=tools,
        notes=tuple(notes),
    )
