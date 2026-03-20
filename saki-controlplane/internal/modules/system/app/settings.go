package app

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"strconv"
	"strings"

	systemdomain "github.com/elebirds/saki/saki-controlplane/internal/modules/system/domain"
	"github.com/google/uuid"
)

var (
	ErrInvalidSettingValue = errors.New("invalid system setting value")
	ErrNotInitialized      = errors.New("system is not initialized")
)

type SettingsStore interface {
	ListSettings(ctx context.Context, installationID uuid.UUID) ([]systemdomain.Setting, error)
	UpsertSetting(ctx context.Context, installationID uuid.UUID, key string, value json.RawMessage) (*systemdomain.Setting, error)
}

type SettingsBatchStore interface {
	UpsertSettings(ctx context.Context, installationID uuid.UUID, values map[string]json.RawMessage) error
}

type SettingsBundle struct {
	Schema []SettingDefinition
	Values map[string]json.RawMessage
}

type SettingsUseCase struct {
	installations InstallationGetter
	store         SettingsStore
}

func NewSettingsUseCase(installations InstallationGetter, store SettingsStore) *SettingsUseCase {
	return &SettingsUseCase{
		installations: installations,
		store:         store,
	}
}

func (u *SettingsUseCase) GetBundle(ctx context.Context) (*SettingsBundle, error) {
	values := DefaultSettingValues()
	definitions := make(map[string]struct{}, len(ListSettingDefinitions()))
	for _, definition := range ListSettingDefinitions() {
		definitions[definition.Key] = struct{}{}
	}
	installation, err := u.installations.Get(ctx)
	if err != nil {
		return nil, err
	}
	if installation != nil {
		rows, err := u.store.ListSettings(ctx, installation.ID)
		if err != nil {
			return nil, err
		}
		for _, setting := range rows {
			// 关键设计：settings schema 的真源在代码目录。
			// 读取时遇到历史脏 key 或已废弃 key，应该跳过而不是把整个接口打成 500。
			if _, ok := definitions[setting.Key]; !ok {
				continue
			}
			values[setting.Key] = append(json.RawMessage(nil), setting.Value...)
		}
	}

	return &SettingsBundle{
		Schema: ListSettingDefinitions(),
		Values: values,
	}, nil
}

func (u *SettingsUseCase) Patch(ctx context.Context, values map[string]json.RawMessage) (*SettingsBundle, error) {
	installation, err := u.installations.Get(ctx)
	if err != nil {
		return nil, err
	}
	if installation == nil || installation.InstallState != systemdomain.InstallationStateReady {
		return nil, ErrNotInitialized
	}

	// 关键设计：PATCH /system/settings 在语义上是一个“配置批次”。
	// 因此要先把整批输入全部校验并归一化，再统一落库，避免旧实现那种“前几个 key 已写入、后一个 key 校验失败”导致的部分成功。
	normalizedValues := make(map[string]json.RawMessage, len(values))
	for key, raw := range values {
		definition, ok := FindSettingDefinition(key)
		if !ok {
			return nil, fmt.Errorf("%w: unknown key %s", ErrInvalidSettingValue, key)
		}
		if !definition.Editable {
			return nil, fmt.Errorf("%w: setting %s is read-only", ErrInvalidSettingValue, key)
		}

		normalized, err := normalizeSettingValue(definition, raw)
		if err != nil {
			return nil, err
		}
		normalizedValues[key] = normalized
	}

	if batchStore, ok := u.store.(SettingsBatchStore); ok {
		if err := batchStore.UpsertSettings(ctx, installation.ID, normalizedValues); err != nil {
			return nil, err
		}
	} else {
		for key, normalized := range normalizedValues {
			if _, err := u.store.UpsertSetting(ctx, installation.ID, key, normalized); err != nil {
				return nil, err
			}
		}
	}

	return u.GetBundle(ctx)
}

func normalizeSettingValue(definition SettingDefinition, raw json.RawMessage) (json.RawMessage, error) {
	switch definition.Type {
	case "boolean":
		var value bool
		if err := json.Unmarshal(raw, &value); err != nil {
			return nil, fmt.Errorf("%w: %s must be a boolean", ErrInvalidSettingValue, definition.Key)
		}
		return mustMarshalValidated(definition, value)
	case "string":
		var value string
		if err := json.Unmarshal(raw, &value); err != nil {
			return nil, fmt.Errorf("%w: %s must be a string", ErrInvalidSettingValue, definition.Key)
		}
		value = strings.TrimSpace(value)
		if err := validateStringConstraints(definition, value); err != nil {
			return nil, err
		}
		return mustMarshalValidated(definition, value)
	case "integer":
		number, err := decodeJSONNumber(raw, true)
		if err != nil {
			return nil, fmt.Errorf("%w: %s must be an integer", ErrInvalidSettingValue, definition.Key)
		}
		value := int(number)
		if err := validateNumericConstraints(definition, float64(value)); err != nil {
			return nil, err
		}
		return mustMarshalValidated(definition, value)
	case "number":
		value, err := decodeJSONNumber(raw, false)
		if err != nil {
			return nil, fmt.Errorf("%w: %s must be a finite number", ErrInvalidSettingValue, definition.Key)
		}
		if err := validateNumericConstraints(definition, value); err != nil {
			return nil, err
		}
		return mustMarshalValidated(definition, value)
	case "enum":
		var value string
		if err := json.Unmarshal(raw, &value); err != nil {
			return nil, fmt.Errorf("%w: %s must be a string enum", ErrInvalidSettingValue, definition.Key)
		}
		value = strings.TrimSpace(value)
		allowed := make(map[string]struct{}, len(definition.Options))
		for _, option := range definition.Options {
			allowed[option.Value] = struct{}{}
		}
		if _, ok := allowed[value]; !ok {
			return nil, fmt.Errorf("%w: %s must be one of %v", ErrInvalidSettingValue, definition.Key, definition.Options)
		}
		return mustMarshalValidated(definition, value)
	default:
		return nil, fmt.Errorf("%w: unsupported type %s", ErrInvalidSettingValue, definition.Type)
	}
}

func mustMarshalValidated(_ SettingDefinition, value any) (json.RawMessage, error) {
	raw, err := json.Marshal(value)
	if err != nil {
		return nil, err
	}
	return raw, nil
}

func decodeJSONNumber(raw json.RawMessage, integer bool) (float64, error) {
	var value any
	if err := json.Unmarshal(raw, &value); err != nil {
		return 0, err
	}

	switch number := value.(type) {
	case float64:
		if math.IsNaN(number) || math.IsInf(number, 0) {
			return 0, errors.New("number is not finite")
		}
		if integer && number != math.Trunc(number) {
			return 0, errors.New("number is not integral")
		}
		return number, nil
	case string:
		parsed, err := strconv.ParseFloat(strings.TrimSpace(number), 64)
		if err != nil || math.IsNaN(parsed) || math.IsInf(parsed, 0) {
			return 0, errors.New("invalid numeric string")
		}
		if integer && parsed != math.Trunc(parsed) {
			return 0, errors.New("numeric string is not integral")
		}
		return parsed, nil
	default:
		return 0, errors.New("unsupported number type")
	}
}

func validateNumericConstraints(definition SettingDefinition, value float64) error {
	constraints := definition.Constraints
	if constraints == nil {
		return nil
	}

	if minimum, ok := decodeConstraintNumber(constraints["min"]); ok && value < minimum {
		return fmt.Errorf("%w: %s must be >= %v", ErrInvalidSettingValue, definition.Key, minimum)
	}
	if maximum, ok := decodeConstraintNumber(constraints["max"]); ok && value > maximum {
		return fmt.Errorf("%w: %s must be <= %v", ErrInvalidSettingValue, definition.Key, maximum)
	}
	return nil
}

func validateStringConstraints(definition SettingDefinition, value string) error {
	constraints := definition.Constraints
	if constraints == nil {
		return nil
	}

	if minimum, ok := decodeConstraintNumber(constraints["min_length"]); ok && len(value) < int(minimum) {
		return fmt.Errorf("%w: %s length must be >= %d", ErrInvalidSettingValue, definition.Key, int(minimum))
	}
	if maximum, ok := decodeConstraintNumber(constraints["max_length"]); ok && len(value) > int(maximum) {
		return fmt.Errorf("%w: %s length must be <= %d", ErrInvalidSettingValue, definition.Key, int(maximum))
	}
	return nil
}

func decodeConstraintNumber(raw json.RawMessage) (float64, bool) {
	if len(raw) == 0 {
		return 0, false
	}
	value, err := decodeJSONNumber(raw, false)
	if err != nil {
		return 0, false
	}
	return value, true
}
