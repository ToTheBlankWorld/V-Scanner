"""Stage 08 backend-seam stubs for pre-Stage-08 test fakes.

The :class:`DeviceBackend` protocol grew the Stage 08 surface (root
tri-state, monitoring, admin, forensics, mirroring, demo, full device
info). Test fakes written for earlier stages do not script those
surfaces; instead of duplicating 12+ stubs into each fake, they inherit
:class:`Stage08StubBackend` so the structural protocol check passes. Any
accidental real call raises an honest, loud error — these fakes never
silently pretend a Stage 08 surface answered.
"""

from __future__ import annotations

from typing import Optional


_STUB_MSG = (
    "this legacy test fake does not script the Stage 08 backend surface")


class Stage08StubBackend:
    """Honest not-scripted stubs for the Stage 08 DeviceBackend members."""

    # -- R-05 root / Stage 08 device info ------------------------------------ #

    def root_status_now(self, serial: str):
        raise RuntimeError(_STUB_MSG)

    def full_device_info(self, serial: str):
        raise RuntimeError(_STUB_MSG)

    # -- SC-6 monitoring ------------------------------------------------------- #

    def read_sensors_once(self, serial: str):
        raise RuntimeError(_STUB_MSG)

    def start_monitoring_session(self, serial: str, interval_s: float):
        raise RuntimeError(_STUB_MSG)

    def stop_monitoring(self, serial: str) -> None:
        raise RuntimeError(_STUB_MSG)

    def active_monitoring_handle(self, serial: str):
        raise RuntimeError(_STUB_MSG)

    # -- SC-5 admin / forensic / demo / mirroring ------------------------------- #

    def start_admin_job(self, serial: str, op: str, package: str,
                        confirmation):
        raise RuntimeError(_STUB_MSG)

    def start_forensics_job(self, serial: str, op: str,
                            kwargs: Optional[dict]):
        raise RuntimeError(_STUB_MSG)

    def forensics_load_case(self, case_id: str):
        raise RuntimeError(_STUB_MSG)

    def demo_bundle(self):
        raise RuntimeError(_STUB_MSG)

    def start_demo_job(self):
        raise RuntimeError(_STUB_MSG)

    def mirror_launch(self, serial: str, options):
        raise RuntimeError(_STUB_MSG)

    def mirror_list(self, serial: Optional[str]):
        raise RuntimeError(_STUB_MSG)

    def mirror_stop(self, serial: str, pid: Optional[int] = None):
        raise RuntimeError(_STUB_MSG)
