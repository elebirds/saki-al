package app

import (
	"bytes"
	"context"
	"errors"
	"time"

	"github.com/elebirds/saki/saki-controlplane/internal/app/storage"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgconn"
)

var ErrAssetOwnerNotFound = errors.New("asset owner not found")
var ErrAssetUploadIdempotencyConflict = errors.New("asset upload idempotency conflict")
var ErrAssetUploadIntentConflict = errors.New("asset upload intent conflict")
var ErrAssetUploadIntentExpired = errors.New("asset upload intent expired")
var ErrAssetUploadIntentNotCompletable = errors.New("asset upload intent is not completable")
var ErrAssetUploadIntentNotCancelable = errors.New("asset upload intent is not cancelable")
var ErrAssetUploadInconsistentState = errors.New("asset upload state is inconsistent")
var ErrAssetUploadObjectSizeMismatch = errors.New("uploaded object size does not match request")
var ErrDurableReferenceConflict = errors.New("durable asset reference conflict")

const (
	assetReferenceOwnerRoleUniqueConstraint = "asset_reference_active_asset_owner_role_key"
	assetReferencePrimaryUniqueConstraint   = "asset_reference_active_owner_role_primary_key"
)

type AssetUploadIntent struct {
	ID                  uuid.UUID
	AssetID             uuid.UUID
	Binding             DurableOwnerBinding
	DeclaredContentType string
	State               AssetUploadIntentState
	IdempotencyKey      string
	ExpiresAt           time.Time
	CreatedBy           *uuid.UUID
	CompletedAt         *time.Time
	CanceledAt          *time.Time
	CreatedAt           time.Time
	UpdatedAt           time.Time
}

type AssetReference struct {
	ID        uuid.UUID
	AssetID   uuid.UUID
	Binding   DurableOwnerBinding
	Lifecycle AssetReferenceLifecycle
	Metadata  []byte
	CreatedBy *uuid.UUID
	CreatedAt time.Time
	DeletedAt *time.Time
}

type CreatePendingAssetParams struct {
	Kind           AssetKind
	StorageBackend AssetStorageBackend
	Bucket         string
	ContentType    string
	Metadata       []byte
	CreatedBy      *uuid.UUID
	BuildObjectKey func(attempt int) string
	MaxAttempts    int
}

type GetAssetUploadIntentByOwnerKeyInput struct {
	OwnerType      AssetOwnerType
	OwnerID        uuid.UUID
	Role           AssetReferenceRole
	IdempotencyKey string
}

type CreateAssetUploadIntentInput struct {
	AssetID             uuid.UUID
	Binding             DurableOwnerBinding
	DeclaredContentType string
	IdempotencyKey      string
	ExpiresAt           time.Time
	CreatedBy           *uuid.UUID
	CreatedAt           time.Time
}

type MarkAssetReadyInput struct {
	ID          uuid.UUID
	SizeBytes   int64
	SHA256Hex   *string
	ContentType string
	ReadyAt     *time.Time
	UpdatedAt   time.Time
}

type MarkAssetUploadIntentCompletedInput struct {
	AssetID     uuid.UUID
	CompletedAt time.Time
}

type MarkAssetUploadIntentCanceledInput struct {
	AssetID    uuid.UUID
	CanceledAt time.Time
}

type MarkAssetUploadIntentExpiredInput struct {
	AssetID   uuid.UUID
	ExpiredAt time.Time
}

type CreateAssetReferenceInput struct {
	AssetID   uuid.UUID
	Binding   DurableOwnerBinding
	Lifecycle AssetReferenceLifecycle
	Metadata  []byte
	CreatedBy *uuid.UUID
	CreatedAt time.Time
}

type ListActiveReferencesByOwnerInput struct {
	OwnerType AssetOwnerType
	OwnerID   uuid.UUID
}

type DurableUploadTxStore interface {
	ResolveOwner(ctx context.Context, ownerType AssetOwnerType, ownerID uuid.UUID) (*ResolvedOwner, error)
	CreatePendingAsset(ctx context.Context, params CreatePendingAssetParams) (*Asset, error)
	GetAsset(ctx context.Context, id uuid.UUID) (*Asset, error)
	MarkAssetReady(ctx context.Context, params MarkAssetReadyInput) (*Asset, error)
	GetUploadIntentByAssetID(ctx context.Context, assetID uuid.UUID) (*AssetUploadIntent, error)
	GetUploadIntentByOwnerKey(ctx context.Context, params GetAssetUploadIntentByOwnerKeyInput) (*AssetUploadIntent, error)
	CreateUploadIntent(ctx context.Context, params CreateAssetUploadIntentInput) (*AssetUploadIntent, error)
	MarkUploadIntentCompleted(ctx context.Context, params MarkAssetUploadIntentCompletedInput) (*AssetUploadIntent, error)
	MarkUploadIntentCanceled(ctx context.Context, params MarkAssetUploadIntentCanceledInput) (*AssetUploadIntent, error)
	MarkUploadIntentExpired(ctx context.Context, params MarkAssetUploadIntentExpiredInput) (*AssetUploadIntent, error)
	CreateDurableReference(ctx context.Context, params CreateAssetReferenceInput) (*AssetReference, error)
	ListActiveReferencesByOwner(ctx context.Context, params ListActiveReferencesByOwnerInput) ([]AssetReference, error)
}

type DurableUploadTxRunner interface {
	InTx(ctx context.Context, fn func(store DurableUploadTxStore) error) error
}

type DurableUploadConfig struct {
	Now                func() time.Time
	BuildObjectKey     func(kind AssetKind, attempt int) string
	UploadURLExpiry    time.Duration
	IntentTTL          time.Duration
	UploadGraceWindow  time.Duration
	MaxObjectKeyTrials int
}

type InitDurableUploadInput struct {
	Binding             DurableOwnerBinding
	Kind                AssetKind
	DeclaredContentType string
	Metadata            []byte
	IdempotencyKey      string
	CreatedBy           *uuid.UUID
}

type InitDurableUploadResult struct {
	Asset        *Asset
	Intent       *AssetUploadIntent
	UploadTicket *Ticket
}

type CompleteDurableUploadInput struct {
	AssetID          uuid.UUID
	RequestSizeBytes *int64
	SHA256Hex        *string
}

type CompleteDurableUploadResult struct {
	Asset     *Asset
	Intent    *AssetUploadIntent
	Reference *AssetReference
}

type CancelDurableUploadResult struct {
	Intent *AssetUploadIntent
}

type InitDurableUploadUseCase struct {
	tx       DurableUploadTxRunner
	provider storage.Provider
	config   DurableUploadConfig
}

func NewInitDurableUploadUseCase(tx DurableUploadTxRunner, provider storage.Provider, config DurableUploadConfig) *InitDurableUploadUseCase {
	return &InitDurableUploadUseCase{tx: tx, provider: provider, config: config}
}

func (u *InitDurableUploadUseCase) Execute(ctx context.Context, input InitDurableUploadInput) (*InitDurableUploadResult, error) {
	if err := input.Binding.Validate(); err != nil {
		return nil, err
	}
	kind, err := ParseAssetKind(string(input.Kind))
	if err != nil {
		return nil, err
	}

	now := u.config.now()
	var (
		result        *InitDurableUploadResult
		postCommitErr error
	)

	err = u.tx.InTx(ctx, func(store DurableUploadTxStore) error {
		if err := ensureOwnerExists(ctx, store, input.Binding); err != nil {
			return err
		}

		intent, err := store.GetUploadIntentByOwnerKey(ctx, GetAssetUploadIntentByOwnerKeyInput{
			OwnerType:      input.Binding.OwnerType,
			OwnerID:        input.Binding.OwnerID,
			Role:           input.Binding.Role,
			IdempotencyKey: input.IdempotencyKey,
		})
		if err != nil {
			return err
		}
		if intent == nil {
			asset, err := store.CreatePendingAsset(ctx, CreatePendingAssetParams{
				Kind:           kind,
				StorageBackend: AssetStorageBackendMinio,
				Bucket:         u.provider.Bucket(),
				ContentType:    input.DeclaredContentType,
				Metadata:       cloneBytes(input.Metadata),
				CreatedBy:      cloneUUIDPtr(input.CreatedBy),
				BuildObjectKey: func(attempt int) string {
					return u.config.buildObjectKey(kind, attempt)
				},
				MaxAttempts: u.config.maxObjectKeyTrials(),
			})
			if err != nil {
				return err
			}

			intent, err = store.CreateUploadIntent(ctx, CreateAssetUploadIntentInput{
				AssetID:             asset.ID,
				Binding:             input.Binding,
				DeclaredContentType: input.DeclaredContentType,
				IdempotencyKey:      input.IdempotencyKey,
				ExpiresAt:           u.config.intentExpiresAt(now),
				CreatedBy:           cloneUUIDPtr(input.CreatedBy),
				CreatedAt:           now,
			})
			if err != nil {
				return err
			}

			ticket, err := issueUploadTicket(ctx, u.provider, asset, u.config.uploadURLExpiry())
			if err != nil {
				return err
			}
			result = &InitDurableUploadResult{Asset: asset, Intent: intent, UploadTicket: ticket}
			return nil
		}

		asset, err := store.GetAsset(ctx, intent.AssetID)
		if err != nil {
			return err
		}
		if asset == nil {
			return ErrAssetUploadInconsistentState
		}
		if err := ensureInitContractMatches(intent, asset, input); err != nil {
			return err
		}

		switch intent.State {
		case AssetUploadIntentStateInitiated:
			if !intent.ExpiresAt.After(now) {
				expired, err := store.MarkUploadIntentExpired(ctx, MarkAssetUploadIntentExpiredInput{
					AssetID:   intent.AssetID,
					ExpiredAt: now,
				})
				if err != nil {
					return err
				}
				if expired == nil {
					return ErrAssetUploadInconsistentState
				}
				postCommitErr = ErrAssetUploadIntentConflict
				return nil
			}
			ticket, err := issueUploadTicket(ctx, u.provider, asset, u.config.uploadURLExpiry())
			if err != nil {
				return err
			}
			result = &InitDurableUploadResult{Asset: asset, Intent: intent, UploadTicket: ticket}
			return nil
		case AssetUploadIntentStateCompleted:
			if asset.Status != AssetStatusReady {
				return ErrAssetUploadInconsistentState
			}
			result = &InitDurableUploadResult{Asset: asset, Intent: intent}
			return nil
		case AssetUploadIntentStateCanceled, AssetUploadIntentStateExpired:
			return ErrAssetUploadIntentConflict
		default:
			return ErrAssetUploadInconsistentState
		}
	})
	if err != nil {
		return nil, err
	}
	if postCommitErr != nil {
		return nil, postCommitErr
	}
	return result, nil
}

type CompleteDurableUploadUseCase struct {
	tx       DurableUploadTxRunner
	provider storage.Provider
	config   DurableUploadConfig
}

func NewCompleteDurableUploadUseCase(tx DurableUploadTxRunner, provider storage.Provider, config DurableUploadConfig) *CompleteDurableUploadUseCase {
	return &CompleteDurableUploadUseCase{tx: tx, provider: provider, config: config}
}

func (u *CompleteDurableUploadUseCase) Execute(ctx context.Context, input CompleteDurableUploadInput) (*CompleteDurableUploadResult, error) {
	now := u.config.now()
	var (
		result        *CompleteDurableUploadResult
		postCommitErr error
	)

	err := u.tx.InTx(ctx, func(store DurableUploadTxStore) error {
		intent, asset, err := loadIntentAndAsset(ctx, store, input.AssetID)
		if err != nil {
			return err
		}

		switch intent.State {
		case AssetUploadIntentStateCompleted:
			reference, err := loadMatchingReference(ctx, store, intent)
			if err != nil {
				return err
			}
			if asset.Status != AssetStatusReady || reference == nil {
				return ErrAssetUploadInconsistentState
			}
			result = &CompleteDurableUploadResult{
				Asset:     asset,
				Intent:    intent,
				Reference: reference,
			}
			return nil
		case AssetUploadIntentStateInitiated:
			if !intent.ExpiresAt.After(now) {
				expired, err := store.MarkUploadIntentExpired(ctx, MarkAssetUploadIntentExpiredInput{
					AssetID:   intent.AssetID,
					ExpiredAt: now,
				})
				if err != nil {
					return err
				}
				if expired == nil {
					return ErrAssetUploadInconsistentState
				}
				postCommitErr = ErrAssetUploadIntentExpired
				return nil
			}
		default:
			return ErrAssetUploadIntentNotCompletable
		}

		if asset.Status != AssetStatusPendingUpload {
			return ErrAssetUploadInconsistentState
		}
		if asset.Bucket != u.provider.Bucket() {
			return ErrAssetBucketMismatch
		}

		objectStat, err := u.provider.StatObject(ctx, asset.ObjectKey)
		if err != nil {
			return err
		}
		if objectStat == nil {
			return storage.ErrObjectNotFound
		}
		if input.RequestSizeBytes != nil && objectStat.Size != *input.RequestSizeBytes {
			return ErrAssetUploadObjectSizeMismatch
		}
		if err := ensureOwnerExists(ctx, store, intent.Binding); err != nil {
			return err
		}

		references, err := store.ListActiveReferencesByOwner(ctx, ListActiveReferencesByOwnerInput{
			OwnerType: intent.Binding.OwnerType,
			OwnerID:   intent.Binding.OwnerID,
		})
		if err != nil {
			return err
		}
		if hasReferenceConflict(references, intent.Binding, asset.ID) {
			return ErrDurableReferenceConflict
		}

		contentType := intent.DeclaredContentType
		if objectStat.ContentType != "" {
			contentType = objectStat.ContentType
		}
		readyAt := now
		asset, err = store.MarkAssetReady(ctx, MarkAssetReadyInput{
			ID:          asset.ID,
			SizeBytes:   objectStat.Size,
			SHA256Hex:   cloneStringPtr(input.SHA256Hex),
			ContentType: contentType,
			ReadyAt:     &readyAt,
			UpdatedAt:   now,
		})
		if err != nil {
			return err
		}
		if asset == nil {
			return ErrAssetUploadInconsistentState
		}

		reference, err := store.CreateDurableReference(ctx, CreateAssetReferenceInput{
			AssetID:   asset.ID,
			Binding:   intent.Binding,
			Lifecycle: AssetReferenceLifecycleDurable,
			Metadata:  nil,
			CreatedBy: cloneUUIDPtr(intent.CreatedBy),
			CreatedAt: now,
		})
		if err != nil {
			if isDurableReferenceConflict(err) {
				return ErrDurableReferenceConflict
			}
			return err
		}

		intent, err = store.MarkUploadIntentCompleted(ctx, MarkAssetUploadIntentCompletedInput{
			AssetID:     asset.ID,
			CompletedAt: now,
		})
		if err != nil {
			return err
		}
		if intent == nil {
			return ErrAssetUploadInconsistentState
		}

		result = &CompleteDurableUploadResult{
			Asset:     asset,
			Intent:    intent,
			Reference: reference,
		}
		return nil
	})
	if err != nil {
		return nil, err
	}
	if postCommitErr != nil {
		return nil, postCommitErr
	}
	return result, nil
}

type CancelDurableUploadUseCase struct {
	tx     DurableUploadTxRunner
	config DurableUploadConfig
}

func NewCancelDurableUploadUseCase(tx DurableUploadTxRunner, config DurableUploadConfig) *CancelDurableUploadUseCase {
	return &CancelDurableUploadUseCase{tx: tx, config: config}
}

func (u *CancelDurableUploadUseCase) Execute(ctx context.Context, assetID uuid.UUID) (*CancelDurableUploadResult, error) {
	now := u.config.now()
	var result *CancelDurableUploadResult
	err := u.tx.InTx(ctx, func(store DurableUploadTxStore) error {
		intent, err := store.GetUploadIntentByAssetID(ctx, assetID)
		if err != nil {
			return err
		}
		if intent == nil {
			return ErrAssetNotFound
		}

		switch intent.State {
		case AssetUploadIntentStateInitiated:
			intent, err = store.MarkUploadIntentCanceled(ctx, MarkAssetUploadIntentCanceledInput{
				AssetID:    assetID,
				CanceledAt: now,
			})
			if err != nil {
				return err
			}
			if intent == nil {
				return ErrAssetUploadInconsistentState
			}
			result = &CancelDurableUploadResult{Intent: intent}
			return nil
		case AssetUploadIntentStateCanceled, AssetUploadIntentStateExpired:
			result = &CancelDurableUploadResult{Intent: intent}
			return nil
		case AssetUploadIntentStateCompleted:
			return ErrAssetUploadIntentNotCancelable
		default:
			return ErrAssetUploadInconsistentState
		}
	})
	if err != nil {
		return nil, err
	}
	return result, nil
}

func loadIntentAndAsset(ctx context.Context, store DurableUploadTxStore, assetID uuid.UUID) (*AssetUploadIntent, *Asset, error) {
	intent, err := store.GetUploadIntentByAssetID(ctx, assetID)
	if err != nil {
		return nil, nil, err
	}
	if intent == nil {
		return nil, nil, ErrAssetNotFound
	}
	asset, err := store.GetAsset(ctx, assetID)
	if err != nil {
		return nil, nil, err
	}
	if asset == nil {
		return nil, nil, ErrAssetUploadInconsistentState
	}
	return intent, asset, nil
}

func loadMatchingReference(ctx context.Context, store DurableUploadTxStore, intent *AssetUploadIntent) (*AssetReference, error) {
	references, err := store.ListActiveReferencesByOwner(ctx, ListActiveReferencesByOwnerInput{
		OwnerType: intent.Binding.OwnerType,
		OwnerID:   intent.Binding.OwnerID,
	})
	if err != nil {
		return nil, err
	}
	for i := range references {
		ref := references[i]
		if ref.AssetID == intent.AssetID &&
			ref.Binding.OwnerType == intent.Binding.OwnerType &&
			ref.Binding.OwnerID == intent.Binding.OwnerID &&
			ref.Binding.Role == intent.Binding.Role &&
			ref.Binding.IsPrimary == intent.Binding.IsPrimary {
			copy := ref
			return &copy, nil
		}
	}
	return nil, nil
}

func ensureOwnerExists(ctx context.Context, store DurableUploadTxStore, binding DurableOwnerBinding) error {
	resolved, err := store.ResolveOwner(ctx, binding.OwnerType, binding.OwnerID)
	if err != nil {
		return err
	}
	if resolved == nil {
		return ErrAssetOwnerNotFound
	}
	return nil
}

func ensureInitContractMatches(intent *AssetUploadIntent, asset *Asset, input InitDurableUploadInput) error {
	if intent.Binding.OwnerType != input.Binding.OwnerType ||
		intent.Binding.OwnerID != input.Binding.OwnerID ||
		intent.Binding.Role != input.Binding.Role ||
		intent.Binding.IsPrimary != input.Binding.IsPrimary {
		return ErrAssetUploadIdempotencyConflict
	}
	if !uuidPtrEqual(intent.CreatedBy, input.CreatedBy) {
		return ErrAssetUploadIdempotencyConflict
	}
	if asset.Kind != input.Kind {
		return ErrAssetUploadIdempotencyConflict
	}
	if !bytes.Equal(asset.Metadata, input.Metadata) {
		return ErrAssetUploadIdempotencyConflict
	}
	if intent.DeclaredContentType != input.DeclaredContentType {
		return ErrAssetUploadIdempotencyConflict
	}
	return nil
}

func issueUploadTicket(ctx context.Context, provider storage.Provider, asset *Asset, expiry time.Duration) (*Ticket, error) {
	if asset == nil {
		return nil, ErrAssetNotFound
	}
	if asset.Status != AssetStatusPendingUpload {
		return nil, ErrAssetNotPendingUpload
	}
	if asset.Bucket != provider.Bucket() {
		return nil, ErrAssetBucketMismatch
	}
	url, err := provider.SignPutObject(ctx, asset.ObjectKey, expiry, asset.ContentType)
	if err != nil {
		return nil, err
	}
	return &Ticket{
		AssetID: asset.ID,
		URL:     url,
	}, nil
}

func hasReferenceConflict(references []AssetReference, binding DurableOwnerBinding, assetID uuid.UUID) bool {
	for _, ref := range references {
		if ref.DeletedAt != nil {
			continue
		}
		if ref.AssetID == assetID && ref.Binding.Role == binding.Role {
			return true
		}
		if binding.IsPrimary &&
			ref.Binding.IsPrimary &&
			ref.Binding.Role == binding.Role {
			return true
		}
	}
	return false
}

func isDurableReferenceConflict(err error) bool {
	var pgErr *pgconn.PgError
	return errors.As(err, &pgErr) &&
		pgErr.Code == "23505" &&
		(pgErr.ConstraintName == assetReferenceOwnerRoleUniqueConstraint ||
			pgErr.ConstraintName == assetReferencePrimaryUniqueConstraint)
}

func uuidPtrEqual(left *uuid.UUID, right *uuid.UUID) bool {
	switch {
	case left == nil && right == nil:
		return true
	case left == nil || right == nil:
		return false
	default:
		return *left == *right
	}
}

func (c DurableUploadConfig) now() time.Time {
	if c.Now != nil {
		return c.Now().UTC()
	}
	return time.Now().UTC()
}

func (c DurableUploadConfig) buildObjectKey(kind AssetKind, attempt int) string {
	if c.BuildObjectKey != nil {
		return c.BuildObjectKey(kind, attempt)
	}
	return string(kind) + "/" + uuid.NewString()
}

func (c DurableUploadConfig) uploadURLExpiry() time.Duration {
	if c.UploadURLExpiry > 0 {
		return c.UploadURLExpiry
	}
	return 5 * time.Minute
}

func (c DurableUploadConfig) intentExpiresAt(now time.Time) time.Time {
	ttl := c.IntentTTL
	if ttl <= 0 {
		ttl = c.uploadURLExpiry()
	}
	if c.UploadGraceWindow > 0 && ttl > c.UploadGraceWindow {
		ttl = c.UploadGraceWindow
	}
	return now.Add(ttl)
}

func (c DurableUploadConfig) maxObjectKeyTrials() int {
	if c.MaxObjectKeyTrials > 0 {
		return c.MaxObjectKeyTrials
	}
	return 3
}
