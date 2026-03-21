package apihttp

import (
	"context"
	"slices"

	authctx "github.com/elebirds/saki/saki-controlplane/internal/app/auth"
	accessapp "github.com/elebirds/saki/saki-controlplane/internal/modules/access/app"
)

func requireAnyPermission(ctx context.Context, permissions ...string) (*accessapp.Claims, error) {
	claims, ok := authctx.ClaimsFromContext(ctx)
	if !ok {
		return nil, accessapp.ErrUnauthorized
	}
	for _, permission := range permissions {
		if slices.Contains(claims.Permissions, permission) {
			return claims, nil
		}
	}
	return nil, accessapp.ErrForbidden
}
