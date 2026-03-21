package app

import (
	"context"
	"encoding/json"
	"testing"

	systemdomain "github.com/elebirds/saki/saki-controlplane/internal/modules/system/domain"
	"github.com/google/uuid"
)

func TestStatusUseCaseDefaultsToUninitializedWhenInstallationMissing(t *testing.T) {
	useCase := NewStatusUseCase(
		fakeStatusInstallationGetter{},
		&fakeStatusSettingReader{},
		"test-build",
	)

	status, err := useCase.Execute(t.Context())
	if err != nil {
		t.Fatalf("execute status: %v", err)
	}

	if status.InitializationState != systemdomain.InitializationStateUninitialized {
		t.Fatalf("unexpected initialization state: %+v", status)
	}
	if status.AllowSelfRegister {
		t.Fatalf("expected self register disabled by default: %+v", status)
	}
	if status.Version != "test-build" {
		t.Fatalf("unexpected version: %+v", status)
	}
}

func TestStatusUseCaseReadsAllowSelfRegisterFromSettings(t *testing.T) {
	installationID := uuid.MustParse("00000000-0000-0000-0000-000000001101")
	useCase := NewStatusUseCase(
		fakeStatusInstallationGetter{
			current: &systemdomain.Installation{
				ID:                  installationID,
				InitializationState: systemdomain.InitializationStateInitialized,
				Metadata:            json.RawMessage(`{}`),
			},
		},
		&fakeStatusSettingReader{
			values: map[string]bool{
				SettingKeyAuthAllowSelfRegister: true,
			},
		},
		"v2026.03.20",
	)

	status, err := useCase.Execute(t.Context())
	if err != nil {
		t.Fatalf("execute status: %v", err)
	}

	if status.InitializationState != systemdomain.InitializationStateInitialized {
		t.Fatalf("unexpected initialization state: %+v", status)
	}
	if !status.AllowSelfRegister {
		t.Fatalf("expected self register to be loaded from settings: %+v", status)
	}
	if status.Version != "v2026.03.20" {
		t.Fatalf("unexpected version: %+v", status)
	}
}

type fakeStatusInstallationGetter struct {
	current *systemdomain.Installation
}

func (f fakeStatusInstallationGetter) Get(context.Context) (*systemdomain.Installation, error) {
	if f.current == nil {
		return nil, nil
	}
	copy := *f.current
	copy.Metadata = append(json.RawMessage(nil), f.current.Metadata...)
	return &copy, nil
}

type fakeStatusSettingReader struct {
	values map[string]bool
}

func (f *fakeStatusSettingReader) GetBool(_ context.Context, _ uuid.UUID, key string, defaultValue bool) (bool, error) {
	if value, ok := f.values[key]; ok {
		return value, nil
	}
	return defaultValue, nil
}
