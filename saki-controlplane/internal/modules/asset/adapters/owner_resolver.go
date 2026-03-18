package adapters

import (
	"context"
	"database/sql"
	"errors"

	sqlcdb "github.com/elebirds/saki/saki-controlplane/internal/gen/sqlc"
	assetapp "github.com/elebirds/saki/saki-controlplane/internal/modules/asset/app"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
)

type ownerResolver struct {
	q *sqlcdb.Queries
}

func NewOwnerResolver(db sqlcdb.DBTX) assetapp.OwnerResolver {
	return &ownerResolver{q: sqlcdb.New(db)}
}

func (r *ownerResolver) Resolve(ctx context.Context, ownerType assetapp.AssetOwnerType, ownerID uuid.UUID) (*assetapp.ResolvedOwner, error) {
	switch ownerType {
	case assetapp.AssetOwnerTypeProject:
		_, err := r.q.GetProject(ctx, ownerID)
		if err != nil {
			if errors.Is(err, pgx.ErrNoRows) || errors.Is(err, sql.ErrNoRows) {
				return nil, nil
			}
			return nil, err
		}
		return &assetapp.ResolvedOwner{OwnerType: ownerType, OwnerID: ownerID}, nil
	case assetapp.AssetOwnerTypeDataset:
		_, err := r.q.GetDataset(ctx, ownerID)
		if err != nil {
			if errors.Is(err, pgx.ErrNoRows) || errors.Is(err, sql.ErrNoRows) {
				return nil, nil
			}
			return nil, err
		}
		return &assetapp.ResolvedOwner{OwnerType: ownerType, OwnerID: ownerID}, nil
	case assetapp.AssetOwnerTypeSample:
		sample, err := r.q.GetSample(ctx, ownerID)
		if err != nil {
			if errors.Is(err, pgx.ErrNoRows) || errors.Is(err, sql.ErrNoRows) {
				return nil, nil
			}
			return nil, err
		}
		datasetID := sample.DatasetID
		return &assetapp.ResolvedOwner{
			OwnerType: ownerType,
			OwnerID:   ownerID,
			DatasetID: &datasetID,
		}, nil
	default:
		return nil, assetapp.ErrUnsupportedAssetOwnerType
	}
}
