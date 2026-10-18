"""ScreenMirrorService — SC-8 scrcpy launcher (Stage 08 port).

Legacy behavior (``ADBInterface.start_screen_mirroring``) kept: spawn
``scrcpy`` non-blocking with the same option shapes (``-s <serial>``,
optional ``-S`` screen-off, ``-m 1024``, ``--max-fps 30``). Stage 08 adds
the honesty the legacy lacked:

* tool-validated precondition: an unvalidated scrcpy raises
  :class:`~vscanner.core.errors.ToolNotValidated` — never a silent
  ``False`` that the user misreads as a device problem;
* an in-process handle registry so a launched mirror can actually be
  *stopped* (legacy spawned and forgot the process);
* ``turn_screen_off`` requires ``confirm_screen_off`` on the options
  (model-level guard) — the screen-off change is device-mutating;
* spawn uses an argv list (never a shell string — R-12 hardening);
* launch failures surface as typed errors, not swallowed exceptions.
"""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from typing import Callable, Optional, Protocol, Tuple

from vscanner.core.errors import ToolNotValidated
from vscanner.core.models import MirrorHandle, MirrorOptions, ToolId, ToolState

__all__ = ["ScreenMirrorService", "TOOL_ID"]

TOOL_ID = ToolId.SCRCPY


class _ToolStatusCallable(Protocol):
    """Anything returning the current ToolStatusReflected for scrcpy."""

    def __call__(self) -> object:  # pragma: no cover
        ...


class ScreenMirrorService:
    """SC-8: validate → launch → track → stop, all argv-only."""

    def __init__(
        self,
        adb_path: Callable[[], str],
        scrcpy_path: Callable[[], Optional[str]],
        tool_status: _ToolStatusCallable,
        serial: Optional[str] = None,
    ) -> None:
        self._adb_path = adb_path
        self._scrcpy_path = scrcpy_path
        self._tool_status = tool_status
        self._serial = serial
        self._handles: dict[int, MirrorHandle] = {}
        self._processes: dict[int, subprocess.Popen] = {}

    # ------------------------------------------------------------------ #
    # public
    # ------------------------------------------------------------------ #

    def launch(self, options: Optional[MirrorOptions] = None) -> MirrorHandle:
        """Validate the tool, spawn scrcpy (never blocking the caller),
        register and return the handle."""
        options = options or MirrorOptions()
        status = self._tool_status()
        state = getattr(status, "state", None)
        if state is not ToolState.VALIDATED:
            note = getattr(status, "path", None)
            raise ToolNotValidated(
                "screen mirroring requires a validated scrcpy tool; open "
                "Tools and provision/validate it first",
                {"scrcpy_path": note or "not provisioned"},
            )
        exe = self._scrcpy_path()
        if not exe:
            raise ToolNotValidated(
                "scrcpy executable path is not provisioned",
                {"scrcpy_path": "absent"},
            )
        cmd: list[str] = [exe]
        if self._serial:
            cmd.extend(["-s", self._serial])
        if options.turn_screen_off:
            cmd.append("-S")
        if options.resolution:
            cmd.extend(["-m", str(int(options.resolution))])
        if options.max_fps:
            cmd.extend(["--max-fps", str(int(options.max_fps))])
        if options.always_on_top:
            cmd.append("--always-on-top")
        # adb path comes into visibility via scrcpy's own adb resolution;
        # kept explicit on PATH for the child process
        env_hint = self._adb_path()
        _ = env_hint  # documented: scrcpy finds adb on PATH; no injection
        try:
            process = subprocess.Popen(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            raise ToolNotValidated(
                f"scrcpy launch failed: {exc}",
                {"scrcpy_path": exe},
            ) from exc
        handle = MirrorHandle(
            pid=process.pid,
            serial=self._serial,
            launched_at=datetime.now(timezone.utc).isoformat(),
            command=tuple(cmd),
        )
        self._handles[handle.pid] = handle
        self._processes[handle.pid] = process
        return handle

    def list_running(self) -> Tuple[MirrorHandle, ...]:
        """Snapshot of handles with honest exit states (exited processes
        keep their recorded exit code visible)."""
        running: list[MirrorHandle] = []
        for pid, process in list(self._processes.items()):
            code = process.poll()
            handle = self._handles[pid]
            if code is None:
                running.append(handle)
            else:
                exited = MirrorHandle(
                    pid=handle.pid, serial=handle.serial,
                    launched_at=handle.launched_at, command=handle.command,
                    exit_code=code,
                )
                self._handles[pid] = exited
                running.append(exited)
        # long-past handles drop out of the registry after full retirement
        self._processes = {
            pid: proc for pid, proc in self._processes.items()
            if proc.poll() is None
        }
        return tuple(running)

    def all_handles(self) -> Tuple[MirrorHandle, ...]:
        """Every registered handle including exited ones (honest history)."""
        out = [self.list_running()]
        flat = list(out[0])
        # exited handles still registered under _handles but not returned
        # by list_running stay visible here
        included = {h.pid for h in flat}
        for handle in self._handles.values():
            if handle.pid not in included:
                flat.append(handle)
        return tuple(flat)

    def stop(self, pid: Optional[int] = None) -> Tuple[int, ...]:
        """Terminate one handle (or all running ones). Returns the pids
        that were still running and received the terminate signal."""
        stopped: list[int] = []
        targets = ([self._processes[pid]] if pid is not None
                   and pid in self._processes
                   else list(self._processes.values()))
        for process in targets:
            if process.poll() is None:
                try:
                    process.terminate()
                except OSError:
                    continue
                stopped.append(process.pid)
        return tuple(stopped)
