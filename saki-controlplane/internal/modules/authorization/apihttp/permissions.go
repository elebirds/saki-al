package apihttp

import (
	"context"
	"slices"

	authctx "github.com/elebirds/saki/saki-controlplane/internal/app/auth"
	accessapp "github.com/elebirds/saki/saki-controlplane/internal/modules/access/app"
	authorizationapp "github.com/elebirds/saki/saki-controlplane/internal/modules/authorization/app"
	"github.com/google/uuid"
	ogenhttp "github.com/ogen-go/ogen/http"
)

func requireAnyPermission(ctx context.Context, permissions ...string) (*accessapp.Claims, error) {
	claims, ok := authctx.ClaimsFromContext(ctx)
	if !ok {
		return nil, accessapp.ErrUnauthorized
	}
	if len(permissions) == 0 {
		return claims, nil
	}
	for _, permission := range permissions {
		if slices.Contains(claims.Permissions, permission) {
			return claims, nil
		}
	}
	return nil, accessapp.ErrForbidden
}

func requireRoleReplacementPermission(ctx context.Context) (*accessapp.Claims, error) {
	// 关键设计：system role 绑定写权限已经收敛到 canonical permission `roles:write`，
	// 不再接受历史拆分别名，避免同一动作还留着旁路。
	return requireAnyPermission(ctx, "roles:write")
}

func (h *Handlers) requireResourcePermission(ctx context.Context, resourceType string, rawResourceID string, permissions ...string) (uuid.UUID, error) {
	claims, ok := authctx.ClaimsFromContext(ctx)
	if !ok {
		return uuid.Nil, accessapp.ErrUnauthorized
	}
	if h == nil || h.resolveResourceAccess == nil {
		return uuid.Nil, ogenhttp.ErrNotImplemented
	}

	resourceID, err := uuid.Parse(rawResourceID)
	if err != nil {
		return uuid.Nil, authorizationapp.ErrInvalidResourceInput
	}

	effective, err := h.resolveResourceAccess.Execute(ctx, claims.PrincipalID, resourceType, resourceID)
	if err != nil {
		return uuid.Nil, err
	}
	// 关键设计：空权限集合表示“只校验资源参数合法，并允许读取当前主体的能力快照”。
	// `/auth/resource-permissions` 需要在无权限时返回空快照，而不是提前在 transport 层拦成 403。
	if len(permissions) == 0 {
		return resourceID, nil
	}
	for _, permission := range permissions {
		if slices.Contains(effective, permission) {
			return resourceID, nil
		}
	}
	return uuid.Nil, accessapp.ErrForbidden
}

func parseMembershipIDs(rawResourceID string, rawPrincipalID string, rawRoleID string) (resourceID uuid.UUID, principalID uuid.UUID, roleID uuid.UUID, err error) {
	resourceID, err = uuid.Parse(rawResourceID)
	if err != nil {
		return uuid.Nil, uuid.Nil, uuid.Nil, authorizationapp.ErrInvalidResourceInput
	}
	principalID, err = uuid.Parse(rawPrincipalID)
	if err != nil {
		return uuid.Nil, uuid.Nil, uuid.Nil, authorizationapp.ErrInvalidResourceInput
	}
	if rawRoleID == "" {
		return resourceID, principalID, uuid.Nil, nil
	}
	roleID, err = uuid.Parse(rawRoleID)
	if err != nil {
		return uuid.Nil, uuid.Nil, uuid.Nil, authorizationapp.ErrInvalidResourceInput
	}
	return resourceID, principalID, roleID, nil
}
