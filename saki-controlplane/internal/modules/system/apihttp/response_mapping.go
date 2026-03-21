package apihttp

import (
	"encoding/json"
	"fmt"

	openapi "github.com/elebirds/saki/saki-controlplane/internal/gen/openapi"
	systemapp "github.com/elebirds/saki/saki-controlplane/internal/modules/system/app"
	systemdomain "github.com/elebirds/saki/saki-controlplane/internal/modules/system/domain"
)

func mapInitializationState(value systemdomain.InitializationState) openapi.SystemStatusResponseInitializationState {
	// 关键设计：公开 API 只暴露 initialization 语义，
	// `/system/status` 与 `/system/init` 因此共享同一套词汇，不再外泄 install/setup 历史命名。
	switch value {
	case systemdomain.InitializationStateInitialized:
		return openapi.SystemStatusResponseInitializationStateInitialized
	default:
		return openapi.SystemStatusResponseInitializationStateUninitialized
	}
}

func mapTypeInfo(item systemapp.TypeInfo) openapi.SystemTypeInfo {
	return openapi.SystemTypeInfo{
		Value:                  item.Value,
		Label:                  item.Label,
		Description:            item.Description,
		Color:                  item.Color,
		Enabled:                item.Enabled,
		AllowedAnnotationTypes: append([]string(nil), item.AllowedAnnotationTypes...),
		MustAnnotationTypes:    append([]string(nil), item.MustAnnotationTypes...),
		BannedAnnotationTypes:  append([]string(nil), item.BannedAnnotationTypes...),
	}
}

func mapSettingsBundle(bundle *systemapp.SettingsBundle) (*openapi.SystemSettingsResponse, error) {
	response := &openapi.SystemSettingsResponse{
		Schema: make([]openapi.SystemSettingField, 0, len(bundle.Schema)),
		Values: make(openapi.SystemSettingsResponseValues, len(bundle.Values)),
	}

	definitions := make(map[string]systemapp.SettingDefinition, len(bundle.Schema))
	for _, definition := range bundle.Schema {
		definitions[definition.Key] = definition

		field, err := mapSettingDefinition(definition)
		if err != nil {
			return nil, err
		}
		response.Schema = append(response.Schema, field)
	}
	for key, raw := range bundle.Values {
		definition, ok := definitions[key]
		if !ok {
			return nil, fmt.Errorf("unknown setting definition for key %s", key)
		}
		value, err := rawToOpenAPISettingValue(raw, definition.Type)
		if err != nil {
			return nil, err
		}
		response.Values[key] = value
	}
	return response, nil
}

func mapSettingDefinition(definition systemapp.SettingDefinition) (openapi.SystemSettingField, error) {
	field := openapi.SystemSettingField{
		Key:         definition.Key,
		Group:       definition.Group,
		Title:       definition.Title,
		Description: definition.Description,
		Type:        definition.Type,
		Editable:    definition.Editable,
		Order:       int32(definition.Order),
		GroupOrder:  int32(definition.GroupOrder),
		Options:     make([]openapi.SystemSettingOption, 0, len(definition.Options)),
	}

	defaultValue, err := rawToOpenAPISettingValue(definition.Default, definition.Type)
	if err != nil {
		return openapi.SystemSettingField{}, err
	}
	field.Default = defaultValue

	for _, option := range definition.Options {
		field.Options = append(field.Options, openapi.SystemSettingOption{
			Value: option.Value,
			Label: option.Label,
		})
	}

	if constraints := mapSettingConstraints(definition.Constraints); constraints != nil {
		field.Constraints.SetTo(*constraints)
	}
	if ui := mapSettingUI(definition.UI); ui != nil {
		field.UI.SetTo(*ui)
	}
	return field, nil
}

func mapSettingConstraints(values map[string]json.RawMessage) *openapi.SystemSettingConstraints {
	if len(values) == 0 {
		return nil
	}

	constraints := &openapi.SystemSettingConstraints{}
	if value, ok := decodeConstraintFloat(values["min"]); ok {
		constraints.Min.SetTo(value)
	}
	if value, ok := decodeConstraintFloat(values["max"]); ok {
		constraints.Max.SetTo(value)
	}
	if value, ok := decodeConstraintInt(values["min_length"]); ok {
		constraints.MinLength.SetTo(value)
	}
	if value, ok := decodeConstraintInt(values["max_length"]); ok {
		constraints.MaxLength.SetTo(value)
	}
	if value, ok := decodeConstraintInt(values["min_items"]); ok {
		constraints.MinItems.SetTo(value)
	}
	if value, ok := decodeConstraintInt(values["max_items"]); ok {
		constraints.MaxItems.SetTo(value)
	}
	if value, ok := decodeConstraintFloat(values["step"]); ok {
		constraints.Step.SetTo(value)
	}
	return constraints
}

func mapSettingUI(values map[string]json.RawMessage) *openapi.SystemSettingUI {
	if len(values) == 0 {
		return nil
	}

	ui := &openapi.SystemSettingUI{}
	if value, ok := decodeConstraintString(values["component"]); ok {
		ui.Component.SetTo(value)
	}
	if value, ok := decodeConstraintString(values["placeholder"]); ok {
		ui.Placeholder.SetTo(value)
	}
	if value, ok := decodeConstraintInt(values["rows"]); ok {
		ui.Rows.SetTo(value)
	}
	return ui
}

func rawToOpenAPISettingValue(raw json.RawMessage, kind string) (openapi.SystemSettingValue, error) {
	value := openapi.SystemSettingValue{Kind: kind}
	switch kind {
	case "boolean":
		var decoded bool
		if err := json.Unmarshal(raw, &decoded); err != nil {
			return openapi.SystemSettingValue{}, err
		}
		value.BoolValue.SetTo(decoded)
	case "string", "enum":
		var decoded string
		if err := json.Unmarshal(raw, &decoded); err != nil {
			return openapi.SystemSettingValue{}, err
		}
		value.StringValue.SetTo(decoded)
	case "integer":
		var decoded int
		if err := json.Unmarshal(raw, &decoded); err != nil {
			return openapi.SystemSettingValue{}, err
		}
		value.IntegerValue.SetTo(decoded)
	case "number":
		var decoded float64
		if err := json.Unmarshal(raw, &decoded); err != nil {
			return openapi.SystemSettingValue{}, err
		}
		value.NumberValue.SetTo(decoded)
	case "integer_array":
		var decoded []int
		if err := json.Unmarshal(raw, &decoded); err != nil {
			return openapi.SystemSettingValue{}, err
		}
		value.IntegerArrayValue = append([]int(nil), decoded...)
	default:
		return openapi.SystemSettingValue{}, fmt.Errorf("unsupported setting type %s", kind)
	}
	return value, nil
}

func openAPISettingValueToRaw(value openapi.SystemSettingValue, expectedKind string) (json.RawMessage, error) {
	if value.Kind != "" && value.Kind != expectedKind {
		return nil, fmt.Errorf("%w: expected kind %s but got %s", systemapp.ErrInvalidSettingValue, expectedKind, value.Kind)
	}

	switch expectedKind {
	case "boolean":
		decoded, ok := value.BoolValue.Get()
		if !ok {
			return nil, fmt.Errorf("%w: %s requires bool_value", systemapp.ErrInvalidSettingValue, value.Kind)
		}
		return json.Marshal(decoded)
	case "string", "enum":
		decoded, ok := value.StringValue.Get()
		if !ok {
			return nil, fmt.Errorf("%w: %s requires string_value", systemapp.ErrInvalidSettingValue, value.Kind)
		}
		return json.Marshal(decoded)
	case "integer":
		decoded, ok := value.IntegerValue.Get()
		if !ok {
			return nil, fmt.Errorf("%w: %s requires integer_value", systemapp.ErrInvalidSettingValue, value.Kind)
		}
		return json.Marshal(decoded)
	case "number":
		decoded, ok := value.NumberValue.Get()
		if !ok {
			return nil, fmt.Errorf("%w: %s requires number_value", systemapp.ErrInvalidSettingValue, value.Kind)
		}
		return json.Marshal(decoded)
	case "integer_array":
		return json.Marshal(append([]int(nil), value.IntegerArrayValue...))
	default:
		return nil, fmt.Errorf("%w: unsupported setting type %s", systemapp.ErrInvalidSettingValue, expectedKind)
	}
}

func decodeConstraintFloat(raw json.RawMessage) (float64, bool) {
	if len(raw) == 0 {
		return 0, false
	}
	var value float64
	if err := json.Unmarshal(raw, &value); err != nil {
		return 0, false
	}
	return value, true
}

func decodeConstraintInt(raw json.RawMessage) (int, bool) {
	if len(raw) == 0 {
		return 0, false
	}
	var value int
	if err := json.Unmarshal(raw, &value); err != nil {
		return 0, false
	}
	return value, true
}

func decodeConstraintString(raw json.RawMessage) (string, bool) {
	if len(raw) == 0 {
		return "", false
	}
	var value string
	if err := json.Unmarshal(raw, &value); err != nil {
		return "", false
	}
	return value, true
}
