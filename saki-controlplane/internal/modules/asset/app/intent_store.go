package app

import (
	"context"

	assetrepo "github.com/elebirds/saki/saki-controlplane/internal/modules/asset/repo"
	"github.com/google/uuid"
)

type IntentStore interface {
	GetUploadIntentByAssetID(ctx context.Context, assetID uuid.UUID) (*AssetUploadIntent, error)
}

type repoUploadIntentGetter interface {
	GetByAssetID(ctx context.Context, assetID uuid.UUID) (*assetrepo.AssetUploadIntent, error)
}

type repoIntentStore struct {
	source repoUploadIntentGetter
}

func NewRepoIntentStore(source repoUploadIntentGetter) IntentStore {
	if source == nil {
		return nil
	}
	return &repoIntentStore{source: source}
}

func (s *repoIntentStore) GetUploadIntentByAssetID(ctx context.Context, assetID uuid.UUID) (*AssetUploadIntent, error) {
	intent, err := s.source.GetByAssetID(ctx, assetID)
	if err != nil {
		return nil, err
	}
	return fromRepoAssetUploadIntent(intent)
}
