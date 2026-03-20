package app

import (
	"context"
	"encoding/json"
	"slices"
	"testing"
	"time"

	systemdomain "github.com/elebirds/saki/saki-controlplane/internal/modules/system/domain"
	"github.com/google/uuid"
)

func TestInstallationServiceGetsCurrentInstallation(t *testing.T) {
	now := time.Date(2026, 3, 20, 13, 0, 0, 0, time.UTC)
	installationID := uuid.MustParse("00000000-0000-0000-0000-000000000701")
	setupBy := uuid.MustParse("00000000-0000-0000-0000-000000000702")
	store := &fakeInstallationStore{
		current: &systemdomain.Installation{
			ID:                 installationID,
			InstallState:       systemdomain.InstallationStateReady,
			Metadata:           json.RawMessage(`{"source":"test"}`),
			SetupAt:            &now,
			SetupByPrincipalID: &setupBy,
			CreatedAt:          now,
			UpdatedAt:          now,
		},
	}

	service := NewInstallationService(store)

	got, err := service.Get(context.Background())
	if err != nil {
		t.Fatalf("get installation: %v", err)
	}
	if got == nil {
		t.Fatal("expected installation")
	}
	if got.InstallState != systemdomain.InstallationStateReady {
		t.Fatalf("unexpected install state: %+v", got)
	}
	if got.SetupAt == nil || !got.SetupAt.Equal(now) {
		t.Fatalf("unexpected setup time: %+v", got)
	}
	if got.SetupByPrincipalID == nil || *got.SetupByPrincipalID != setupBy {
		t.Fatalf("unexpected setup principal: %+v", got)
	}
	if string(got.Metadata) != `{"source":"test"}` {
		t.Fatalf("unexpected metadata: %s", got.Metadata)
	}
}

func TestInstallationServiceUpsertsInstallation(t *testing.T) {
	now := time.Date(2026, 3, 20, 14, 0, 0, 0, time.UTC)
	setupBy := uuid.MustParse("00000000-0000-0000-0000-000000000703")
	store := &fakeInstallationStore{}
	service := NewInstallationService(store)

	updated, err := service.Upsert(context.Background(), UpsertInstallationParams{
		InstallState:       systemdomain.InstallationStateReady,
		Metadata:           json.RawMessage(`{"allow_self_register":true}`),
		SetupAt:            &now,
		SetupByPrincipalID: &setupBy,
	})
	if err != nil {
		t.Fatalf("upsert installation: %v", err)
	}

	if len(store.upserts) != 1 {
		t.Fatalf("expected one upsert, got %d", len(store.upserts))
	}
	recorded := store.upserts[0]
	if recorded.InstallState != systemdomain.InstallationStateReady {
		t.Fatalf("unexpected recorded install state: %+v", recorded)
	}
	if recorded.SetupAt == nil || !recorded.SetupAt.Equal(now) {
		t.Fatalf("unexpected recorded setup time: %+v", recorded)
	}
	if recorded.SetupByPrincipalID == nil || *recorded.SetupByPrincipalID != setupBy {
		t.Fatalf("unexpected recorded setup principal: %+v", recorded)
	}
	if string(recorded.Metadata) != `{"allow_self_register":true}` {
		t.Fatalf("unexpected recorded metadata: %s", recorded.Metadata)
	}

	if updated == nil {
		t.Fatal("expected upsert result")
	}
	if !slices.Equal(updated.Metadata, json.RawMessage(`{"allow_self_register":true}`)) {
		t.Fatalf("unexpected upsert metadata: %s", updated.Metadata)
	}
}

func TestInstallationServiceDefaultsNilMetadataToEmptyObject(t *testing.T) {
	store := &fakeInstallationStore{}
	service := NewInstallationService(store)

	updated, err := service.Upsert(context.Background(), UpsertInstallationParams{
		InstallState: systemdomain.InstallationStateUninitialized,
	})
	if err != nil {
		t.Fatalf("upsert installation with nil metadata: %v", err)
	}

	if len(store.upserts) != 1 {
		t.Fatalf("expected one upsert, got %d", len(store.upserts))
	}
	if string(store.upserts[0].Metadata) != `{}` {
		t.Fatalf("expected nil metadata to normalize to empty object, got %q", string(store.upserts[0].Metadata))
	}
	if updated == nil || string(updated.Metadata) != `{}` {
		t.Fatalf("expected returned metadata to be empty object, got %+v", updated)
	}
}

func TestInstallationServiceClonesPointerInputs(t *testing.T) {
	now := time.Date(2026, 3, 20, 16, 0, 0, 0, time.UTC)
	setupBy := uuid.MustParse("00000000-0000-0000-0000-000000000705")
	store := &fakeInstallationStore{}
	service := NewInstallationService(store)

	params := UpsertInstallationParams{
		InstallState:       systemdomain.InstallationStateReady,
		Metadata:           json.RawMessage(`{"mode":"safe"}`),
		SetupAt:            &now,
		SetupByPrincipalID: &setupBy,
	}

	updated, err := service.Upsert(context.Background(), params)
	if err != nil {
		t.Fatalf("upsert installation: %v", err)
	}

	now = now.Add(2 * time.Hour)
	setupBy = uuid.MustParse("00000000-0000-0000-0000-000000000706")

	recorded := store.upserts[0]
	if recorded.SetupAt == nil || recorded.SetupAt.Hour() != 16 {
		t.Fatalf("expected stored setup time to stay isolated, got %+v", recorded.SetupAt)
	}
	if recorded.SetupByPrincipalID == nil || *recorded.SetupByPrincipalID == setupBy {
		t.Fatalf("expected stored setup principal to stay isolated, got %+v", recorded.SetupByPrincipalID)
	}
	if updated == nil || updated.SetupAt == nil || updated.SetupAt.Hour() != 16 {
		t.Fatalf("expected returned setup time to stay isolated, got %+v", updated)
	}
	if updated.SetupByPrincipalID == nil || *updated.SetupByPrincipalID == setupBy {
		t.Fatalf("expected returned setup principal to stay isolated, got %+v", updated.SetupByPrincipalID)
	}
}

type fakeInstallationStore struct {
	current *systemdomain.Installation
	upserts []UpsertInstallationParams
}

func (s *fakeInstallationStore) GetInstallation(context.Context) (*systemdomain.Installation, error) {
	return cloneInstallation(s.current), nil
}

func (s *fakeInstallationStore) UpsertInstallation(_ context.Context, params UpsertInstallationParams) (*systemdomain.Installation, error) {
	s.upserts = append(s.upserts, cloneUpsertInstallationParams(params))

	now := time.Date(2026, 3, 20, 15, 0, 0, 0, time.UTC)
	s.current = &systemdomain.Installation{
		ID:                 uuid.MustParse("00000000-0000-0000-0000-000000000704"),
		InstallState:       params.InstallState,
		Metadata:           append(json.RawMessage(nil), params.Metadata...),
		SetupAt:            cloneTime(params.SetupAt),
		SetupByPrincipalID: cloneUUID(params.SetupByPrincipalID),
		CreatedAt:          now,
		UpdatedAt:          now,
	}
	return cloneInstallation(s.current), nil
}

func cloneInstallation(value *systemdomain.Installation) *systemdomain.Installation {
	if value == nil {
		return nil
	}
	copy := *value
	copy.Metadata = append(json.RawMessage(nil), value.Metadata...)
	copy.SetupAt = cloneTime(value.SetupAt)
	copy.SetupByPrincipalID = cloneUUID(value.SetupByPrincipalID)
	return &copy
}

func cloneUpsertInstallationParams(value UpsertInstallationParams) UpsertInstallationParams {
	value.Metadata = append(json.RawMessage(nil), value.Metadata...)
	value.SetupAt = cloneTime(value.SetupAt)
	value.SetupByPrincipalID = cloneUUID(value.SetupByPrincipalID)
	return value
}

func cloneTime(value *time.Time) *time.Time {
	if value == nil {
		return nil
	}
	copy := *value
	return &copy
}

func cloneUUID(value *uuid.UUID) *uuid.UUID {
	if value == nil {
		return nil
	}
	copy := *value
	return &copy
}
