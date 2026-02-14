from __future__ import annotations

import uuid

from saki_api.infra.grpc.runtime_control import _build_activation_key


def test_build_activation_key_is_order_insensitive():
    loop_id = uuid.uuid4()
    sample_a = uuid.uuid4()
    sample_b = uuid.uuid4()
    first = _build_activation_key(loop_id, 2, [sample_a, sample_b, sample_a])
    second = _build_activation_key(loop_id, 2, [sample_b, sample_a])
    assert first == second


def test_build_activation_key_changes_with_round_index():
    loop_id = uuid.uuid4()
    sample = uuid.uuid4()
    key_round_1 = _build_activation_key(loop_id, 1, [sample])
    key_round_2 = _build_activation_key(loop_id, 2, [sample])
    assert key_round_1 != key_round_2
