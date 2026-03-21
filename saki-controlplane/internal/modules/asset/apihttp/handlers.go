package apihttp

import (
	"context"
	"time"

	"github.com/elebirds/saki/saki-controlplane/internal/app/storage"
	assetapp "github.com/elebirds/saki/saki-controlplane/internal/modules/asset/app"
	"github.com/google/uuid"
)

type Store = assetapp.Store

type InitUploadUseCase interface {
	Execute(ctx context.Context, input assetapp.InitDurableUploadInput) (*assetapp.InitDurableUploadResult, error)
}

type CompleteUploadUseCase interface {
	Execute(ctx context.Context, input assetapp.CompleteDurableUploadInput) (*assetapp.CompleteDurableUploadResult, error)
}

type CancelUploadUseCase interface {
	Execute(ctx context.Context, assetID uuid.UUID) (*assetapp.CancelDurableUploadResult, error)
}

type Dependencies struct {
	Store           Store
	IntentStore     assetapp.IntentStore
	InitUpload      InitUploadUseCase
	CompleteUpload  CompleteUploadUseCase
	CancelUpload    CancelUploadUseCase
	Provider        storage.Provider
	UploadURLExpiry time.Duration
	DownloadExpiry  time.Duration
}

type Handlers struct {
	store          Store
	intentStore    assetapp.IntentStore
	initUpload     InitUploadUseCase
	completeUpload CompleteUploadUseCase
	cancelUpload   CancelUploadUseCase
	provider       storage.Provider
	uploadExpiry   time.Duration
	downloadExpiry time.Duration
}

// 关键设计：asset transport 入口只做 durable upload 依赖装配。
// 上传写链路与资产读链路拆分后，各自维护自己的协议边界，不再混在一个 handlers.go 中。
func NewHandlers(deps Dependencies) *Handlers {
	return &Handlers{
		store:          deps.Store,
		intentStore:    deps.IntentStore,
		initUpload:     deps.InitUpload,
		completeUpload: deps.CompleteUpload,
		cancelUpload:   deps.CancelUpload,
		provider:       deps.Provider,
		uploadExpiry:   deps.UploadURLExpiry,
		downloadExpiry: deps.DownloadExpiry,
	}
}

func (h *Handlers) Enabled() bool {
	return h != nil && h.store != nil && h.provider != nil
}
