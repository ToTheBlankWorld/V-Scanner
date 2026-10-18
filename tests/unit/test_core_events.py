"""Typed event-model tests (Stage 04 — core/events contract surface)."""

from __future__ import annotations

import dataclasses
from datetime import datetime, timezone

import pytest

from vscanner.core.errors import InputValidationError, VScannerError
from vscanner.core.events import (
    ALLOWED_LOG_LEVELS,
    JobConflictScope,
    JobEvent,
    JobFindingEvent,
    JobKind,
    JobLogChunkEvent,
    JobProgressEvent,
    JobSnapshotStreamEvent,
    JobStartedEvent,
    JobState,
    JobTerminalEvent,
    event_category,
    is_terminal_job_state,
)
from vscanner.core.models import (
    Evidence,
    EvidenceKind,
    Finding,
    FindingCategory,
    FindingSeverity,
    model_to_dict,
)


def _finding() -> Finding:
    return Finding(
        kind=FindingCategory.PERMISSION_EXCESS,
        severity=FindingSeverity.HIGH,
        title="READ_SMS",
        detail="reads text messages",
        evidence=(
            Evidence.of(
                EvidenceKind.CONFIRMED_ARTIFACT,
                description="declared",
                source="dumpsys package com.x",
                raw_excerpt="READ_SMS",
            ),
        ),
        app=None,
        device_serial="demo",
    )


class TestShape:
    def test_identity_defaults_allow_service_side_construction(self):
        event = JobProgressEvent(current=3, total=7, unit="apps", context="com.a")
        assert event.job_id == "" and event.kind is JobKind.OTHER
        assert event.seq == 0 and event.ts == 0.0

    def test_state_names_exact_and_terminal_set(self):
        assert [s.value for s in JobState] == [
            "queued", "running", "succeeded", "failed", "cancelled"
        ]
        assert is_terminal_job_state(JobState.SUCCEEDED)
        assert is_terminal_job_state(JobState.FAILED)
        assert is_terminal_job_state(JobState.CANCELLED)
        assert not is_terminal_job_state(JobState.QUEUED)
        assert not is_terminal_job_state(JobState.RUNNING)

    def test_job_kinds_are_the_documented_thirteen(self):
        expected = {
            "DEVICE_DISCOVERY", "APP_LISTING", "SINGLE_APP_SCAN",
            "FULL_DEVICE_SCAN", "DEVICE_INFO", "ADMIN_OP",
            "MONITORING_SESSION", "TOOL_PROVISIONING", "MIRRORING",
            "FORENSICS_OP", "EXPORT", "DEMO", "OTHER",
        }
        assert {member.name for member in JobKind} == expected

    def test_conflict_scopes(self):
        assert JobConflictScope.GLOBAL.value == "global"
        assert JobConflictScope.PER_DEVICE.value == "per_device"

    def test_event_categories_identical_for_both_frontends(self):
        pairs = [
            (JobStartedEvent(), "started"),
            (JobProgressEvent(), "progress"),
            (JobLogChunkEvent(), "log"),
            (JobFindingEvent(finding=_finding()), "finding"),
            (JobSnapshotStreamEvent(payload={"cpu": 1}), "snapshot"),
            (JobTerminalEvent(), "terminal"),
        ]
        for event, category in pairs:
            assert event_category(event) == category

    def test_log_levels_whitelist_documented(self):
        assert ALLOWED_LOG_LEVELS == frozenset({"debug", "info", "warning", "error"})


class TestImmutability:
    def test_events_never_mutate_post_construction(self):
        event = JobProgressEvent(current=1, total=2)
        with pytest.raises(dataclasses.FrozenInstanceError):
            event.current = 5
        terminal = JobTerminalEvent(outcome=JobState.CANCELLED)
        with pytest.raises(dataclasses.FrozenInstanceError):
            terminal.at_cancellation_point = "somewhere"

    def test_finding_payload_is_immutable_snapshot(self):
        finding = _finding()
        event = JobFindingEvent(finding=finding)
        with pytest.raises(dataclasses.FrozenInstanceError):
            event.finding = None
        assert event.finding is finding


class TestValidation:
    @pytest.mark.parametrize("level", ["verbose", "CRITICAL", "", "warn"])
    def test_invalid_log_level_refused(self, level):
        with pytest.raises(InputValidationError):
            JobLogChunkEvent(level=level)

    def test_negative_progress_refused(self):
        with pytest.raises(InputValidationError):
            JobProgressEvent(current=-1)

    def test_non_positive_total_refused(self):
        with pytest.raises(InputValidationError):
            JobProgressEvent(current=1, total=0)

    def test_current_over_total_refused(self):
        with pytest.raises(InputValidationError):
            JobProgressEvent(current=4, total=3)

    def test_total_none_is_honest_indeterminate(self):
        event = JobProgressEvent(current=1, total=None)
        assert event.total is None  # documented indeterminate-progress shape

    def test_nonterminal_outcome_refused(self):
        for state in (JobState.QUEUED, JobState.RUNNING):
            with pytest.raises(InputValidationError):
                JobTerminalEvent(outcome=state)

    def test_conservative_terminal_default_is_failed(self):
        assert JobTerminalEvent().outcome is JobState.FAILED


class TestSerialization:
    def test_events_serialize_to_primitives_only(self):
        event = JobStartedEvent(
            device_serial="demo",
            params_summary={"kind": "scan"},
        )
        dumped = model_to_dict(event)
        assert dumped["job_id"] == "" and dumped["seq"] == 0
        assert dumped["kind"] == "other"
        assert dumped["device_serial"] == "demo"
        assert isinstance(dumped["ts"], float)

    def test_finding_event_round_trips_without_functions(self):
        event = JobFindingEvent(finding=_finding())
        dumped = model_to_dict(event)
        assert dumped["finding"]["title"] == "READ_SMS"
        assert dumped["finding"]["evidence"][0]["kind"] == "confirmed_artifact"
        assert dumped["finding"]["evidence"][0]["raw_excerpt"] == "READ_SMS"

    def test_terminal_error_stays_a_typed_object_in_the_event(self):
        error = VScannerError("scan aborted", {"partial": True})
        event = JobTerminalEvent(outcome=JobState.FAILED, error=error)
        # The contract keeps error as the TYPED object (bridges read
        # .message/.details); it is never stringified into the payload.
        assert isinstance(event.error, VScannerError)
        dumped = model_to_dict(event)
        assert dumped["error"].message == "scan aborted"


class TestOperationConfirmation:
    def test_token_is_frozen_with_reference_and_time(self):
        from vscanner.core.events import OperationConfirmation

        token = OperationConfirmation(
            reference="uninstall:com.example.app",
            confirmed_at=datetime(2026, 10, 18, tzinfo=timezone.utc),
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            token.reference = "other"
