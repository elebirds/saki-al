from __future__ import annotations

from pathlib import Path

from saki_plugin_oriented_rcnn.config_builder import (
    _resolve_warmup_iters,
    build_mmrotate_runtime_cfg,
)


def test_resolve_warmup_iters_is_adaptive_for_small_dataset() -> None:
    # 24 样本 / batch=2 / epochs=12 => 总迭代约 144，warmup 应约束在 14，而不是固定 500。
    warmup_iters = _resolve_warmup_iters(train_sample_count=24, batch=2, epochs=12)
    assert warmup_iters == 14


def test_resolve_warmup_iters_has_safe_fallback_when_sample_unknown() -> None:
    # 无法获知样本规模时，使用保守小 warmup，避免再次出现“全程 warmup”。
    warmup_iters = _resolve_warmup_iters(train_sample_count=0, batch=2, epochs=12)
    assert warmup_iters == 20


def test_build_runtime_cfg_uses_low_test_score_thr_and_dynamic_warmup(tmp_path: Path) -> None:
    cfg_path = tmp_path / "runtime_cfg.py"
    build_mmrotate_runtime_cfg(
        output_path=cfg_path,
        data_root=tmp_path / "data",
        classes=("class_a", "class_b"),
        epochs=12,
        batch=2,
        workers=2,
        imgsz=1024,
        nms_iou_thr=0.1,
        max_per_img=2000,
        val_degraded=False,
        work_dir=tmp_path / "work",
        load_from="https://example.com/checkpoint.pth",
        train_seed=42,
        train_sample_count=24,
    )

    text = cfg_path.read_text(encoding="utf-8")
    # 模型侧评估阈值要足够低，避免候选框在 evaluator 前被过早清空。
    assert "score_thr=0.001" in text
    # warmup 迭代应该来自自适应计算结果（14），不能回退成固定 500。
    assert 'type="LinearLR", begin=0, end=14' in text
