package apihttp

import (
	"context"
	"encoding/json"
	"fmt"

	authctx "github.com/elebirds/saki/saki-controlplane/internal/app/auth"
	openapi "github.com/elebirds/saki/saki-controlplane/internal/gen/openapi"
	accessapp "github.com/elebirds/saki/saki-controlplane/internal/modules/access/app"
	systemapp "github.com/elebirds/saki/saki-controlplane/internal/modules/system/app"
	ogenhttp "github.com/ogen-go/ogen/http"
)

type StatusExecutor interface {
	Execute(ctx context.Context) (*systemapp.Status, error)
}

type TypesExecutor interface {
	Execute(ctx context.Context) (*systemapp.TypesCatalog, error)
}

type SetupExecutor interface {
	Execute(ctx context.Context, cmd systemapp.SetupCommand) (*systemapp.AuthSession, error)
}

type SettingsManager interface {
	GetBundle(ctx context.Context) (*systemapp.SettingsBundle, error)
	Patch(ctx context.Context, values map[string]json.RawMessage) (*systemapp.SettingsBundle, error)
}

type HandlersDeps struct {
	Status   StatusExecutor
	Types    TypesExecutor
	Setup    SetupExecutor
	Settings SettingsManager
}

type Handlers struct {
	status   StatusExecutor
	types    TypesExecutor
	setup    SetupExecutor
	settings SettingsManager
}

func NewHandlers(deps HandlersDeps) *Handlers {
	return &Handlers{
		status:   deps.Status,
		types:    deps.Types,
		setup:    deps.Setup,
		settings: deps.Settings,
	}
}

func (h *Handlers) GetSystemStatus(ctx context.Context) (*openapi.SystemStatusResponse, error) {
	if h == nil || h.status == nil {
		return nil, ogenhttp.ErrNotImplemented
	}
	status, err := h.status.Execute(ctx)
	if err != nil {
		return nil, err
	}
	return &openapi.SystemStatusResponse{
		InstallState:      string(status.InstallState),
		AllowSelfRegister: status.AllowSelfRegister,
		Version:           status.Version,
	}, nil
}

func (h *Handlers) GetSystemTypes(ctx context.Context) (*openapi.SystemTypesResponse, error) {
	if h == nil || h.types == nil {
		return nil, ogenhttp.ErrNotImplemented
	}
	catalog, err := h.types.Execute(ctx)
	if err != nil {
		return nil, err
	}

	response := &openapi.SystemTypesResponse{
		TaskTypes:    make([]openapi.SystemTypeInfo, 0, len(catalog.TaskTypes)),
		DatasetTypes: make([]openapi.SystemTypeInfo, 0, len(catalog.DatasetTypes)),
	}
	for _, item := range catalog.TaskTypes {
		response.TaskTypes = append(response.TaskTypes, mapTypeInfo(item))
	}
	for _, item := range catalog.DatasetTypes {
		response.DatasetTypes = append(response.DatasetTypes, mapTypeInfo(item))
	}
	return response, nil
}

func (h *Handlers) SetupSystem(ctx context.Context, req *openapi.SystemSetupRequest) (*openapi.AuthSessionResponse, error) {
	if h == nil || h.setup == nil {
		return nil, ogenhttp.ErrNotImplemented
	}
	session, err := h.setup.Execute(ctx, systemapp.SetupCommand{
		Email:    req.GetEmail(),
		Password: req.GetPassword(),
		FullName: req.GetFullName(),
	})
	if err != nil {
		return nil, err
	}
	return &openapi.AuthSessionResponse{
		AccessToken:        session.AccessToken,
		RefreshToken:       session.RefreshToken,
		ExpiresIn:          session.ExpiresIn,
		MustChangePassword: session.MustChangePassword,
		User: openapi.AuthSessionUser{
			PrincipalID: session.User.PrincipalID.String(),
			Email:       session.User.Email,
			FullName:    session.User.FullName,
		},
	}, nil
}

func (h *Handlers) GetSystemSettings(ctx context.Context) (*openapi.SystemSettingsResponse, error) {
	if h == nil || h.settings == nil {
		return nil, ogenhttp.ErrNotImplemented
	}
	if _, err := requireAnyPermission(ctx, "system:read"); err != nil {
		return nil, err
	}

	bundle, err := h.settings.GetBundle(ctx)
	if err != nil {
		return nil, err
	}
	return mapSettingsBundle(bundle)
}

func (h *Handlers) PatchSystemSettings(ctx context.Context, req *openapi.SystemSettingsPatchRequest) (*openapi.SystemSettingsResponse, error) {
	if h == nil || h.settings == nil {
		return nil, ogenhttp.ErrNotImplemented
	}
	if _, err := requireAnyPermission(ctx, "system:write"); err != nil {
		return nil, err
	}

	values := make(map[string]json.RawMessage, len(req.Values))
	for key, value := range req.Values {
		definition, ok := systemapp.FindSettingDefinition(key)
		if !ok {
			return nil, fmt.Errorf("%w: unknown key %s", systemapp.ErrInvalidSettingValue, key)
		}
		raw, err := openAPISettingValueToRaw(value, definition.Type)
		if err != nil {
			return nil, err
		}
		values[key] = raw
	}

	bundle, err := h.settings.Patch(ctx, values)
	if err != nil {
		return nil, err
	}
	return mapSettingsBundle(bundle)
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

func requireAnyPermission(ctx context.Context, permissions ...string) (*accessapp.Claims, error) {
	claims, ok := authctx.ClaimsFromContext(ctx)
	if !ok {
		return nil, accessapp.ErrUnauthorized
	}

	// 关键设计：运行时权限校验只接受 canonical permission。
	// 旧权限别名的适配通过离线数据库迁移完成，而不是继续保留在服务端分支判断里。
	for _, permission := range permissions {
		if claims.HasPermission(permission) {
			return claims, nil
		}
	}
	return nil, accessapp.ErrForbidden
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
