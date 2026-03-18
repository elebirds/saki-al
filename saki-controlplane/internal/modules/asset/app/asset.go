package app

import (
	"context"
	"errors"
	"time"

	assetrepo "github.com/elebirds/saki/saki-controlplane/internal/modules/asset/repo"
	"github.com/google/uuid"
)

var ErrAssetNotFound = errors.New("asset not found")

type Asset struct {
	ID             uuid.UUID
	Kind           AssetKind
	Status         AssetStatus
	StorageBackend AssetStorageBackend
	Bucket         string
	ObjectKey      string
	ContentType    string
	SizeBytes      int64
	Sha256Hex      *string
	Metadata       []byte
	CreatedBy      *uuid.UUID
	ReadyAt        *time.Time
	OrphanedAt     *time.Time
	CreatedAt      time.Time
	UpdatedAt      time.Time
}

type Store interface {
	Get(ctx context.Context, id uuid.UUID) (*Asset, error)
}

type repoGetter interface {
	Get(ctx context.Context, id uuid.UUID) (*assetrepo.Asset, error)
}

type repoStore struct {
	source repoGetter
}

func NewRepoStore(source repoGetter) Store {
	if source == nil {
		return nil
	}
	return &repoStore{source: source}
}

func (s *repoStore) Get(ctx context.Context, id uuid.UUID) (*Asset, error) {
	asset, err := s.source.Get(ctx, id)
	if err != nil {
		return nil, err
	}
	return fromRepoAsset(asset), nil
}

func fromRepoAsset(asset *assetrepo.Asset) *Asset {
	if asset == nil {
		return nil
	}

	return &Asset{
		ID:             asset.ID,
		Kind:           AssetKind(asset.Kind),
		Status:         AssetStatus(asset.Status),
		StorageBackend: AssetStorageBackend(asset.StorageBackend),
		Bucket:         asset.Bucket,
		ObjectKey:      asset.ObjectKey,
		ContentType:    asset.ContentType,
		SizeBytes:      asset.SizeBytes,
		Sha256Hex:      cloneStringPtr(asset.Sha256Hex),
		Metadata:       cloneBytes(asset.Metadata),
		CreatedBy:      cloneUUIDPtr(asset.CreatedBy),
		ReadyAt:        cloneTimePtr(asset.ReadyAt),
		OrphanedAt:     cloneTimePtr(asset.OrphanedAt),
		CreatedAt:      asset.CreatedAt,
		UpdatedAt:      asset.UpdatedAt,
	}
}

func cloneStringPtr(value *string) *string {
	if value == nil {
		return nil
	}
	copy := *value
	return &copy
}

func cloneUUIDPtr(value *uuid.UUID) *uuid.UUID {
	if value == nil {
		return nil
	}
	copy := *value
	return &copy
}

func cloneTimePtr(value *time.Time) *time.Time {
	if value == nil {
		return nil
	}
	copy := *value
	return &copy
}

func cloneBytes(value []byte) []byte {
	if value == nil {
		return nil
	}
	cloned := make([]byte, len(value))
	copy(cloned, value)
	return cloned
}
