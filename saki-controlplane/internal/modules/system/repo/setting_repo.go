package repo

import (
	"context"
	"encoding/json"

	appdb "github.com/elebirds/saki/saki-controlplane/internal/app/db"
	sqlcdb "github.com/elebirds/saki/saki-controlplane/internal/gen/sqlc"
	systemdomain "github.com/elebirds/saki/saki-controlplane/internal/modules/system/domain"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

type SettingRepo struct {
	q  *sqlcdb.Queries
	tx *appdb.TxRunner
}

func NewSettingRepo(pool *pgxpool.Pool) *SettingRepo {
	return &SettingRepo{
		q:  sqlcdb.New(pool),
		tx: appdb.NewTxRunner(pool),
	}
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

func (r *SettingRepo) UpsertSettings(ctx context.Context, installationID uuid.UUID, values map[string]json.RawMessage) error {
	// 关键设计：多键 settings patch 必须在一个数据库事务里提交，
	// 否则 API 返回失败时，数据库里却可能已经写进一半配置，后续排障会非常混乱。
	return r.tx.InTx(ctx, func(tx pgx.Tx) error {
		q := sqlcdb.New(tx)
		for key, value := range values {
			if _, err := q.UpsertSystemSetting(ctx, sqlcdb.UpsertSystemSettingParams{
				InstallationID: installationID,
				Key:            key,
				Value:          append([]byte(nil), value...),
			}); err != nil {
				return err
			}
		}
		return nil
	})
}
