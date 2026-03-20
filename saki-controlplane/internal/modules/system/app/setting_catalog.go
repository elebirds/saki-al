package app

import (
	"encoding/json"
	"slices"
)

const (
	SettingKeyGeneralAppTitle                     = "general.app_title"
	SettingKeyGeneralAppFooter                    = "general.app_footer"
	SettingKeyGeneralDefaultLanguage              = "general.default_language"
	SettingKeyAuthAllowSelfRegister               = "auth.allow_self_register"
	SettingKeyDatasetAllowDuplicateSampleNames    = "dataset.allow_duplicate_sample_names_default"
	SettingKeyImportMaxZipBytes                   = "import.max_zip_bytes"
	SettingKeySimulationSeedRatio                 = "simulation.seed_ratio"
	SettingKeySimulationStepRatio                 = "simulation.step_ratio"
	SettingKeySimulationMaxRounds                 = "simulation.max_rounds"
	SettingKeyMaintenanceRuntimeMode              = "maintenance.runtime_mode"
	SettingKeyMaintenanceAssetGCEnabled           = "maintenance.asset_gc_enabled"
	SettingKeyMaintenanceAssetGCIntervalHours     = "maintenance.asset_gc_interval_hours"
	SettingKeyMaintenanceAssetGCOrphanAgeHours    = "maintenance.asset_gc_orphan_age_hours"
)

type SettingOption struct {
	Value string
	Label string
}

type SettingDefinition struct {
	Key         string
	Group       string
	Title       string
	Description string
	Type        string
	Default     json.RawMessage
	Editable    bool
	Order       int
	GroupOrder  int
	Options     []SettingOption
	Constraints map[string]json.RawMessage
	UI          map[string]json.RawMessage
}

// 关键设计：system settings schema 由 Go 代码静态注册，而不是散落到 handler 或数据库里临时拼装。
// 这样 setup 默认值、status 读取逻辑、settings API schema 三者共享同一份真源，避免旧 saki-api 里多处复制后逐步漂移。
func ListSettingDefinitions() []SettingDefinition {
	definitions := []SettingDefinition{
		{
			Key:         SettingKeyGeneralAppTitle,
			Group:       "general",
			Title:       "应用标题",
			Description: "系统主标题，显示在登录页和导航顶栏。",
			Type:        "string",
			Default:     mustRaw("Saki Active Learning"),
			Editable:    true,
			Order:       10,
			GroupOrder:  10,
			Constraints: rawMap(map[string]any{"min_length": 1, "max_length": 120}),
			UI:          rawMap(map[string]any{"component": "input", "placeholder": "Saki Active Learning"}),
		},
		{
			Key:         SettingKeyGeneralAppFooter,
			Group:       "general",
			Title:       "页脚文案",
			Description: "系统页面底部显示文案。",
			Type:        "string",
			Default:     mustRaw("Saki Active Learning ©2025 Created by elebird."),
			Editable:    true,
			Order:       20,
			GroupOrder:  10,
			Constraints: rawMap(map[string]any{"min_length": 1, "max_length": 300}),
			UI:          rawMap(map[string]any{"component": "textarea", "rows": 2}),
		},
		{
			Key:         SettingKeyGeneralDefaultLanguage,
			Group:       "general",
			Title:       "默认语言",
			Description: "未命中浏览器语言时使用的默认语言。",
			Type:        "enum",
			Default:     mustRaw("zh"),
			Editable:    true,
			Order:       30,
			GroupOrder:  10,
			Options: []SettingOption{
				{Value: "zh", Label: "中文"},
				{Value: "en", Label: "English"},
			},
			UI: rawMap(map[string]any{"component": "select"}),
		},
		{
			Key:         SettingKeyAuthAllowSelfRegister,
			Group:       "auth",
			Title:       "允许用户主动注册",
			Description: "关闭后，/auth/register 将被拒绝。",
			Type:        "boolean",
			Default:     mustRaw(false),
			Editable:    true,
			Order:       10,
			GroupOrder:  20,
			UI:          rawMap(map[string]any{"component": "switch"}),
		},
		{
			Key:         SettingKeyDatasetAllowDuplicateSampleNames,
			Group:       "dataset",
			Title:       "新建数据集默认允许同名样本",
			Description: "仅影响新建数据集时的默认值，不回写历史数据集。",
			Type:        "boolean",
			Default:     mustRaw(true),
			Editable:    true,
			Order:       10,
			GroupOrder:  30,
			UI:          rawMap(map[string]any{"component": "switch"}),
		},
		{
			Key:         SettingKeyImportMaxZipBytes,
			Group:       "import",
			Title:       "导入 ZIP 最大体积（字节）",
			Description: "导入上传会话与预检统一体积上限。2C4G 推荐 2147483648（2GB）。",
			Type:        "integer",
			Default:     mustRaw(2 * 1024 * 1024 * 1024),
			Editable:    true,
			Order:       10,
			GroupOrder:  35,
			Constraints: rawMap(map[string]any{"min": 64 * 1024 * 1024, "max": 20 * 1024 * 1024 * 1024}),
			UI:          rawMap(map[string]any{"component": "number", "step": 1024 * 1024}),
		},
		{
			Key:         SettingKeySimulationSeedRatio,
			Group:       "simulation",
			Title:       "Simulation 默认 seed_ratio",
			Description: "默认初始种子比例，范围 [0,1]。",
			Type:        "number",
			Default:     mustRaw(0.05),
			Editable:    true,
			Order:       10,
			GroupOrder:  40,
			Constraints: rawMap(map[string]any{"min": 0.0, "max": 1.0}),
			UI:          rawMap(map[string]any{"component": "number", "step": 0.01}),
		},
		{
			Key:         SettingKeySimulationStepRatio,
			Group:       "simulation",
			Title:       "Simulation 默认 step_ratio",
			Description: "默认每轮增量比例，范围 [0,1]。",
			Type:        "number",
			Default:     mustRaw(0.05),
			Editable:    true,
			Order:       20,
			GroupOrder:  40,
			Constraints: rawMap(map[string]any{"min": 0.0, "max": 1.0}),
			UI:          rawMap(map[string]any{"component": "number", "step": 0.01}),
		},
		{
			Key:         SettingKeySimulationMaxRounds,
			Group:       "simulation",
			Title:       "Simulation 默认 max_rounds",
			Description: "默认最大轮次数，必须 >= 1。",
			Type:        "integer",
			Default:     mustRaw(20),
			Editable:    true,
			Order:       30,
			GroupOrder:  40,
			Constraints: rawMap(map[string]any{"min": 1, "max": 1000}),
			UI:          rawMap(map[string]any{"component": "number", "step": 1}),
		},
		{
			Key:         SettingKeyMaintenanceRuntimeMode,
			Group:       "maintenance",
			Title:       "运行时维护模式",
			Description: "控制运行时是否正常派发、排空或强制进入可恢复暂停。",
			Type:        "enum",
			Default:     mustRaw("normal"),
			Editable:    true,
			Order:       5,
			GroupOrder:  50,
			Options: []SettingOption{
				{Value: "normal", Label: "Normal"},
				{Value: "drain", Label: "Drain"},
				{Value: "pause_now", Label: "Pause Now"},
			},
			UI: rawMap(map[string]any{"component": "select"}),
		},
		{
			Key:         SettingKeyMaintenanceAssetGCEnabled,
			Group:       "maintenance",
			Title:       "启用无用 Asset 定时清理",
			Description: "开启后，后台按计划清理对象存储中的无引用资产。",
			Type:        "boolean",
			Default:     mustRaw(false),
			Editable:    true,
			Order:       10,
			GroupOrder:  50,
			UI:          rawMap(map[string]any{"component": "switch"}),
		},
		{
			Key:         SettingKeyMaintenanceAssetGCIntervalHours,
			Group:       "maintenance",
			Title:       "Asset 清理间隔（小时）",
			Description: "定时任务执行周期，单位小时。",
			Type:        "integer",
			Default:     mustRaw(24),
			Editable:    true,
			Order:       20,
			GroupOrder:  50,
			Constraints: rawMap(map[string]any{"min": 1, "max": 24 * 30}),
			UI:          rawMap(map[string]any{"component": "number", "step": 1}),
		},
		{
			Key:         SettingKeyMaintenanceAssetGCOrphanAgeHours,
			Group:       "maintenance",
			Title:       "Asset 判定无用时长（小时）",
			Description: "资产在无引用状态下超过该时长才会被清理。",
			Type:        "integer",
			Default:     mustRaw(24 * 7),
			Editable:    true,
			Order:       30,
			GroupOrder:  50,
			Constraints: rawMap(map[string]any{"min": 1, "max": 24 * 365}),
			UI:          rawMap(map[string]any{"component": "number", "step": 1}),
		},
	}

	slices.SortFunc(definitions, func(a, b SettingDefinition) int {
		if a.GroupOrder != b.GroupOrder {
			if a.GroupOrder < b.GroupOrder {
				return -1
			}
			return 1
		}
		if a.Order != b.Order {
			if a.Order < b.Order {
				return -1
			}
			return 1
		}
		switch {
		case a.Key < b.Key:
			return -1
		case a.Key > b.Key:
			return 1
		default:
			return 0
		}
	})

	return definitions
}

func FindSettingDefinition(key string) (SettingDefinition, bool) {
	for _, definition := range ListSettingDefinitions() {
		if definition.Key == key {
			return definition, true
		}
	}
	return SettingDefinition{}, false
}

func DefaultSettingValues() map[string]json.RawMessage {
	values := make(map[string]json.RawMessage, len(ListSettingDefinitions()))
	for _, definition := range ListSettingDefinitions() {
		values[definition.Key] = append(json.RawMessage(nil), definition.Default...)
	}
	return values
}

func rawMap(values map[string]any) map[string]json.RawMessage {
	if len(values) == 0 {
		return nil
	}
	result := make(map[string]json.RawMessage, len(values))
	for key, value := range values {
		result[key] = mustRaw(value)
	}
	return result
}

func mustRaw(value any) json.RawMessage {
	raw, err := json.Marshal(value)
	if err != nil {
		panic(err)
	}
	return raw
}
