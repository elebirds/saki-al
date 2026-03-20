package repo

import (
	"context"
	"errors"
	"fmt"

	appdb "github.com/elebirds/saki/saki-controlplane/internal/app/db"
	sqlcdb "github.com/elebirds/saki/saki-controlplane/internal/gen/sqlc"
	authorizationapp "github.com/elebirds/saki/saki-controlplane/internal/modules/authorization/app"
	identityapp "github.com/elebirds/saki/saki-controlplane/internal/modules/identity/app"
	identitydomain "github.com/elebirds/saki/saki-controlplane/internal/modules/identity/domain"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
	"github.com/jackc/pgx/v5/pgtype"
	"github.com/jackc/pgx/v5/pgxpool"
)

const iamUserEmailUniqueConstraint = "iam_user_email_unique"
const builtinSuperAdminRoleName = "super_admin"

type AdminStore struct {
	q  *sqlcdb.Queries
	tx *appdb.TxRunner
}

func NewAdminStore(pool *pgxpool.Pool) *AdminStore {
	return &AdminStore{
		q:  sqlcdb.New(pool),
		tx: appdb.NewTxRunner(pool),
	}
}

var _ identityapp.AdminUserRecordStore = (*AdminStore)(nil)
var _ identityapp.AdminUserMutationStore = (*AdminStore)(nil)

func (r *AdminStore) GetAdminUserRecord(ctx context.Context, principalID uuid.UUID) (*identitydomain.AdminUserRecord, error) {
	record, err := r.loadAdminUserRecord(ctx, r.q, principalID)
	if err != nil {
		return nil, err
	}
	return record, nil
}

func (r *AdminStore) CreateAdminUser(ctx context.Context, params identityapp.CreateAdminUserParams) (*identitydomain.AdminUserRecord, error) {
	var result *identitydomain.AdminUserRecord
	err := r.tx.InTx(ctx, func(tx pgx.Tx) error {
		q := sqlcdb.New(tx)

		displayName := params.Email
		if params.FullName != nil {
			displayName = *params.FullName
		}

		principal, err := q.CreateIamPrincipal(ctx, sqlcdb.CreateIamPrincipalParams{
			Kind:        sqlcdb.IamPrincipalKindHumanUser,
			DisplayName: displayName,
		})
		if err != nil {
			return err
		}

		if _, err := q.CreateIamUser(ctx, sqlcdb.CreateIamUserParams{
			PrincipalID: principal.ID,
			Email:       params.Email,
			Username:    pgtype.Text{},
			FullName:    toText(params.FullName),
		}); err != nil {
			if isConstraintViolation(err, iamUserEmailUniqueConstraint) {
				return identityapp.ErrUserAlreadyExists
			}
			return err
		}

		if _, err := q.UpsertIamPasswordCredential(ctx, sqlcdb.UpsertIamPasswordCredentialParams{
			PrincipalID:        principal.ID,
			Scheme:             identitydomain.PasswordSchemeArgon2id,
			PasswordHash:       params.PasswordHash,
			MustChangePassword: params.MustChangePassword,
			PasswordChangedAt:  timeValue(params.Now),
		}); err != nil {
			return err
		}

		if !params.IsActive {
			if err := q.UpdateIamPrincipalStatus(ctx, sqlcdb.UpdateIamPrincipalStatusParams{
				ID:     principal.ID,
				Status: sqlcdb.IamPrincipalStatus(identitydomain.PrincipalStatusDisabled),
			}); err != nil {
				return err
			}
			if err := q.UpdateIamUserState(ctx, sqlcdb.UpdateIamUserStateParams{
				PrincipalID: principal.ID,
				State:       sqlcdb.IamUserState(identitydomain.UserStateDisabled),
			}); err != nil {
				return err
			}
		}

		record, err := r.loadAdminUserRecord(ctx, q, principal.ID)
		if err != nil {
			return err
		}
		result = record
		return nil
	})
	if err != nil {
		return nil, err
	}
	return result, nil
}

func (r *AdminStore) UpdateAdminUser(ctx context.Context, params identityapp.UpdateAdminUserParams) (*identitydomain.AdminUserRecord, error) {
	var result *identitydomain.AdminUserRecord
	err := r.tx.InTx(ctx, func(tx pgx.Tx) error {
		q := sqlcdb.New(tx)

		record, err := r.loadAdminUserRecord(ctx, q, params.PrincipalID)
		if err != nil {
			return err
		}
		if record == nil || record.User.State == identitydomain.UserStateDeleted {
			return identityapp.ErrUserNotFound
		}

		fullName := record.User.FullName
		if params.ChangeFullName {
			fullName = params.FullName
		}

		if err := q.UpdateIamUserProfile(ctx, sqlcdb.UpdateIamUserProfileParams{
			PrincipalID:   params.PrincipalID,
			Email:         record.User.Email,
			Username:      toText(record.User.Username),
			FullName:      toText(fullName),
			AvatarAssetID: toUUID(record.User.AvatarAssetID),
		}); err != nil {
			return err
		}

		revokeSessions := false
		if params.IsActive != nil {
			if !*params.IsActive {
				protected, err := r.rejectLastSuperAdminDisable(ctx, q, params.PrincipalID)
				if err != nil {
					return err
				}
				if protected {
					return authorizationapp.ErrLastSuperAdmin
				}
			}
			userState := identitydomain.UserStateActive
			principalStatus := identitydomain.PrincipalStatusActive
			if !*params.IsActive {
				userState = identitydomain.UserStateDisabled
				principalStatus = identitydomain.PrincipalStatusDisabled
				revokeSessions = true
			}
			if err := q.UpdateIamPrincipalStatus(ctx, sqlcdb.UpdateIamPrincipalStatusParams{
				ID:     params.PrincipalID,
				Status: sqlcdb.IamPrincipalStatus(principalStatus),
			}); err != nil {
				return err
			}
			if err := q.UpdateIamUserState(ctx, sqlcdb.UpdateIamUserStateParams{
				PrincipalID: params.PrincipalID,
				State:       sqlcdb.IamUserState(userState),
			}); err != nil {
				return err
			}
		}

		if params.PasswordHash != nil {
			if _, err := q.UpsertIamPasswordCredential(ctx, sqlcdb.UpsertIamPasswordCredentialParams{
				PrincipalID:        params.PrincipalID,
				Scheme:             identitydomain.PasswordSchemeArgon2id,
				PasswordHash:       *params.PasswordHash,
				MustChangePassword: params.MustChangePassword,
				PasswordChangedAt:  timeValue(params.Now),
			}); err != nil {
				return err
			}
			if err := q.DeleteIamPasswordCredentialsByPrincipalExcludingScheme(ctx, sqlcdb.DeleteIamPasswordCredentialsByPrincipalExcludingSchemeParams{
				PrincipalID: params.PrincipalID,
				Scheme:      identitydomain.PasswordSchemeArgon2id,
			}); err != nil {
				return err
			}
			revokeSessions = true
		}

		if revokeSessions {
			if err := q.RevokeIamRefreshSessionsByPrincipal(ctx, sqlcdb.RevokeIamRefreshSessionsByPrincipalParams{
				Now:         timeValue(params.Now),
				PrincipalID: params.PrincipalID,
			}); err != nil {
				return err
			}
		}

		record, err = r.loadAdminUserRecord(ctx, q, params.PrincipalID)
		if err != nil {
			return err
		}
		result = record
		return nil
	})
	if err != nil {
		return nil, err
	}
	return result, nil
}

func (r *AdminStore) SoftDeleteAdminUser(ctx context.Context, params identityapp.DeleteAdminUserParams) error {
	return r.tx.InTx(ctx, func(tx pgx.Tx) error {
		q := sqlcdb.New(tx)

		record, err := r.loadAdminUserRecord(ctx, q, params.PrincipalID)
		if err != nil {
			return err
		}
		if record == nil || record.User.State == identitydomain.UserStateDeleted {
			return identityapp.ErrUserNotFound
		}
		protected, err := r.rejectLastSuperAdminDisable(ctx, q, params.PrincipalID)
		if err != nil {
			return err
		}
		if protected {
			return authorizationapp.ErrLastSuperAdmin
		}

		if err := q.UpdateIamPrincipalStatus(ctx, sqlcdb.UpdateIamPrincipalStatusParams{
			ID:     params.PrincipalID,
			Status: sqlcdb.IamPrincipalStatus(identitydomain.PrincipalStatusDisabled),
		}); err != nil {
			return err
		}
		if err := q.RevokeIamRefreshSessionsByPrincipal(ctx, sqlcdb.RevokeIamRefreshSessionsByPrincipalParams{
			Now:         timeValue(params.Now),
			PrincipalID: params.PrincipalID,
		}); err != nil {
			return err
		}
		return q.SoftDeleteIamUser(ctx, sqlcdb.SoftDeleteIamUserParams{
			PrincipalID: params.PrincipalID,
			Email:       buildDeletedUserEmail(params.PrincipalID),
			FullName:    pgtype.Text{},
		})
	})
}

func (r *AdminStore) rejectLastSuperAdminDisable(ctx context.Context, q *sqlcdb.Queries, principalID uuid.UUID) (bool, error) {
	superAdminRole, err := q.GetAuthzRoleByName(ctx, builtinSuperAdminRoleName)
	switch {
	case err == nil:
	case errors.Is(err, pgx.ErrNoRows):
		return false, nil
	default:
		return false, err
	}

	bindings, err := q.ListAuthzSystemBindingsByPrincipal(ctx, principalID)
	if err != nil {
		return false, err
	}
	hasSuperAdmin := false
	for _, binding := range bindings {
		if binding.RoleID == superAdminRole.ID {
			hasSuperAdmin = true
			break
		}
	}
	if !hasSuperAdmin {
		return false, nil
	}

	activeCount, err := q.CountActivePrincipalsBySystemRole(ctx, superAdminRole.ID)
	if err != nil {
		return false, err
	}
	return activeCount <= 1, nil
}

func (r *AdminStore) loadAdminUserRecord(ctx context.Context, q *sqlcdb.Queries, principalID uuid.UUID) (*identitydomain.AdminUserRecord, error) {
	principal, err := q.GetIamPrincipalByID(ctx, principalID)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return nil, nil
		}
		return nil, err
	}

	user, err := q.GetIamUserByPrincipalID(ctx, principalID)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return nil, nil
		}
		return nil, err
	}

	credentials, err := q.GetIamPasswordCredentialByPrincipal(ctx, principalID)
	if err != nil {
		return nil, err
	}

	mustChangePassword := false
	for _, credential := range credentials {
		if credential.MustChangePassword {
			mustChangePassword = true
			break
		}
	}

	return &identitydomain.AdminUserRecord{
		User:               *mapUser(user),
		PrincipalStatus:    identitydomain.PrincipalStatus(principal.Status),
		MustChangePassword: mustChangePassword,
	}, nil
}

func buildDeletedUserEmail(principalID uuid.UUID) string {
	return fmt.Sprintf("deleted+%s@saki.invalid", principalID.String())
}

func isConstraintViolation(err error, constraintName string) bool {
	var pgErr *pgconn.PgError
	return errors.As(err, &pgErr) &&
		pgErr.Code == "23505" &&
		pgErr.ConstraintName == constraintName
}
