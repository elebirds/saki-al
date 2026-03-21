package repo

import (
	"context"
	"encoding/json"
	"errors"
	"time"

	sqlcdb "github.com/elebirds/saki/saki-controlplane/internal/gen/sqlc"
	systemapp "github.com/elebirds/saki/saki-controlplane/internal/modules/system/app"
	systemdomain "github.com/elebirds/saki/saki-controlplane/internal/modules/system/domain"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgtype"
	"github.com/jackc/pgx/v5/pgxpool"
)

type InstallationRepo struct {
	q *sqlcdb.Queries
}

var _ systemapp.InstallationStore = (*InstallationRepo)(nil)

func NewInstallationRepo(pool *pgxpool.Pool) *InstallationRepo {
	return &InstallationRepo{q: sqlcdb.New(pool)}
}

func (r *InstallationRepo) GetInstallation(ctx context.Context) (*systemdomain.Installation, error) {
	row, err := r.q.GetSystemInstallation(ctx)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return nil, nil
		}
		return nil, err
	}
	return mapInstallation(row), nil
}

func (r *InstallationRepo) UpsertInstallation(ctx context.Context, params systemapp.UpsertInstallationParams) (*systemdomain.Installation, error) {
	metadata := params.Metadata
	if len(metadata) == 0 {
		metadata = json.RawMessage(`{}`)
	}
	row, err := r.q.UpsertSystemInstallation(ctx, sqlcdb.UpsertSystemInstallationParams{
		InstallState:       mapDomainInitializationStateToRepo(params.InitializationState),
		Metadata:           append([]byte(nil), metadata...),
		SetupAt:            toRepoTime(params.InitializedAt),
		SetupByPrincipalID: toRepoUUID(params.InitializedByPrincipalID),
	})
	if err != nil {
		return nil, err
	}
	return mapInstallation(row), nil
}

func mapInstallation(row sqlcdb.SystemInstallation) *systemdomain.Installation {
	return &systemdomain.Installation{
		ID:                       row.ID,
		InstallationKey:          row.InstallationKey,
		InitializationState:      mapRepoInitializationStateToDomain(row.InstallState),
		Metadata:                 append(json.RawMessage(nil), row.Metadata...),
		InitializedAt:            fromRepoTime(row.SetupAt),
		InitializedByPrincipalID: fromRepoUUID(row.SetupByPrincipalID),
		CreatedAt:                row.CreatedAt.Time,
		UpdatedAt:                row.UpdatedAt.Time,
	}
}

func mapDomainInitializationStateToRepo(value systemdomain.InitializationState) sqlcdb.SystemInstallationState {
	switch value {
	case systemdomain.InitializationStateInitialized:
		return sqlcdb.SystemInstallationStateReady
	default:
		return sqlcdb.SystemInstallationStateUninitialized
	}
}

func mapRepoInitializationStateToDomain(value sqlcdb.SystemInstallationState) systemdomain.InitializationState {
	// 关键设计：公开与应用层已经切到 initialization 语义，
	// 但数据库迁移尚未进行，所以这里继续把旧库值 `ready` 映射成新的 `initialized`。
	switch value {
	case sqlcdb.SystemInstallationStateReady:
		return systemdomain.InitializationStateInitialized
	default:
		return systemdomain.InitializationStateUninitialized
	}
}

func toRepoTime(value *time.Time) pgtype.Timestamptz {
	if value == nil {
		return pgtype.Timestamptz{}
	}
	return pgtype.Timestamptz{Time: value.UTC(), Valid: true}
}

func fromRepoTime(value pgtype.Timestamptz) *time.Time {
	if !value.Valid {
		return nil
	}
	copy := value.Time
	return &copy
}

func toRepoUUID(value *uuid.UUID) pgtype.UUID {
	if value == nil {
		return pgtype.UUID{}
	}
	return pgtype.UUID{Bytes: *value, Valid: true}
}

func fromRepoUUID(value pgtype.UUID) *uuid.UUID {
	if !value.Valid {
		return nil
	}
	copy := uuid.UUID(value.Bytes)
	return &copy
}
