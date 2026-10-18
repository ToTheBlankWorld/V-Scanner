"""R-05 root-status probe — verified tri-state semantics (Stage 08).

Legacy root "detection" mapped detection *failure* to a definite answer
(``is_rooted = False`` propagated everywhere, and case metadata recorded a
definitive ``is_rooted: false`` even when every probe errored). The R-05
contract forbids both directions:

* a failed detection operation must NOT imply the device is rooted;
* a failed detection operation must NOT imply it is definitely not rooted;
* exceptions, timeouts, missing executables, and malformed responses must
  surface as the honest tri-state UNKNOWN, never as a confirmed status.

This probe produces:

* ``ROOTED`` only from a *verified* positive: ``su -c id`` succeeds with
  ``uid=0`` in its output (real command output — the evidence is kept);
* ``NOT_ROOTED`` only when the detector positively supports the negative:
  ``command -v su`` finds nothing AND no known root-manager package is
  installed (documented caveat: this proves root is unavailable to the
  ADB-shell context, not spiritual certainty about the device);
* ``UNKNOWN`` for everything else — exceptions, timeouts, an ``su`` binary
  present but denied from the ADB context (e.g. Magisk denylist), or
  malformed output.

``probe_evidence()`` returns the tri-state with the raw probe evidence so
UIs and reports can *show why* — R-05 honesty is audit-visible.
"""

from __future__ import annotations

from typing import Protocol, Tuple

from vscanner.core.models import RootStatus

__all__ = ["RootStatusService", "ROOT_MANAGER_PACKAGES"]

ROOT_MANAGER_PACKAGES = (
    "com.topjohnwu.magisk",
    "me.bmax.kernelsu",
    "eu.chainfire.supersu",
    "com.koushikdutta.superuser",
    "com.noshufou.android.su",
    "com.thirdparty.superuser",
    "com.yellowroot.superuser.yellowsu",
    "com.kingouser.com",
)
_PROBE_TIMEOUT = 6.0


class _RootTransport(Protocol):
    def run_text(self, cmd, timeout: float = 30.0):
        """CompletedProcess-shaped text execution (stdout/returncode/opts)."""
        ...


class _ShellLike:  # pragma: no cover - protocol helper typing only
    stdout: str
    stderr: str
    returncode: int


class RootStatusService:
    """Verified root-status detector over one serial-bound transport."""

    def __init__(self, transport: _RootTransport) -> None:
        self._transport = transport

    def probe(self) -> RootStatus:
        status, _evidence = self.probe_evidence()
        return status

    def probe_evidence(self) -> Tuple[RootStatus, Tuple[str, ...]]:
        """Run the verified probe; return (status, evidence lines).

        Evidence lines are short, single-line, and safe for rendering —
        they are the *why* behind the tri-state answer.
        """
        evidence: list[str] = []

        # Step 1: verified positive probe.
        try:
            result = self._transport.run_text(
                ["shell", "su", "-c", "id"], timeout=_PROBE_TIMEOUT)
        except Exception as exc:
            evidence.append(f"su probe failed ({type(exc).__name__}) → unknown")
            return RootStatus.UNKNOWN, tuple(evidence)
        stdout = (result.stdout or "").strip()
        rc = result.returncode
        evidence.append(f"su -c id → rc={rc}, out={stdout[:64]!r}")
        if rc == 0:
            if "uid=0" in stdout:
                evidence.append("verified: uid=0 from su execution")
                return RootStatus.ROOTED, tuple(evidence)
            evidence.append("su rc=0 but no uid=0 in output → malformed → unknown")
            return RootStatus.UNKNOWN, tuple(evidence)

        # Step 2: is a su binary visible from ADB shell at all?
        try:
            vis = self._transport.run_text(
                ["shell", "command", "-v", "su"], timeout=_PROBE_TIMEOUT)
        except Exception as exc:
            evidence.append(f"su-visibility probe failed ({type(exc).__name__}) → unknown")
            return RootStatus.UNKNOWN, tuple(evidence)
        vis_out = (vis.stdout or "").strip()
        evidence.append(f"command -v su → rc={vis.returncode}, out={vis_out[:64]!r}")
        if vis.returncode == 0 and vis_out:
            evidence.append(
                "su binary present but ADB-side execution refused → unknown "
                "(denylist managers can hide root; not confirmed either way)")
            return RootStatus.UNKNOWN, tuple(evidence)

        # Step 3: positive not-rooted requires the manager absence check.
        try:
            pkgs = self._transport.run_text(
                ["shell", "pm", "list", "packages"], timeout=_PROBE_TIMEOUT)
        except Exception as exc:
            evidence.append(f"package probe failed ({type(exc).__name__}) → unknown")
            return RootStatus.UNKNOWN, tuple(evidence)
        pkg_output = (pkgs.stdout or "")
        pkg_rc = pkgs.returncode
        if pkg_rc == 0:
            managers = [name for name in ROOT_MANAGER_PACKAGES
                        if f"package:{name}" in pkg_output]
            if managers:
                evidence.append(
                    f"root manager package present ({managers[0]}) but su "
                    f"denied from ADB → unknown")
                return RootStatus.UNKNOWN, tuple(evidence)
            evidence.append(
                "su unavailable to ADB shell and no root manager package "
                "installed → not-rooted (for the ADB-shell context)")
            return RootStatus.NOT_ROOTED, tuple(evidence)
        evidence.append(f"package probe rc={pkg_rc} → can't confirm absence → unknown")
        return RootStatus.UNKNOWN, tuple(evidence)

    def probe_evidence_words(self) -> Tuple[str, Tuple[str, ...]]:
        """Contract-wording variant (SC-forensics/R-05): the tri-state as
        ``rooted`` | ``not-rooted`` | ``unknown`` plus evidence lines."""
        status, evidence = self.probe_evidence()
        return status.value.replace("_", "-"), evidence
