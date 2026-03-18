package app

import (
	"context"
	"errors"

	assetrepo "github.com/elebirds/saki/saki-controlplane/internal/modules/asset/repo"
	sqlcdb "github.com/elebirds/saki/saki-controlplane/internal/gen/sqlc"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
)

type repoDurableUploadTxRunner interface {
	InTx(ctx context.Context, fn func(store assetrepo.DurableUploadTx) error) error
}

type repoTx interface {
	Tx() pgx.Tx
}

type repoDurableUploadTxRunnerAdapter struct {
	source repoDurableUploadTxRunner
}

type repoDurableUploadTxStoreAdapter struct {
	source assetrepo.DurableUploadTx
	tx     pgx.Tx
}

func NewRepoDurableUploadTxRunner(source repoDurableUploadTxRunner) DurableUploadTxRunner {
	if source == nil {
		return nil
	}
	return &repoDurableUploadTxRunnerAdapter{source: source}
}

func (r *repoDurableUploadTxRunnerAdapter) InTx(ctx context.Context, fn func(store DurableUploadTxStore) error) error {
	return r.source.InTx(ctx, func(store assetrepo.DurableUploadTx) error {
		tx, ok := store.(repoTx)
		if !ok {
			return errors.New("asset durable upload tx does not expose transaction")
		}
		return fn(repoDurableUploadTxStoreAdapter{
			source: store,
			tx:     tx.Tx(),
		})
	})
}

func (s repoDurableUploadTxStoreAdapter) ResolveOwner(ctx context.Context, ownerType AssetOwnerType, ownerID uuid.UUID) (*ResolvedOwner, error) {
	q := sqlcdb.New(s.tx)
	switch ownerType {
	case AssetOwnerTypeProject:
		if _, err := q.GetProject(ctx, ownerID); err != nil {
			if errors.Is(err, pgx.ErrNoRows) {
				return nil, nil
			}
			return nil, err
		}
		return &ResolvedOwner{OwnerType: ownerType, OwnerID: ownerID}, nil
	case AssetOwnerTypeDataset:
		if _, err := q.GetDataset(ctx, ownerID); err != nil {
			if errors.Is(err, pgx.ErrNoRows) {
				return nil, nil
			}
			return nil, err
		}
		return &ResolvedOwner{OwnerType: ownerType, OwnerID: ownerID}, nil
	case AssetOwnerTypeSample:
		sample, err := q.GetSample(ctx, ownerID)
		if err != nil {
			if errors.Is(err, pgx.ErrNoRows) {
				return nil, nil
			}
			return nil, err
		}
		datasetID := sample.DatasetID
		return &ResolvedOwner{
			OwnerType: ownerType,
			OwnerID:   ownerID,
			DatasetID: &datasetID,
		}, nil
	default:
		return nil, ErrUnsupportedAssetOwnerType
	}
}

func (s repoDurableUploadTxStoreAdapter) CreatePendingAsset(ctx context.Context, params CreatePendingAssetParams) (*Asset, error) {
	asset, err := s.source.CreatePendingAsset(ctx, assetrepo.CreatePendingAssetTxParams{
		Kind:           string(params.Kind),
		StorageBackend: string(params.StorageBackend),
		Bucket:         params.Bucket,
		ContentType:    params.ContentType,
		Metadata:       cloneBytes(params.Metadata),
		CreatedBy:      cloneUUIDPtr(params.CreatedBy),
		BuildObjectKey: params.BuildObjectKey,
		MaxAttempts:    params.MaxAttempts,
	})
	if err != nil {
		return nil, err
	}
	return fromRepoAsset(asset)
}

func (s repoDurableUploadTxStoreAdapter) GetAsset(ctx context.Context, id uuid.UUID) (*Asset, error) {
	asset, err := s.source.GetAsset(ctx, id)
	if err != nil {
		return nil, err
	}
	return fromRepoAsset(asset)
}

func (s repoDurableUploadTxStoreAdapter) MarkAssetReady(ctx context.Context, params MarkAssetReadyInput) (*Asset, error) {
	asset, err := s.source.MarkAssetReady(ctx, assetrepo.MarkReadyParams{
		ID:          params.ID,
		SizeBytes:   params.SizeBytes,
		Sha256Hex:   cloneStringPtr(params.SHA256Hex),
		ContentType: params.ContentType,
	})
	if err != nil {
		return nil, err
	}
	return fromRepoAsset(asset)
}

func (s repoDurableUploadTxStoreAdapter) GetUploadIntentByAssetID(ctx context.Context, assetID uuid.UUID) (*AssetUploadIntent, error) {
	intent, err := s.source.GetUploadIntentByAssetID(ctx, assetID)
	if err != nil {
		return nil, err
	}
	return fromRepoAssetUploadIntent(intent)
}

func (s repoDurableUploadTxStoreAdapter) GetUploadIntentByOwnerKey(ctx context.Context, params GetAssetUploadIntentByOwnerKeyInput) (*AssetUploadIntent, error) {
	intent, err := s.source.GetUploadIntentByOwnerKey(ctx, assetrepo.GetAssetUploadIntentByOwnerKeyParams{
		OwnerType:      string(params.OwnerType),
		OwnerID:        params.OwnerID,
		Role:           string(params.Role),
		IdempotencyKey: params.IdempotencyKey,
	})
	if err != nil {
		return nil, err
	}
	return fromRepoAssetUploadIntent(intent)
}

func (s repoDurableUploadTxStoreAdapter) CreateUploadIntent(ctx context.Context, params CreateAssetUploadIntentInput) (*AssetUploadIntent, error) {
	intent, err := s.source.CreateUploadIntent(ctx, assetrepo.CreateAssetUploadIntentParams{
		AssetID:             params.AssetID,
		OwnerType:           string(params.Binding.OwnerType),
		OwnerID:             params.Binding.OwnerID,
		Role:                string(params.Binding.Role),
		IsPrimary:           params.Binding.IsPrimary,
		DeclaredContentType: params.DeclaredContentType,
		IdempotencyKey:      params.IdempotencyKey,
		ExpiresAt:           params.ExpiresAt,
		CreatedBy:           cloneUUIDPtr(params.CreatedBy),
	})
	if err != nil {
		return nil, err
	}
	return fromRepoAssetUploadIntent(intent)
}

func (s repoDurableUploadTxStoreAdapter) MarkUploadIntentCompleted(ctx context.Context, params MarkAssetUploadIntentCompletedInput) (*AssetUploadIntent, error) {
	intent, err := s.source.MarkUploadIntentCompleted(ctx, assetrepo.MarkAssetUploadIntentCompletedParams{
		AssetID:     params.AssetID,
		CompletedAt: params.CompletedAt,
	})
	if err != nil {
		return nil, err
	}
	return fromRepoAssetUploadIntent(intent)
}

func (s repoDurableUploadTxStoreAdapter) MarkUploadIntentCanceled(ctx context.Context, params MarkAssetUploadIntentCanceledInput) (*AssetUploadIntent, error) {
	intent, err := s.source.MarkUploadIntentCanceled(ctx, assetrepo.MarkAssetUploadIntentCanceledParams{
		AssetID:    params.AssetID,
		CanceledAt: params.CanceledAt,
	})
	if err != nil {
		return nil, err
	}
	return fromRepoAssetUploadIntent(intent)
}

func (s repoDurableUploadTxStoreAdapter) MarkUploadIntentExpired(ctx context.Context, params MarkAssetUploadIntentExpiredInput) (*AssetUploadIntent, error) {
	intent, err := s.source.MarkUploadIntentExpired(ctx, assetrepo.MarkAssetUploadIntentExpiredParams{
		AssetID:   params.AssetID,
		ExpiredAt: params.ExpiredAt,
	})
	if err != nil {
		return nil, err
	}
	return fromRepoAssetUploadIntent(intent)
}

func (s repoDurableUploadTxStoreAdapter) CreateDurableReference(ctx context.Context, params CreateAssetReferenceInput) (*AssetReference, error) {
	reference, err := s.source.CreateDurableReference(ctx, assetrepo.CreateAssetReferenceParams{
		AssetID:   params.AssetID,
		OwnerType: string(params.Binding.OwnerType),
		OwnerID:   params.Binding.OwnerID,
		Role:      string(params.Binding.Role),
		Lifecycle: string(params.Lifecycle),
		IsPrimary: params.Binding.IsPrimary,
		Metadata:  cloneBytes(params.Metadata),
		CreatedBy: cloneUUIDPtr(params.CreatedBy),
	})
	if err != nil {
		return nil, err
	}
	return fromRepoAssetReference(reference)
}

func (s repoDurableUploadTxStoreAdapter) ListActiveReferencesByOwner(ctx context.Context, params ListActiveReferencesByOwnerInput) ([]AssetReference, error) {
	references, err := s.source.ListActiveReferencesByOwner(ctx, assetrepo.ListActiveReferencesByOwnerParams{
		OwnerType: string(params.OwnerType),
		OwnerID:   params.OwnerID,
	})
	if err != nil {
		return nil, err
	}

	result := make([]AssetReference, 0, len(references))
	for i := range references {
		reference, err := fromRepoAssetReference(&references[i])
		if err != nil {
			return nil, err
		}
		if reference != nil {
			result = append(result, *reference)
		}
	}
	return result, nil
}

func fromRepoAssetUploadIntent(intent *assetrepo.AssetUploadIntent) (*AssetUploadIntent, error) {
	if intent == nil {
		return nil, nil
	}
	ownerType, err := ParseAssetOwnerType(intent.OwnerType)
	if err != nil {
		return nil, err
	}
	role, err := ParseAssetReferenceRole(intent.Role)
	if err != nil {
		return nil, err
	}
	state, err := ParseAssetUploadIntentState(intent.State)
	if err != nil {
		return nil, err
	}

	return &AssetUploadIntent{
		ID:      intent.ID,
		AssetID: intent.AssetID,
		Binding: DurableOwnerBinding{
			OwnerType: ownerType,
			OwnerID:   intent.OwnerID,
			Role:      role,
			IsPrimary: intent.IsPrimary,
		},
		DeclaredContentType: intent.DeclaredContentType,
		State:               state,
		IdempotencyKey:      intent.IdempotencyKey,
		ExpiresAt:           intent.ExpiresAt,
		CreatedBy:           cloneUUIDPtr(intent.CreatedBy),
		CompletedAt:         cloneTimePtr(intent.CompletedAt),
		CanceledAt:          cloneTimePtr(intent.CanceledAt),
		CreatedAt:           intent.CreatedAt,
		UpdatedAt:           intent.UpdatedAt,
	}, nil
}

func fromRepoAssetReference(reference *assetrepo.AssetReference) (*AssetReference, error) {
	if reference == nil {
		return nil, nil
	}
	ownerType, err := ParseAssetOwnerType(reference.OwnerType)
	if err != nil {
		return nil, err
	}
	role, err := ParseAssetReferenceRole(reference.Role)
	if err != nil {
		return nil, err
	}
	lifecycle, err := ParseAssetReferenceLifecycle(reference.Lifecycle)
	if err != nil {
		return nil, err
	}

	return &AssetReference{
		ID:      reference.ID,
		AssetID: reference.AssetID,
		Binding: DurableOwnerBinding{
			OwnerType: ownerType,
			OwnerID:   reference.OwnerID,
			Role:      role,
			IsPrimary: reference.IsPrimary,
		},
		Lifecycle: lifecycle,
		Metadata:  cloneBytes(reference.Metadata),
		CreatedBy: cloneUUIDPtr(reference.CreatedBy),
		CreatedAt: reference.CreatedAt,
		DeletedAt: cloneTimePtr(reference.DeletedAt),
	}, nil
}
