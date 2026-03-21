package app

import (
	"context"
	"encoding/json"
	"testing"

	systemdomain "github.com/elebirds/saki/saki-controlplane/internal/modules/system/domain"
	"github.com/google/uuid"
)

func TestSettingsUseCaseGetBundleMergesSchemaDefaultsAndStoredValues(t *testing.T) {
	installationID := uuid.MustParse("00000000-0000-0000-0000-000000001201")
	store := &fakeSettingsUseCaseStore{
		settings: []systemdomain.Setting{
			{
				InstallationID: installationID,
				Key:            SettingKeyAuthAllowSelfRegister,
				Value:          json.RawMessage(`true`),
			},
		},
	}
	useCase := NewSettingsUseCase(
		fakeSettingsInstallationGetter{
			current: &systemdomain.Installation{
				ID:                  installationID,
				InitializationState: systemdomain.InitializationStateInitialized,
			},
		},
		store,
	)

	bundle, err := useCase.GetBundle(t.Context())
	if err != nil {
		t.Fatalf("get bundle: %v", err)
	}

	if len(bundle.Schema) == 0 {
		t.Fatal("expected non-empty setting schema")
	}
	if got := string(bundle.Values[SettingKeyAuthAllowSelfRegister]); got != "true" {
		t.Fatalf("expected stored bool to override default, got %s", got)
	}
	if _, ok := bundle.Values[SettingKeyGeneralAppTitle]; !ok {
		t.Fatalf("expected effective values to include defaults, got %+v", bundle.Values)
	}
}

func TestSettingsUseCasePatchValidatesAndPersistsNormalizedValues(t *testing.T) {
	installationID := uuid.MustParse("00000000-0000-0000-0000-000000001202")
	store := &fakeSettingsUseCaseStore{}
	useCase := NewSettingsUseCase(
		fakeSettingsInstallationGetter{
			current: &systemdomain.Installation{
				ID:                  installationID,
				InitializationState: systemdomain.InitializationStateInitialized,
			},
		},
		store,
	)

	bundle, err := useCase.Patch(t.Context(), map[string]json.RawMessage{
		SettingKeyAuthAllowSelfRegister: json.RawMessage(`true`),
		SettingKeyImportMaxZipBytes:     json.RawMessage(`1073741824`),
	})
	if err != nil {
		t.Fatalf("patch settings: %v", err)
	}

	if len(store.upserts) != 2 {
		t.Fatalf("expected two upserts, got %+v", store.upserts)
	}
	if got := string(bundle.Values[SettingKeyAuthAllowSelfRegister]); got != "true" {
		t.Fatalf("unexpected bool in bundle: %+v", bundle.Values)
	}
	if got := string(bundle.Values[SettingKeyImportMaxZipBytes]); got != "1073741824" {
		t.Fatalf("unexpected integer in bundle: %+v", bundle.Values)
	}
}

func TestSettingsUseCasePatchRejectsUnknownKey(t *testing.T) {
	installationID := uuid.MustParse("00000000-0000-0000-0000-000000001203")
	store := &fakeSettingsUseCaseStore{}
	useCase := NewSettingsUseCase(
		fakeSettingsInstallationGetter{
			current: &systemdomain.Installation{
				ID:                  installationID,
				InitializationState: systemdomain.InitializationStateInitialized,
			},
		},
		store,
	)

	_, err := useCase.Patch(t.Context(), map[string]json.RawMessage{
		"unknown.key": json.RawMessage(`true`),
	})
	if err == nil {
		t.Fatal("expected unknown key to fail")
	}
	if len(store.upserts) != 0 {
		t.Fatalf("expected validation failure to avoid partial writes, got %+v", store.upserts)
	}
}

func TestSettingsUseCaseGetBundleIgnoresUnknownStoredKeys(t *testing.T) {
	installationID := uuid.MustParse("00000000-0000-0000-0000-000000001204")
	store := &fakeSettingsUseCaseStore{
		settings: []systemdomain.Setting{
			{
				InstallationID: installationID,
				Key:            "legacy.removed_key",
				Value:          json.RawMessage(`true`),
			},
		},
	}
	useCase := NewSettingsUseCase(
		fakeSettingsInstallationGetter{
			current: &systemdomain.Installation{
				ID:                  installationID,
				InitializationState: systemdomain.InitializationStateInitialized,
			},
		},
		store,
	)

	bundle, err := useCase.GetBundle(t.Context())
	if err != nil {
		t.Fatalf("get bundle: %v", err)
	}
	if _, ok := bundle.Values["legacy.removed_key"]; ok {
		t.Fatalf("expected unknown stored key to be ignored, got %+v", bundle.Values)
	}
}

type fakeSettingsInstallationGetter struct {
	current *systemdomain.Installation
}

func (f fakeSettingsInstallationGetter) Get(context.Context) (*systemdomain.Installation, error) {
	if f.current == nil {
		return nil, nil
	}
	copy := *f.current
	copy.Metadata = append(json.RawMessage(nil), f.current.Metadata...)
	return &copy, nil
}

type fakeSettingsUseCaseStore struct {
	settings []systemdomain.Setting
	upserts  []systemdomain.Setting
}

func (f *fakeSettingsUseCaseStore) ListSettings(_ context.Context, installationID uuid.UUID) ([]systemdomain.Setting, error) {
	result := make([]systemdomain.Setting, 0, len(f.settings))
	for _, setting := range f.settings {
		if setting.InstallationID == installationID {
			copy := setting
			copy.Value = append(json.RawMessage(nil), setting.Value...)
			result = append(result, copy)
		}
	}
	return result, nil
}

func (f *fakeSettingsUseCaseStore) UpsertSetting(_ context.Context, installationID uuid.UUID, key string, value json.RawMessage) (*systemdomain.Setting, error) {
	record := systemdomain.Setting{
		InstallationID: installationID,
		Key:            key,
		Value:          append(json.RawMessage(nil), value...),
	}
	f.upserts = append(f.upserts, record)

	replaced := false
	for idx, setting := range f.settings {
		if setting.InstallationID == installationID && setting.Key == key {
			f.settings[idx] = record
			replaced = true
			break
		}
	}
	if !replaced {
		f.settings = append(f.settings, record)
	}
	return &record, nil
}

func (f *fakeSettingsUseCaseStore) UpsertSettings(ctx context.Context, installationID uuid.UUID, values map[string]json.RawMessage) error {
	for key, value := range values {
		if _, err := f.UpsertSetting(ctx, installationID, key, value); err != nil {
			return err
		}
	}
	return nil
}
