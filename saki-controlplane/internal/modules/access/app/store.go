package app

import (
	"context"

	accessdomain "github.com/elebirds/saki/saki-controlplane/internal/modules/access/domain"
	"github.com/google/uuid"
)

type BootstrapPrincipalSpec struct {
	UserID      string
	DisplayName string
	Permissions []string
}

type ClaimsSnapshot struct {
	PrincipalID uuid.UUID
	UserID      string
	Permissions []string
}

// access 是迁移期 HTTP auth 外壳，正式的人类控制面身份与授权能力已经迁入 identity/authorization。
// 这里的 claims 装载只负责把上游聚合结果搬进 token / middleware，不再在 access 内部自行拼权限。
type ClaimsStore interface {
	LoadClaimsByUserID(ctx context.Context, userID string) (*ClaimsSnapshot, error)
	LoadClaimsByPrincipalID(ctx context.Context, principalID uuid.UUID) (*ClaimsSnapshot, error)
}

type BootstrapStore interface {
	UpsertBootstrapPrincipal(ctx context.Context, spec BootstrapPrincipalSpec) (*accessdomain.Principal, error)
}

type Store interface {
	ClaimsStore
	BootstrapStore
}
