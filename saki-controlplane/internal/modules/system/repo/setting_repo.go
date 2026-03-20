package repo

import (
	"context"
	"encoding/json"

	sqlcdb "github.com/elebirds/saki/saki-controlplane/internal/gen/sqlc"
	systemdomain "github.com/elebirds/saki/saki-controlplane/internal/modules/system/domain"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"
)

type SettingRepo struct {
	q *sqlcdb.Queries
}

func NewSettingRepo(pool *pgxpool.Pool) *SettingRepo {
	return &SettingRepo{q: sqlcdb.New(pool)}
}

func (r *SettingRepo) ListSettings(ctx context.Context, installationID uuid.UUID) ([]systemdomain.Setting, error) {
	rows, err := r.q.ListSystemSettings(ctx, installationID)
	if err != nil {
		return nil, err
	}

	result := make([]systemdomain.Setting, 0, len(rows))
	for _, row := range rows {
		result = append(result, systemdomain.Setting{
			ID:             row.ID,
			InstallationID: row.InstallationID,
			Key:            row.Key,
			Value:          append(json.RawMessage(nil), row.Value...),
			CreatedAt:      row.CreatedAt.Time,
			UpdatedAt:      row.UpdatedAt.Time,
		})
	}
	return result, nil
}

func (r *SettingRepo) UpsertSetting(ctx context.Context, installationID uuid.UUID, key string, value json.RawMessage) (*systemdomain.Setting, error) {
	row, err := r.q.UpsertSystemSetting(ctx, sqlcdb.UpsertSystemSettingParams{
		InstallationID: installationID,
		Key:            key,
		Value:          append([]byte(nil), value...),
	})
	if err != nil {
		return nil, err
	}

	return &systemdomain.Setting{
		ID:             row.ID,
		InstallationID: row.InstallationID,
		Key:            row.Key,
		Value:          append(json.RawMessage(nil), row.Value...),
		CreatedAt:      row.CreatedAt.Time,
		UpdatedAt:      row.UpdatedAt.Time,
	}, nil
}
