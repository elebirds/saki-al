package repo

import (
	"context"
	"encoding/json"
	"errors"

	appdb "github.com/elebirds/saki/saki-controlplane/internal/app/db"
	sqlcdb "github.com/elebirds/saki/saki-controlplane/internal/gen/sqlc"
	authorizationdomain "github.com/elebirds/saki/saki-controlplane/internal/modules/authorization/domain"
	identityapp "github.com/elebirds/saki/saki-controlplane/internal/modules/identity/app"
	identitydomain "github.com/elebirds/saki/saki-controlplane/internal/modules/identity/domain"
	systemapp "github.com/elebirds/saki/saki-controlplane/internal/modules/system/app"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgtype"
	"github.com/jackc/pgx/v5/pgxpool"
)

type AuthStore struct {
	q  *sqlcdb.Queries
	tx *appdb.TxRunner
}

func NewAuthStore(pool *pgxpool.Pool) *AuthStore {
	return &AuthStore{
		q:  sqlcdb.New(pool),
		tx: appdb.NewTxRunner(pool),
	}
}

var _ identityapp.LoginAccountStore = (*AuthStore)(nil)
var _ identityapp.RefreshAccountStore = (*AuthStore)(nil)
var _ identityapp.ChangePasswordStore = (*AuthStore)(nil)
var _ identityapp.CurrentUserStore = (*AuthStore)(nil)
var _ identityapp.RegisterStore = (*AuthStore)(nil)

func (r *AuthStore) FindAccountByIdentifier(ctx context.Context, identifier string) (*identityapp.AuthAccount, error) {
	user, err := r.q.GetIamUserByIdentifier(ctx, identifier)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return nil, nil
		}
		return nil, err
	}
	return r.loadAccountByPrincipalID(ctx, user.PrincipalID)
}

func (r *AuthStore) FindAccountByPrincipalID(ctx context.Context, principalID uuid.UUID) (*identityapp.AuthAccount, error) {
	return r.loadAccountByPrincipalID(ctx, principalID)
}

func (r *AuthStore) ChangePassword(ctx context.Context, params identityapp.ChangePasswordParams) (*identityapp.PasswordMutationResult, error) {
	var result *identityapp.PasswordMutationResult
	err := r.tx.InTx(ctx, func(tx pgx.Tx) error {
		q := sqlcdb.New(tx)

		if _, err := q.UpsertIamPasswordCredential(ctx, sqlcdb.UpsertIamPasswordCredentialParams{
			PrincipalID:        params.PrincipalID,
			Scheme:             identitydomain.PasswordSchemeArgon2id,
			PasswordHash:       params.NewPasswordHash,
			MustChangePassword: false,
			PasswordChangedAt:  timeValue(params.ChangedAt),
		}); err != nil {
			return err
		}
		if err := q.DeleteIamPasswordCredentialsByPrincipalExcludingScheme(ctx, sqlcdb.DeleteIamPasswordCredentialsByPrincipalExcludingSchemeParams{
			PrincipalID: params.PrincipalID,
			Scheme:      identitydomain.PasswordSchemeArgon2id,
		}); err != nil {
			return err
		}
		if err := q.RevokeIamRefreshSessionsByPrincipal(ctx, sqlcdb.RevokeIamRefreshSessionsByPrincipalParams{
			Now:         timeValue(params.ChangedAt),
			PrincipalID: params.PrincipalID,
		}); err != nil {
			return err
		}
		if _, err := q.CreateIamRefreshSession(ctx, sqlcdb.CreateIamRefreshSessionParams{
			PrincipalID: params.PrincipalID,
			FamilyID:    uuid.New(),
			TokenHash:   params.RefreshTokenHash,
			UserAgent:   textValue(params.UserAgent),
			IpAddress:   cloneRepoAddr(params.IPAddress),
			LastSeenAt:  timeValue(params.ChangedAt),
			ExpiresAt:   timeValue(params.RefreshExpiresAt),
		}); err != nil {
			return err
		}

		user, err := q.GetIamUserByPrincipalID(ctx, params.PrincipalID)
		if err != nil {
			return err
		}
		result = &identityapp.PasswordMutationResult{User: *mapUser(user)}
		return nil
	})
	if err != nil {
		return nil, err
	}
	return result, nil
}

func (r *AuthStore) ListSystemRoleNamesByPrincipal(ctx context.Context, principalID uuid.UUID) ([]string, error) {
	return r.q.ListAuthzSystemRoleNamesByPrincipal(ctx, principalID)
}

func (r *AuthStore) Register(ctx context.Context, params identityapp.RegisterParams) (*identityapp.RegisterResult, error) {
	var result *identityapp.RegisterResult
	err := r.tx.InTx(ctx, func(tx pgx.Tx) error {
		q := sqlcdb.New(tx)

		installation, err := q.GetSystemInstallation(ctx)
		if err != nil {
			if errors.Is(err, pgx.ErrNoRows) {
				return systemapp.ErrNotInitialized
			}
			return err
		}
		if installation.InitializationState != sqlcdb.SystemInitializationStateInitialized {
			return systemapp.ErrNotInitialized
		}

		setting, err := q.GetSystemSettingByKey(ctx, sqlcdb.GetSystemSettingByKeyParams{
			InstallationID: installation.ID,
			Key:            systemapp.SettingKeyAuthAllowSelfRegister,
		})
		if err != nil {
			if errors.Is(err, pgx.ErrNoRows) {
				return identityapp.ErrSelfRegistrationDisabled
			}
			return err
		}
		var allowSelfRegister bool
		if err := json.Unmarshal(setting.Value, &allowSelfRegister); err != nil {
			return err
		}
		if !allowSelfRegister {
			return identityapp.ErrSelfRegistrationDisabled
		}

		roleID, err := ensureRegisteredUserRole(ctx, q)
		if err != nil {
			return err
		}

		principal, err := q.CreateIamPrincipal(ctx, sqlcdb.CreateIamPrincipalParams{
			Kind:        sqlcdb.IamPrincipalKindHumanUser,
			DisplayName: params.FullName,
		})
		if err != nil {
			return err
		}
		user, err := q.CreateIamUser(ctx, sqlcdb.CreateIamUserParams{
			PrincipalID: principal.ID,
			Email:       params.Email,
			FullName:    textValue(params.FullName),
		})
		if err != nil {
			return err
		}
		if _, err := q.UpsertIamPasswordCredential(ctx, sqlcdb.UpsertIamPasswordCredentialParams{
			PrincipalID:        principal.ID,
			Scheme:             identitydomain.PasswordSchemeArgon2id,
			PasswordHash:       params.PasswordHash,
			MustChangePassword: false,
			PasswordChangedAt:  timeValue(params.RegisteredAt),
		}); err != nil {
			return err
		}
		if _, err := q.UpsertAuthzSystemBinding(ctx, sqlcdb.UpsertAuthzSystemBindingParams{
			PrincipalID: principal.ID,
			RoleID:      roleID,
			SystemName:  "primary",
		}); err != nil {
			return err
		}
		if _, err := q.CreateIamRefreshSession(ctx, sqlcdb.CreateIamRefreshSessionParams{
			PrincipalID: principal.ID,
			FamilyID:    uuid.New(),
			TokenHash:   params.RefreshTokenHash,
			UserAgent:   textValue(params.UserAgent),
			IpAddress:   cloneRepoAddr(params.IPAddress),
			LastSeenAt:  timeValue(params.RegisteredAt),
			ExpiresAt:   timeValue(params.RefreshExpiresAt),
		}); err != nil {
			return err
		}
		result = &identityapp.RegisterResult{User: *mapUser(user)}
		return nil
	})
	if err != nil {
		return nil, err
	}
	return result, nil
}

func (r *AuthStore) loadAccountByPrincipalID(ctx context.Context, principalID uuid.UUID) (*identityapp.AuthAccount, error) {
	principal, err := r.q.GetIamPrincipalByID(ctx, principalID)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return nil, nil
		}
		return nil, err
	}
	user, err := r.q.GetIamUserByPrincipalID(ctx, principalID)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return nil, nil
		}
		return nil, err
	}
	credentials, err := r.q.GetIamPasswordCredentialByPrincipal(ctx, principalID)
	if err != nil {
		return nil, err
	}

	account := &identityapp.AuthAccount{
		Principal:   *mapPrincipal(principal),
		User:        *mapUser(user),
		Credentials: make([]identitydomain.PasswordCredential, 0, len(credentials)),
	}
	for _, credential := range credentials {
		account.Credentials = append(account.Credentials, *mapCredential(credential))
	}
	return account, nil
}

func ensureRegisteredUserRole(ctx context.Context, q *sqlcdb.Queries) (uuid.UUID, error) {
	role, err := q.GetAuthzRoleByName(ctx, identityapp.BuiltinRoleRegisteredUser)
	switch {
	case err == nil:
	case !errors.Is(err, pgx.ErrNoRows):
		return uuid.Nil, err
	case errors.Is(err, pgx.ErrNoRows):
		// 关键设计：自助注册默认绑定一个零权限内建角色，而不是直接授予业务权限。
		// 这样 register 流程可以保持“有主体、有会话、可继续扩展成员关系”，同时避免把默认权限散落进 handler。
		created, err := q.CreateAuthzRole(ctx, sqlcdb.CreateAuthzRoleParams{
			ScopeKind:   string(authorizationdomain.RoleScopeSystem),
			Name:        identityapp.BuiltinRoleRegisteredUser,
			DisplayName: "Registered User",
			Description: pgtype.Text{String: "Builtin zero-permission role for self-registered human users.", Valid: true},
			BuiltIn:     true,
			Mutable:     false,
			Color:       "blue",
			IsSupremo:   false,
			SortOrder:   100,
		})
		if err != nil {
			return uuid.Nil, err
		}
		role = created
	}
	role, err = q.UpdateAuthzRoleMetadata(ctx, sqlcdb.UpdateAuthzRoleMetadataParams{
		ID:          role.ID,
		ScopeKind:   string(authorizationdomain.RoleScopeSystem),
		DisplayName: "Registered User",
		Description: pgtype.Text{String: "Builtin zero-permission role for self-registered human users.", Valid: true},
		BuiltIn:     true,
		Mutable:     false,
		Color:       "blue",
		IsSupremo:   false,
		SortOrder:   100,
	})
	if err != nil {
		return uuid.Nil, err
	}
	return role.ID, nil
}
