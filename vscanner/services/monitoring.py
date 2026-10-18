"""SC-6 MonitoringService — honest device monitoring (Stage 08, R-04).

Port of the legacy sensor/usage probes with the fabrication and false
attribution removed:

* ``read_sensor_values_once`` parses ``dumpsys sensorservice`` into
  :class:`~vscanner.core.models.SensorReading` rows using the legacy
  Method-1 (``Name: values`` rows) and Method-2 (detection-list match →
  "Detected and available") semantics. The legacy "Method 3" fallback —
  inventing sensor names from ``ro.hardware`` when nothing was parseable —
  is **deliberately not ported**: zero parseable output yields an explicit
  ``UNAVAILABLE`` row with the reason, never invented names or values.

* ``read_hardware_usage_once`` polls ``dumpsys media.camera`` /
  ``dumpsys audio`` / ``dumpsys location`` and reports an
  :class:`~vscanner.core.models.ObservationState` per capability. The
  legacy attribution bugs are NOT ported:
  - it marked the camera "in use" because the *foreground* app matched;
    foreground focus is not evidence of who uses the camera;
  - it marked microphone/camera "in use" because the app *holds* the
    ``RECORD_AUDIO``/``CAMERA`` permission; a held permission is not
    active use.
  Instead a capability is OBSERVED_ACTIVE only when a documented marker
  appears in that capability's own dumpsys output; the matched line is
  kept as evidence. ``NOT_OBSERVED`` (probe ran, nothing matched) is
  never reported as "not in use" — it is not proof of inactivity.

All parsing is line-based over device-produced text; every row keeps the
device's own value strings (single-line, render-safe). No fabricated
counts, no fabricated measurements, unknown ≠ safe.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional, Protocol, Tuple

from vscanner.core.models import (
    HardwareUsageSnapshot,
    ObservationState,
    SensorReading,
    SensorStatus,
)

__all__ = ["MonitoringService", "SENSOR_NAME_HINTS", "SENSOR_NAME_TABLE"]

# Legacy Method-1 name hints (kept so the honest parser recognizes the same
# sensor-name lines the legacy UI understood).
SENSOR_NAME_HINTS: Tuple[str, ...] = (
    "Accelerometer", "Magnetometer", "Gyroscope", "Proximity", "Light",
    "Barometer", "Temperature", "Humidity",
)

# Legacy Method-2 full name table (detection list; a name becomes a row only
# when the device output actually matches it).
SENSOR_NAME_TABLE: Tuple[str, ...] = (
    "Accelerometer", "Magnetometer", "Gyroscope", "Light Sensor",
    "Proximity Sensor", "Barometer", "Thermometer", "Humidity Sensor",
    "Step Counter", "Tilt Detector",
)

_PROBE_TIMEOUT = 10.0


class _MonitoringTransport(Protocol):
    def run_text(self, cmd, timeout: float = _PROBE_TIMEOUT):  # pragma: no cover
        ...


def _single_line(raw: str) -> str:
    """Normalize a device-reported fragment to a render-safe single line."""
    return " ".join(raw.replace("\r", " ").replace("\n", " ").split())


class MonitoringService:
    """SC-6 sensor + capability monitoring over one serial-bound transport."""

    def __init__(self, transport: _MonitoringTransport) -> None:
        self._transport = transport

    # ------------------------------------------------------------------ #
    # sensor values (R-04)
    # ------------------------------------------------------------------ #

    def read_sensor_values_once(self) -> Tuple[SensorReading, ...]:
        """Read current sensor data honestly.

        Returns a tuple of :class:`SensorReading`. ``AVAILABLE`` rows carry
        only device-reported values. When *nothing* is parseable — transport
        failure, empty output, or unmatched lines — the result is a single
        ``UNAVAILABLE`` row explaining why. That is an honest complete
        answer, never invented data.
        """
        probe_failed: Optional[str] = None
        stdout = ""
        try:
            result = self._transport.run_text(
                ("shell", "dumpsys", "sensorservice"), timeout=_PROBE_TIMEOUT)
            stdout = getattr(result, "stdout", result)
        except Exception as exc:  # transport failures become honest reasons
            plain = type(exc).__name__
            probe_failed = f"sensor-service probe failed ({plain})"

        readings = self._parse_values_output(stdout) if stdout else []
        for name in self._detected_names(stdout):
            if not any(r.name == name for r in readings):
                readings.append(SensorReading(
                    name=name, status=SensorStatus.AVAILABLE,
                    values=("Detected and available",),
                ))

        if not readings:
            reason = probe_failed or (
                "sensor service produced no parseable sensor rows"
                if stdout.strip() == "" else
                "sensor service output contained no recognizable sensor rows"
            )
            readings.append(SensorReading(
                name="(no sensor rows)", status=SensorStatus.UNAVAILABLE,
                reason=reason,
            ))
        return tuple(readings)

    def list_sensor_capabilities(self) -> Tuple[str, ...]:
        """Sensor names actually detected on this device (never inferred).

        Empty means the probe yielded nothing — callers must render that as
        "no sensors detected in device output", not as "no sensors exist".
        """
        try:
            result = self._transport.run_text(
                ("shell", "dumpsys", "sensorservice"), timeout=_PROBE_TIMEOUT)
            stdout = getattr(result, "stdout", result)
        except Exception:
            return ()
        return tuple(self._detected_names(stdout))

    # ------------------------------------------------------------------ #
    # hardware usage (SC-6 camera/mic/location observation)
    # ------------------------------------------------------------------ #

    def read_hardware_usage_once(
        self, serial: Optional[str] = None,
    ) -> HardwareUsageSnapshot:
        """One poll of the camera / microphone / location surface.

        Each capability is OBSERVED_ACTIVE only when a documented pattern
        from that capability's own dumpsys output matches (counts matter:
        ``Active listeners: 0`` is *not* activity); NOT_OBSERVED when the
        probe ran clean and matched nothing (never "not in use"); UNKNOWN
        when the probe failed or output was unusable. Matched lines are
        preserved in ``evidence`` so a human can verify the claim.
        """
        probes = (
            ("camera", ("shell", "dumpsys", "media.camera"), _CAMERA_ACTIVE_PATTERNS),
            ("microphone", ("shell", "dumpsys", "audio"), _MIC_ACTIVE_PATTERNS),
            ("location", ("shell", "dumpsys", "location"), _LOCATION_ACTIVE_PATTERNS),
        )
        evidence: list[tuple[str, str]] = []
        failures: list[str] = []
        states: dict[str, ObservationState] = {}
        for capability, cmd, patterns in probes:
            state, matched = self._probe_one(cmd, patterns)
            states[capability] = state
            if matched is not None:
                evidence.append((capability, _single_line(matched)))
            if state is ObservationState.UNKNOWN:
                failures.append(f"{capability}: probe failed or output unparseable")
        return HardwareUsageSnapshot(
            camera=states["camera"],
            microphone=states["microphone"],
            location=states["location"],
            evidence=tuple(evidence),
            failures=tuple(failures),
            serial=serial,
            captured_at=datetime.now(timezone.utc),
        )

    # ------------------------------------------------------------------ #
    # internals
    # ------------------------------------------------------------------ #

    def _probe_one(self, cmd, patterns) -> tuple[ObservationState, Optional[str]]:
        """Run one probe; match its output against the capability patterns.

        ``patterns`` are compiled regexes evaluated per line; each may
        carry a ``count`` group that must be > 0 to count as activity.
        """
        try:
            result = self._transport.run_text(cmd, timeout=_PROBE_TIMEOUT)
            stdout = getattr(result, "stdout", result)
        except Exception:
            return ObservationState.UNKNOWN, None
        if not stdout or not stdout.strip():
            return ObservationState.UNKNOWN, None
        for line in stdout.splitlines():
            stripped = _single_line(line)
            if not stripped:
                continue
            for pattern in patterns:
                match = pattern.search(stripped)
                if match is None:
                    continue
                if "count" in pattern.groupindex:
                    try:
                        if int(match.group("count")) <= 0:
                            continue
                    except (TypeError, ValueError):
                        continue
                return ObservationState.OBSERVED_ACTIVE, stripped
        return ObservationState.NOT_OBSERVED, None

    def _detected_names(self, stdout: str) -> list[str]:
        """Legacy Method-2 semantics: name match against device output."""
        names: list[str] = []
        for line in stdout.splitlines():
            stripped = _single_line(line)
            if not stripped:
                continue
            for sensor_name in SENSOR_NAME_TABLE:
                if sensor_name.lower() in stripped.lower():
                    names.append(sensor_name)
        return list(dict.fromkeys(names))  # unique, order-preserving

    def _parse_values_output(self, stdout: str) -> list[SensorReading]:
        """Legacy Method-1 semantics: ``Name: values`` rows → AVAILABLE.

        A ``Name: <values>`` row needs a real, non-empty value fragment; a
        bare name mention is detection, not a measurement.
        """
        if not stdout:
            return []
        readings: list[SensorReading] = []
        for line in stdout.splitlines():
            stripped = _single_line(line)
            if not stripped or ":" not in stripped:
                continue
            for hint in SENSOR_NAME_HINTS:
                loc = stripped.find(hint)
                if loc == -1:
                    continue
                colon = stripped.find(":", loc)
                if colon == -1:
                    continue
                name_part = stripped[:colon].strip()
                value_part = stripped[colon + 1:].strip()
                if not value_part or not name_part:
                    continue
                # multi-word prefixes like "0: Accelerometer" keep the hint
                # word itself as the canonical name (legacy dict key parity)
                name = hint
                if hint not in name_part:
                    continue
                values = tuple(
                    piece for piece in (frag.strip() for frag in value_part.split(","))
                    if piece
                )
                if not values:
                    continue
                readings.append(SensorReading(
                    name=name, status=SensorStatus.AVAILABLE, values=values,
                ))
                break
        # one row per sensor name (last wins — latest reading)
        dedup: dict[str, SensorReading] = {}
        for reading in readings:
            dedup[reading.name] = reading
        return list(dedup.values())


# Documented activity patterns, ported conservatively from known dumpsys
# shapes (best-effort across Android versions; patterns with a ``count``
# group require > 0). Hardware verification remains a Stage 08 limitation:
# a NO-match is never reported as "not in use", so pattern looseness can
# only ever over-observe — never under-claim safety.
_CAMERA_ACTIVE_PATTERNS = (
    re.compile(r"Device \d+ is open"),
    re.compile(r"(?i)\bactive client\b"),
)
_MIC_ACTIVE_PATTERNS = (
    re.compile(r"(?i)\baudiorecord\b.*\bstarted\b|\bstarted\b.*\baudiorecord\b"),
    re.compile(r"(?i)recording sessions?:\s*(?P<count>\d+)"),
)
_LOCATION_ACTIVE_PATTERNS = (
    re.compile(r"(?i)active listeners:\s*(?P<count>\d+)"),
    re.compile(r"(?i)\bstarted listening\b"),
)
