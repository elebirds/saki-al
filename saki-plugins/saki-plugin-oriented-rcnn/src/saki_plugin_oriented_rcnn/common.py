from __future__ import annotations

"""插件内部通用工具函数。

设计说明：
1. 这里放纯函数，避免在业务代码里散落重复的容错逻辑。
2. 所有类型转换都做“保守失败回退”，保证运行时可预测。
"""

from pathlib import Path
from typing import Any


def to_int(value: Any, default: int) -> int:
    """尽量把输入转为 int；失败时返回默认值。"""
    try:
        return int(value)
    except Exception:
        return default


def to_float(value: Any, default: float) -> float:
    """尽量把输入转为 float；失败时返回默认值。"""
    try:
        return float(value)
    except Exception:
        return default


def to_bool(value: Any, default: bool) -> bool:
    """把常见字符串/数字形态转换为 bool。"""
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return bool(value)

    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def ensure_parent(path: Path) -> None:
    """确保文件父目录存在。"""
    path.parent.mkdir(parents=True, exist_ok=True)


def normalize_device(
    backend: str,
    device_spec: str,
) -> str:
    """将执行器绑定结果映射为 mmdet/mmengine 识别的 device 字符串。"""
    backend_text = str(backend or "").strip().lower()
    spec = str(device_spec or "").strip().lower()

    if backend_text == "cuda":
        if spec.startswith("cuda:"):
            return spec
        if spec.isdigit():
            return f"cuda:{spec}"
        return "cuda:0"

    # 当前版本只规划 CUDA + CPU。
    # 若宿主返回了其他 backend，这里统一回退 CPU，避免插件崩溃。
    return "cpu"


def sanitize_class_name(name: str) -> str:
    """将标签名转换为 DOTA 安全类名。

    关键约束：
    1. DOTA txt 是按空白分列，类名不能包含空白。
    2. 尽量保留原语义，因此只做最小必要替换。
    """
    text = str(name or "").strip()
    if not text:
        return "class_unnamed"
    safe = "_".join(text.split())
    safe = "".join(ch if ch.isalnum() or ch in {"_", "-", "."} else "_" for ch in safe)
    safe = safe.strip("_")
    return safe or "class_unnamed"
