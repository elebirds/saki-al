package sqlcdb

import (
	"context"

	"github.com/google/uuid"
)

// 兼容层：保留早期 smoke test 里使用的大写 IAM 命名，避免在快速开发期因为 sqlc 命名细节变动而打断契约测试。
// 新代码一律直接使用当前生成的 Iam 形式，兼容方法只服务于迁移中的测试与静态符号占位。

type CreateIAMPrincipalParams = CreateIamPrincipalParams
type CreateIAMUserParams = CreateIamUserParams
type UpsertIAMPasswordCredentialParams = UpsertIamPasswordCredentialParams
type CreateIAMRefreshSessionParams = CreateIamRefreshSessionParams
type AddAuthzSystemBindingParams = UpsertAuthzSystemBindingParams

func (q *Queries) CreateIAMPrincipal(ctx context.Context, arg CreateIAMPrincipalParams) (IamPrincipal, error) {
	return q.CreateIamPrincipal(ctx, arg)
}

func (q *Queries) GetIAMPrincipalByID(ctx context.Context, id uuid.UUID) (IamPrincipal, error) {
	return q.GetIamPrincipalByID(ctx, id)
}

func (q *Queries) CreateIAMUser(ctx context.Context, arg CreateIAMUserParams) (IamUser, error) {
	return q.CreateIamUser(ctx, arg)
}

func (q *Queries) GetIAMUserByEmail(ctx context.Context, email string) (IamUser, error) {
	return q.GetIamUserByEmail(ctx, email)
}

func (q *Queries) UpsertIAMPasswordCredential(ctx context.Context, arg UpsertIAMPasswordCredentialParams) (IamPasswordCredential, error) {
	return q.UpsertIamPasswordCredential(ctx, arg)
}

func (q *Queries) CreateIAMRefreshSession(ctx context.Context, arg CreateIAMRefreshSessionParams) (IamRefreshSession, error) {
	return q.CreateIamRefreshSession(ctx, arg)
}

func (q *Queries) GetIAMRefreshSessionByTokenHash(ctx context.Context, tokenHash string) (IamRefreshSession, error) {
	return q.GetIamRefreshSessionByTokenHash(ctx, tokenHash)
}

func (q *Queries) AddAuthzSystemBinding(ctx context.Context, arg AddAuthzSystemBindingParams) (AuthzSystemBinding, error) {
	return q.UpsertAuthzSystemBinding(ctx, arg)
}
