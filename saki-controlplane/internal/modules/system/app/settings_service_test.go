package app

import (
	"context"
	"encoding/json"
	"slices"
	"testing"

	systemdomain "github.com/elebirds/saki/saki-controlplane/internal/modules/system/domain"
	"github.com/google/uuid"
)

func TestSettingsServiceListsValuesAndReadsBool(t *testing.T) {
	installationID := uuid.MustParse("00000000-0000-0000-0000-000000000901")
	store := &fakeSettingsStore{
		settings: []systemdomain.Setting{
			{InstallationID: installationID, Key: "allow_self_register", Value: json.RawMessage(`true`)},
			{InstallationID: installationID, Key: "ui_title", Value: json.RawMessage(`"Saki"`)}},
	}

	service := NewSettingsService(store)

	values, err := service.ListValues(context.Background(), installationID)
	if err != nil {
		t.Fatalf("list values: %v", err)
	}
	if got, ok := values["allow_self_register"]; !ok || string(got) != "true" {
		t.Fatalf("unexpected bool value map: %+v", values)
	}

	keys := make([]string, 0, len(values))
	for key := range values {
		keys = append(keys, key)
	}
	slices.Sort(keys)
	if !slices.Equal(keys, []string{"allow_self_register", "ui_title"}) {
		t.Fatalf("unexpected keys: %v", keys)
	}

	enabled, err := service.GetBool(context.Background(), installationID, "allow_self_register", false)
	if err != nil {
		t.Fatalf("get bool: %v", err)
	}
	if !enabled {
		t.Fatal("expected stored bool setting to be true")
	}

	fallback, err := service.GetBool(context.Background(), installationID, "missing", true)
	if err != nil {
		t.Fatalf("get missing bool: %v", err)
	}
	if !fallback {
		t.Fatal("expected missing bool setting to use default")
	}
}

type fakeSettingsStore struct {
	settings []systemdomain.Setting
}

func (s *fakeSettingsStore) ListSettings(_ context.Context, installationID uuid.UUID) ([]systemdomain.Setting, error) {
	var result []systemdomain.Setting
	for _, setting := range s.settings {
		if setting.InstallationID == installationID {
			result = append(result, setting)
		}
	}
	return result, nil
}
