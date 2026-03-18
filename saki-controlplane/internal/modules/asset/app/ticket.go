package app

import (
	"context"
	"errors"
	"time"

	"github.com/elebirds/saki/saki-controlplane/internal/app/storage"
	"github.com/google/uuid"
)

var ErrAssetNotPendingUpload = errors.New("asset is not pending upload")
var ErrAssetNotReady = errors.New("asset is not ready")

type Ticket struct {
	AssetID uuid.UUID
	URL     string
}

type IssueUploadTicketUseCase struct {
	store    Store
	provider storage.Provider
	expiry   time.Duration
}

func NewIssueUploadTicketUseCase(store Store, provider storage.Provider, expiry time.Duration) *IssueUploadTicketUseCase {
	return &IssueUploadTicketUseCase{
		store:    store,
		provider: provider,
		expiry:   expiry,
	}
}

func (u *IssueUploadTicketUseCase) Execute(ctx context.Context, assetID uuid.UUID) (*Ticket, error) {
	asset, err := u.store.Get(ctx, assetID)
	if err != nil {
		return nil, err
	}
	if asset == nil {
		return nil, ErrAssetNotFound
	}
	if asset.Status != AssetStatusPendingUpload {
		return nil, ErrAssetNotPendingUpload
	}

	url, err := u.provider.SignPutObject(ctx, asset.ObjectKey, u.expiry, asset.ContentType)
	if err != nil {
		return nil, err
	}
	return &Ticket{
		AssetID: asset.ID,
		URL:     url,
	}, nil
}

type IssueDownloadTicketUseCase struct {
	store    Store
	provider storage.Provider
	expiry   time.Duration
}

func NewIssueDownloadTicketUseCase(store Store, provider storage.Provider, expiry time.Duration) *IssueDownloadTicketUseCase {
	return &IssueDownloadTicketUseCase{
		store:    store,
		provider: provider,
		expiry:   expiry,
	}
}

func (u *IssueDownloadTicketUseCase) Execute(ctx context.Context, assetID uuid.UUID) (*Ticket, error) {
	asset, err := u.store.Get(ctx, assetID)
	if err != nil {
		return nil, err
	}
	if asset == nil {
		return nil, ErrAssetNotFound
	}
	if asset.Status != AssetStatusReady {
		return nil, ErrAssetNotReady
	}

	url, err := u.provider.SignGetObject(ctx, asset.ObjectKey, u.expiry)
	if err != nil {
		return nil, err
	}
	return &Ticket{
		AssetID: asset.ID,
		URL:     url,
	}, nil
}
