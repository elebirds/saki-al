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


def test_build_activation_key_matches_fixed_vector():
    loop_id = uuid.UUID("5f9cc0b9-5605-45f9-ab99-57e099a14d77")
    sample_a = uuid.UUID("11111111-1111-1111-1111-111111111111")
    sample_b = uuid.UUID("22222222-2222-2222-2222-222222222222")
    got = _build_activation_key(loop_id, 3, [sample_b, sample_a, sample_a])
    want = "5f9cc0b9-5605-45f9-ab99-57e099a14d77:3:c1a7fa483d0a044307c7f0618f7cda833cb9472c39b659fdb705f9af2f16090d"
    assert got == want
