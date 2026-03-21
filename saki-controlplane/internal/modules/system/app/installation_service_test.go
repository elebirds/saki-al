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
			ID:                       installationID,
			InitializationState:      systemdomain.InitializationStateInitialized,
			Metadata:                 json.RawMessage(`{"source":"test"}`),
			InitializedAt:            &now,
			InitializedByPrincipalID: &setupBy,
			CreatedAt:                now,
			UpdatedAt:                now,
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
	if got.InitializationState != systemdomain.InitializationStateInitialized {
		t.Fatalf("unexpected initialization state: %+v", got)
	}
	if got.InitializedAt == nil || !got.InitializedAt.Equal(now) {
		t.Fatalf("unexpected initialized time: %+v", got)
	}
	if got.InitializedByPrincipalID == nil || *got.InitializedByPrincipalID != setupBy {
		t.Fatalf("unexpected initialized principal: %+v", got)
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
		InitializationState:      systemdomain.InitializationStateInitialized,
		Metadata:                 json.RawMessage(`{"allow_self_register":true}`),
		InitializedAt:            &now,
		InitializedByPrincipalID: &setupBy,
	})
	if err != nil {
		t.Fatalf("upsert installation: %v", err)
	}

	if len(store.upserts) != 1 {
		t.Fatalf("expected one upsert, got %d", len(store.upserts))
	}
	recorded := store.upserts[0]
	if recorded.InitializationState != systemdomain.InitializationStateInitialized {
		t.Fatalf("unexpected recorded initialization state: %+v", recorded)
	}
	if recorded.InitializedAt == nil || !recorded.InitializedAt.Equal(now) {
		t.Fatalf("unexpected recorded initialized time: %+v", recorded)
	}
	if recorded.InitializedByPrincipalID == nil || *recorded.InitializedByPrincipalID != setupBy {
		t.Fatalf("unexpected recorded initialized principal: %+v", recorded)
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
		InitializationState: systemdomain.InitializationStateUninitialized,
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
		InitializationState:      systemdomain.InitializationStateInitialized,
		Metadata:                 json.RawMessage(`{"mode":"safe"}`),
		InitializedAt:            &now,
		InitializedByPrincipalID: &setupBy,
	}

	updated, err := service.Upsert(context.Background(), params)
	if err != nil {
		t.Fatalf("upsert installation: %v", err)
	}

	now = now.Add(2 * time.Hour)
	setupBy = uuid.MustParse("00000000-0000-0000-0000-000000000706")

	recorded := store.upserts[0]
	if recorded.InitializedAt == nil || recorded.InitializedAt.Hour() != 16 {
		t.Fatalf("expected stored initialized time to stay isolated, got %+v", recorded.InitializedAt)
	}
	if recorded.InitializedByPrincipalID == nil || *recorded.InitializedByPrincipalID == setupBy {
		t.Fatalf("expected stored initialized principal to stay isolated, got %+v", recorded.InitializedByPrincipalID)
	}
	if updated == nil || updated.InitializedAt == nil || updated.InitializedAt.Hour() != 16 {
		t.Fatalf("expected returned initialized time to stay isolated, got %+v", updated)
	}
	if updated.InitializedByPrincipalID == nil || *updated.InitializedByPrincipalID == setupBy {
		t.Fatalf("expected returned initialized principal to stay isolated, got %+v", updated.InitializedByPrincipalID)
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
		ID:                       uuid.MustParse("00000000-0000-0000-0000-000000000704"),
		InitializationState:      params.InitializationState,
		Metadata:                 append(json.RawMessage(nil), params.Metadata...),
		InitializedAt:            cloneTime(params.InitializedAt),
		InitializedByPrincipalID: cloneUUID(params.InitializedByPrincipalID),
		CreatedAt:                now,
		UpdatedAt:                now,
	}
	return cloneInstallation(s.current), nil
}

func cloneInstallation(value *systemdomain.Installation) *systemdomain.Installation {
	if value == nil {
		return nil
	}
	copy := *value
	copy.Metadata = append(json.RawMessage(nil), value.Metadata...)
	copy.InitializedAt = cloneTime(value.InitializedAt)
	copy.InitializedByPrincipalID = cloneUUID(value.InitializedByPrincipalID)
	return &copy
}

func cloneUpsertInstallationParams(value UpsertInstallationParams) UpsertInstallationParams {
	value.Metadata = append(json.RawMessage(nil), value.Metadata...)
	value.InitializedAt = cloneTime(value.InitializedAt)
	value.InitializedByPrincipalID = cloneUUID(value.InitializedByPrincipalID)
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
