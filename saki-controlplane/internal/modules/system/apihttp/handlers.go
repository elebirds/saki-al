package apihttp

import (
	"context"
	"encoding/json"
	"fmt"

	openapi "github.com/elebirds/saki/saki-controlplane/internal/gen/openapi"
	systemapp "github.com/elebirds/saki/saki-controlplane/internal/modules/system/app"
	ogenhttp "github.com/ogen-go/ogen/http"
)

type StatusExecutor interface {
	Execute(ctx context.Context) (*systemapp.Status, error)
}

type TypesExecutor interface {
	Execute(ctx context.Context) (*systemapp.TypesCatalog, error)
}

type InitializeSystemExecutor interface {
	Execute(ctx context.Context, cmd systemapp.InitializeSystemCommand) (*systemapp.AuthSession, error)
}

type SettingsManager interface {
	GetBundle(ctx context.Context) (*systemapp.SettingsBundle, error)
	Patch(ctx context.Context, values map[string]json.RawMessage) (*systemapp.SettingsBundle, error)
}

type HandlersDeps struct {
	Status     StatusExecutor
	Types      TypesExecutor
	Initialize InitializeSystemExecutor
	Settings   SettingsManager
}

type Handlers struct {
	status     StatusExecutor
	types      TypesExecutor
	initialize InitializeSystemExecutor
	settings   SettingsManager
}

func NewHandlers(deps HandlersDeps) *Handlers {
	return &Handlers{
		status:     deps.Status,
		types:      deps.Types,
		initialize: deps.Initialize,
		settings:   deps.Settings,
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
		InitializationState: mapInitializationState(status.InitializationState),
		AllowSelfRegister:   status.AllowSelfRegister,
		Version:             status.Version,
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

func (h *Handlers) InitializeSystem(ctx context.Context, req *openapi.SystemInitRequest) (*openapi.AuthSessionResponse, error) {
	if h == nil || h.initialize == nil {
		return nil, ogenhttp.ErrNotImplemented
	}
	session, err := h.initialize.Execute(ctx, systemapp.InitializeSystemCommand{
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
