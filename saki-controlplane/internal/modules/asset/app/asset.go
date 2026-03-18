package app

import (
	"context"
	"errors"

	assetrepo "github.com/elebirds/saki/saki-controlplane/internal/modules/asset/repo"
	"github.com/google/uuid"
)

const (
	AssetStatusPendingUpload = "pending_upload"
	AssetStatusReady         = "ready"
)

var ErrAssetNotFound = errors.New("asset not found")

type Store interface {
	Get(ctx context.Context, id uuid.UUID) (*assetrepo.Asset, error)
}
