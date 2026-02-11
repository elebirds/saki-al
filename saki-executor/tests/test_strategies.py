from saki_executor.strategies.builtin import (
    score_by_strategy,
    uncertainty_1_minus_max_conf,
    aug_iou_disagreement,
    random_baseline,
    plugin_native_strategy,
)


def test_strategy_score_range():
    sample_id = "00000000-0000-0000-0000-000000000001"
    for fn in [uncertainty_1_minus_max_conf, aug_iou_disagreement, random_baseline, plugin_native_strategy]:
        score, _ = fn(sample_id)
        assert 0.0 <= score <= 1.0


def test_strategy_deterministic_for_same_sample():
    sample_id = "00000000-0000-0000-0000-000000000002"
    s1, _ = score_by_strategy("uncertainty_1_minus_max_conf", sample_id)
    s2, _ = score_by_strategy("uncertainty_1_minus_max_conf", sample_id)
    assert s1 == s2


def test_plugin_native_strategy_alias():
    sample_id = "00000000-0000-0000-0000-000000000003"
    s1, _ = score_by_strategy("plugin_native_strategy", sample_id)
    s2, _ = score_by_strategy("plugin_native", sample_id)
    assert s1 == s2
