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

func (h *Handlers) Login(_ context.Context, req *openapi.LoginRequest) (*openapi.AuthTokenResponse, error) {
	token, err := h.authenticator.IssueToken(req.GetUserID(), req.GetPermissions())
	if err != nil {
		return nil, err
	}

	return &openapi.AuthTokenResponse{
		Token:       token,
		UserID:      req.GetUserID(),
		Permissions: req.GetPermissions(),
	}, nil
}

func (h *Handlers) GetCurrentUser(ctx context.Context) (*openapi.CurrentUserResponse, error) {
	claims, ok := authctx.ClaimsFromContext(ctx)
	if !ok {
		return nil, accessapp.ErrUnauthorized
	}

	return &openapi.CurrentUserResponse{
		UserID:      claims.UserID,
		Permissions: claims.Permissions,
	}, nil
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
