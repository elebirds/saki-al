"""
System settings registry.

Single source of truth for all dynamic system settings.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from saki_api.core.config import settings
from saki_api.modules.system.service.system_setting_keys import SystemSettingKeys


@dataclass(frozen=True)
class SystemSettingDef:
    key: str
    group: str
    title: str
    description: str
    type: str
    default: Any
    editable: bool = True
    order: int = 0
    group_order: int = 0
    options: list[dict[str, Any]] = field(default_factory=list)
    constraints: dict[str, Any] = field(default_factory=dict)
    ui: dict[str, Any] = field(default_factory=dict)

    def to_schema(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["default"] = self.default
        return payload


_DEFS: list[SystemSettingDef] = [
    SystemSettingDef(
        key=SystemSettingKeys.GENERAL_APP_TITLE,
        group="general",
        title="应用标题",
        description="系统主标题，显示在登录页和导航顶栏。",
        type="string",
        default=settings.PROJECT_NAME,
        constraints={"min_length": 1, "max_length": 120},
        ui={"component": "input", "placeholder": "Saki Active Learning"},
        order=10,
        group_order=10,
    ),
    SystemSettingDef(
        key=SystemSettingKeys.GENERAL_APP_FOOTER,
        group="general",
        title="页脚文案",
        description="系统页面底部显示文案。",
        type="string",
        default="Saki Active Learning ©2025 Created by elebird.",
        constraints={"min_length": 1, "max_length": 300},
        ui={"component": "textarea", "rows": 2},
        order=20,
        group_order=10,
    ),
    SystemSettingDef(
        key=SystemSettingKeys.GENERAL_DEFAULT_LANGUAGE,
        group="general",
        title="默认语言",
        description="未命中浏览器语言时使用的默认语言。",
        type="enum",
        default="zh",
        options=[
            {"value": "zh", "label": "中文"},
            {"value": "en", "label": "English"},
        ],
        ui={"component": "select"},
        order=30,
        group_order=10,
    ),
    SystemSettingDef(
        key=SystemSettingKeys.AUTH_ALLOW_SELF_REGISTER,
        group="auth",
        title="允许用户主动注册",
        description="关闭后，/auth/register 将被拒绝。",
        type="boolean",
        default=False,
        ui={"component": "switch"},
        order=10,
        group_order=20,
    ),
    SystemSettingDef(
        key=SystemSettingKeys.DATASET_ALLOW_DUPLICATE_SAMPLE_NAMES_DEFAULT,
        group="dataset",
        title="新建数据集默认允许同名样本",
        description="仅影响新建数据集时的默认值，不回写历史数据集。",
        type="boolean",
        default=True,
        ui={"component": "switch"},
        order=10,
        group_order=30,
    ),
    SystemSettingDef(
        key=SystemSettingKeys.SIMULATION_SEED_RATIO,
        group="simulation",
        title="Simulation 默认 seed_ratio",
        description="默认初始种子比例，范围 [0,1]。",
        type="number",
        default=0.05,
        constraints={"min": 0.0, "max": 1.0},
        ui={"component": "number", "step": 0.01},
        order=10,
        group_order=40,
    ),
    SystemSettingDef(
        key=SystemSettingKeys.SIMULATION_STEP_RATIO,
        group="simulation",
        title="Simulation 默认 step_ratio",
        description="默认每轮增量比例，范围 [0,1]。",
        type="number",
        default=0.05,
        constraints={"min": 0.0, "max": 1.0},
        ui={"component": "number", "step": 0.01},
        order=20,
        group_order=40,
    ),
    SystemSettingDef(
        key=SystemSettingKeys.SIMULATION_MAX_ROUNDS,
        group="simulation",
        title="Simulation 默认 max_rounds",
        description="默认最大轮次数，必须 >= 1。",
        type="integer",
        default=20,
        constraints={"min": 1, "max": 1000},
        ui={"component": "number", "step": 1},
        order=30,
        group_order=40,
    ),
    SystemSettingDef(
        key=SystemSettingKeys.SIMULATION_SEEDS,
        group="simulation",
        title="Simulation 默认 seeds",
        description="默认随机种子列表（整数数组）。",
        type="integer_array",
        default=[0, 1, 2, 3, 4],
        constraints={"min_items": 1, "max_items": 64},
        ui={"component": "tags"},
        order=40,
        group_order=40,
    ),
    SystemSettingDef(
        key=SystemSettingKeys.SIMULATION_RANDOM_BASELINE_ENABLED,
        group="simulation",
        title="Simulation 默认启用随机基线",
        description="为真时自动加入 random baseline 策略。",
        type="boolean",
        default=True,
        ui={"component": "switch"},
        order=50,
        group_order=40,
    ),
    SystemSettingDef(
        key=SystemSettingKeys.MAINTENANCE_ASSET_GC_ENABLED,
        group="maintenance",
        title="启用无用 Asset 定时清理",
        description="开启后，后台按计划清理对象存储中的无引用资产。",
        type="boolean",
        default=False,
        ui={"component": "switch"},
        order=10,
        group_order=50,
    ),
    SystemSettingDef(
        key=SystemSettingKeys.MAINTENANCE_ASSET_GC_INTERVAL_HOURS,
        group="maintenance",
        title="Asset 清理间隔（小时）",
        description="定时任务执行周期，单位小时。",
        type="integer",
        default=24,
        constraints={"min": 1, "max": 24 * 30},
        ui={"component": "number", "step": 1},
        order=20,
        group_order=50,
    ),
    SystemSettingDef(
        key=SystemSettingKeys.MAINTENANCE_ASSET_GC_ORPHAN_AGE_HOURS,
        group="maintenance",
        title="Asset 判定无用时长（小时）",
        description="资产在无引用状态下超过该时长才会被清理。",
        type="integer",
        default=24 * 7,
        constraints={"min": 1, "max": 24 * 365},
        ui={"component": "number", "step": 1},
        order=30,
        group_order=50,
    ),
]


SYSTEM_SETTINGS_REGISTRY: dict[str, SystemSettingDef] = {item.key: item for item in _DEFS}


def list_setting_defs() -> list[SystemSettingDef]:
    return sorted(
        SYSTEM_SETTINGS_REGISTRY.values(),
        key=lambda item: (item.group_order, item.order, item.key),
    )
