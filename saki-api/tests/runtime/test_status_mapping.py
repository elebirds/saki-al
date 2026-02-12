from __future__ import annotations

import uuid

import pytest

from saki_api.grpc_gen import runtime_control_pb2 as pb
from saki_api.modules.runtime.service.ingress.control_ingress_service import RuntimeControlIngressService
from saki_api.modules.shared.modeling.enums import JobTaskStatus


def test_task_status_mapping():
    assert RuntimeControlIngressService._status_from_pb(pb.PENDING) == JobTaskStatus.PENDING
    assert RuntimeControlIngressService._status_from_pb(pb.DISPATCHING) == JobTaskStatus.DISPATCHING
    assert RuntimeControlIngressService._status_from_pb(pb.RUNNING) == JobTaskStatus.RUNNING
    assert RuntimeControlIngressService._status_from_pb(pb.RETRYING) == JobTaskStatus.RETRYING
    assert RuntimeControlIngressService._status_from_pb(pb.SUCCEEDED) == JobTaskStatus.SUCCEEDED
    assert RuntimeControlIngressService._status_from_pb(pb.FAILED) == JobTaskStatus.FAILED
    assert RuntimeControlIngressService._status_from_pb(pb.CANCELLED) == JobTaskStatus.CANCELLED
    assert RuntimeControlIngressService._status_from_pb(pb.SKIPPED) == JobTaskStatus.SKIPPED


def test_parse_uuid_success_and_failure():
    raw = str(uuid.uuid4())
    assert RuntimeControlIngressService._parse_uuid(raw, "task_id") == uuid.UUID(raw)

    with pytest.raises(ValueError):
        RuntimeControlIngressService._parse_uuid("", "task_id")

    with pytest.raises(ValueError):
        RuntimeControlIngressService._parse_uuid("not-a-uuid", "task_id")


def test_to_datetime_millis_never_returns_naive_datetime():
    ts = RuntimeControlIngressService._to_datetime_millis(1700000000000)
    assert ts.tzinfo is not None

    now_fallback = RuntimeControlIngressService._to_datetime_millis(0)
    assert now_fallback.tzinfo is not None
