package app

import (
	"context"
	"encoding/json"
	"time"

	systemdomain "github.com/elebirds/saki/saki-controlplane/internal/modules/system/domain"
	"github.com/google/uuid"
)

type InstallationStore interface {
	GetInstallation(ctx context.Context) (*systemdomain.Installation, error)
	UpsertInstallation(ctx context.Context, params UpsertInstallationParams) (*systemdomain.Installation, error)
}

type UpsertInstallationParams struct {
	InstallState       systemdomain.InstallationState
	Metadata           json.RawMessage
	SetupAt            *time.Time
	SetupByPrincipalID *uuid.UUID
}

type InstallationService struct {
	store InstallationStore
}

func NewInstallationService(store InstallationStore) *InstallationService {
	return &InstallationService{store: store}
}

func (s *InstallationService) Get(ctx context.Context) (*systemdomain.Installation, error) {
	return s.store.GetInstallation(ctx)
}

func (s *InstallationService) Upsert(ctx context.Context, params UpsertInstallationParams) (*systemdomain.Installation, error) {
	params.Metadata = normalizeInstallationMetadata(params.Metadata)
	params.SetupAt = cloneTimePtr(params.SetupAt)
	params.SetupByPrincipalID = cloneUUIDPtr(params.SetupByPrincipalID)
	return s.store.UpsertInstallation(ctx, params)
}

func normalizeInstallationMetadata(value json.RawMessage) json.RawMessage {
	if len(value) == 0 {
		return json.RawMessage(`{}`)
	}
	return append(json.RawMessage(nil), value...)
}

func cloneTimePtr(value *time.Time) *time.Time {
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
