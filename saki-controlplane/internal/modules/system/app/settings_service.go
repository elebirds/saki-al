package app

import (
	"context"
	"encoding/json"

	systemdomain "github.com/elebirds/saki/saki-controlplane/internal/modules/system/domain"
	"github.com/google/uuid"
)

type Store interface {
	ListSettings(ctx context.Context, installationID uuid.UUID) ([]systemdomain.Setting, error)
}

type SettingsService struct {
	store Store
}

func NewSettingsService(store Store) *SettingsService {
	return &SettingsService{store: store}
}

func (s *SettingsService) ListValues(ctx context.Context, installationID uuid.UUID) (map[string]json.RawMessage, error) {
	settings, err := s.store.ListSettings(ctx, installationID)
	if err != nil {
		return nil, err
	}

	values := make(map[string]json.RawMessage, len(settings))
	for _, setting := range settings {
		values[setting.Key] = append(json.RawMessage(nil), setting.Value...)
	}
	return values, nil
}

func (s *SettingsService) GetBool(ctx context.Context, installationID uuid.UUID, key string, defaultValue bool) (bool, error) {
	values, err := s.ListValues(ctx, installationID)
	if err != nil {
		return false, err
	}
	raw, ok := values[key]
	if !ok {
		return defaultValue, nil
	}

	var value bool
	if err := json.Unmarshal(raw, &value); err != nil {
		return false, err
	}
	return value, nil
}
