package apihttp

import (
	"context"

	authctx "github.com/elebirds/saki/saki-controlplane/internal/app/auth"
	openapi "github.com/elebirds/saki/saki-controlplane/internal/gen/openapi"
	accessapp "github.com/elebirds/saki/saki-controlplane/internal/modules/access/app"
)

type Handlers struct {
	authenticator *accessapp.Authenticator
}

func NewHandlers(authenticator *accessapp.Authenticator) *Handlers {
	return &Handlers{authenticator: authenticator}
}

func (h *Handlers) RequirePermission(ctx context.Context, params openapi.RequirePermissionParams) error {
	claims, ok := authctx.ClaimsFromContext(ctx)
	if !ok {
		return accessapp.ErrUnauthorized
	}
	if !claims.HasPermission(params.Permission) {
		return accessapp.ErrForbidden
	}
	return nil
}
