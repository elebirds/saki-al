package repo

import (
	"context"
	"errors"
	"net/netip"
	"time"

	appdb "github.com/elebirds/saki/saki-controlplane/internal/app/db"
	sqlcdb "github.com/elebirds/saki/saki-controlplane/internal/gen/sqlc"
	authorizationdomain "github.com/elebirds/saki/saki-controlplane/internal/modules/authorization/domain"
	identitydomain "github.com/elebirds/saki/saki-controlplane/internal/modules/identity/domain"
	systemapp "github.com/elebirds/saki/saki-controlplane/internal/modules/system/app"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgtype"
	"github.com/jackc/pgx/v5/pgxpool"
)

type InitializeStore struct {
	tx *appdb.TxRunner
}

var _ systemapp.InitializeSystemStore = (*InitializeStore)(nil)

func NewInitializeStore(pool *pgxpool.Pool) *InitializeStore {
	return &InitializeStore{tx: appdb.NewTxRunner(pool)}
}

func (r *InitializeStore) InitializeSystem(ctx context.Context, params systemapp.InitializeSystemParams) (*systemapp.InitializeSystemResult, error) {
	var result *systemapp.InitializeSystemResult
	err := r.tx.InTx(ctx, func(tx pgx.Tx) error {
		q := sqlcdb.New(tx)

		installState, err := lockInstallationSlot(ctx, tx)
		switch {
		case err != nil:
			return err
		case installState == sqlcdb.SystemInstallationStateReady:
			return systemapp.ErrAlreadyInitialized
		}

		roleID, err := ensureSuperAdminRole(ctx, q)
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
			Username:    pgtype.Text{},
			FullName:    textValue(params.FullName),
		})
		if err != nil {
			return err
		}

		if _, err := q.CreateIamPasswordCredential(ctx, sqlcdb.CreateIamPasswordCredentialParams{
			PrincipalID:  principal.ID,
			Scheme:       identitydomain.PasswordSchemeArgon2id,
			PasswordHash: params.PasswordHash,
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

		installation, err := q.UpsertSystemInstallation(ctx, sqlcdb.UpsertSystemInstallationParams{
			InstallState:       sqlcdb.SystemInstallationStateReady,
			Metadata:           []byte(`{}`),
			SetupAt:            timeValue(params.InitializedAt),
			SetupByPrincipalID: uuidValue(principal.ID),
		})
		if err != nil {
			return err
		}

		// 关键设计：初始化结束时必须把 system setting 默认值显式落库，
		// 后续 status/settings/import 等读路径才能统一基于 installation + setting 真值，而不是回退到多套散落默认值。
		for _, definition := range systemapp.ListSettingDefinitions() {
			if _, err := q.UpsertSystemSetting(ctx, sqlcdb.UpsertSystemSettingParams{
				InstallationID: installation.ID,
				Key:            definition.Key,
				Value:          append([]byte(nil), definition.Default...),
			}); err != nil {
				return err
			}
		}

		if _, err := q.CreateIamRefreshSession(ctx, sqlcdb.CreateIamRefreshSessionParams{
			PrincipalID: principal.ID,
			FamilyID:    uuid.New(),
			TokenHash:   params.RefreshTokenHash,
			UserAgent:   textValue(params.UserAgent),
			IpAddress:   cloneAddr(params.IPAddress),
			LastSeenAt:  timeValue(params.InitializedAt),
			ExpiresAt:   timeValue(params.RefreshExpiresAt),
		}); err != nil {
			return err
		}

		result = &systemapp.InitializeSystemResult{
			PrincipalID: principal.ID,
			Email:       user.Email,
			FullName:    user.FullName.String,
		}
		return nil
	})
	if err != nil {
		return nil, err
	}
	return result, nil
}

func lockInstallationSlot(ctx context.Context, tx pgx.Tx) (sqlcdb.SystemInstallationState, error) {
	// 关键设计：初始化必须先抢到 installation singleton 的事务锁，再创建首个用户与会话。
	// 否则两个并发首装请求都可能先看到“未初始化”，随后各自创建出不同的管理员主体。
	if _, err := tx.Exec(ctx, `
insert into system_installation (installation_key, install_state, metadata)
values ('primary', 'uninitialized', '{}'::jsonb)
on conflict (installation_key) do nothing
`); err != nil {
		return "", err
	}

	var installState sqlcdb.SystemInstallationState
	if err := tx.QueryRow(ctx, `
select install_state
from system_installation
where installation_key = 'primary'
for update
`).Scan(&installState); err != nil {
		return "", err
	}
	return installState, nil
}

func ensureSuperAdminRole(ctx context.Context, q *sqlcdb.Queries) (uuid.UUID, error) {
	role, err := q.GetAuthzRoleByName(ctx, systemapp.BuiltinRoleSuperAdmin)
	switch {
	case err == nil:
	case errors.Is(err, pgx.ErrNoRows):
		role, err = q.CreateAuthzRole(ctx, sqlcdb.CreateAuthzRoleParams{
			ScopeKind:   string(authorizationdomain.RoleScopeSystem),
			Name:        systemapp.BuiltinRoleSuperAdmin,
			DisplayName: "Super Admin",
			Description: textValue("Builtin super admin role with full control over the human control plane."),
			BuiltIn:     true,
			Mutable:     false,
			Color:       "red",
			IsSupremo:   true,
			SortOrder:   0,
		})
		if err != nil {
			return uuid.UUID{}, err
		}
	default:
		return uuid.UUID{}, err
	}
	role, err = q.UpdateAuthzRoleMetadata(ctx, sqlcdb.UpdateAuthzRoleMetadataParams{
		ID:          role.ID,
		ScopeKind:   string(authorizationdomain.RoleScopeSystem),
		DisplayName: "Super Admin",
		Description: textValue("Builtin super admin role with full control over the human control plane."),
		BuiltIn:     true,
		Mutable:     false,
		Color:       "red",
		IsSupremo:   true,
		SortOrder:   0,
	})
	if err != nil {
		return uuid.UUID{}, err
	}

	for _, permission := range authorizationdomain.KnownPermissions() {
		if err := q.AddAuthzRolePermission(ctx, sqlcdb.AddAuthzRolePermissionParams{
			RoleID:     role.ID,
			Permission: permission,
		}); err != nil {
			return uuid.UUID{}, err
		}
	}
	return role.ID, nil
}

func textValue(value string) pgtype.Text {
	if value == "" {
		return pgtype.Text{}
	}
	return pgtype.Text{String: value, Valid: true}
}

func timeValue(value time.Time) pgtype.Timestamptz {
	if value.IsZero() {
		return pgtype.Timestamptz{}
	}
	return pgtype.Timestamptz{Time: value.UTC(), Valid: true}
}

func uuidValue(value uuid.UUID) pgtype.UUID {
	return pgtype.UUID{Bytes: value, Valid: true}
}

func cloneAddr(value *netip.Addr) *netip.Addr {
	if value == nil {
		return nil
	}
	copy := *value
	return &copy
}
