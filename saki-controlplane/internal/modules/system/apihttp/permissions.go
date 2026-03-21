package apihttp

import (
	"context"

	authctx "github.com/elebirds/saki/saki-controlplane/internal/app/auth"
	accessapp "github.com/elebirds/saki/saki-controlplane/internal/modules/access/app"
)

func requireAnyPermission(ctx context.Context, permissions ...string) (*accessapp.Claims, error) {
	claims, ok := authctx.ClaimsFromContext(ctx)
	if !ok {
		return nil, accessapp.ErrUnauthorized
	}

	// 关键设计：运行时权限校验只接受 canonical permission，
	// 旧权限别名的兼容通过数据库迁移收口，而不是继续放在在线分支里兜底。
	for _, permission := range permissions {
		if claims.HasPermission(permission) {
			return claims, nil
		}
	}
	return nil, accessapp.ErrForbidden
}
