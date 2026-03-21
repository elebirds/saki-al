package apihttp

import (
	"github.com/elebirds/saki/saki-controlplane/internal/modules/identity/app"
	"github.com/google/uuid"
)

func parsePrincipalID(raw string) (uuid.UUID, error) {
	principalID, err := uuid.Parse(raw)
	if err != nil {
		return uuid.Nil, app.ErrInvalidUserInput
	}
	return principalID, nil
}

func optStringPtr(value string, ok bool) *string {
	if !ok {
		return nil
	}
	copy := value
	return &copy
}

func optBoolPtr(value bool, ok bool) *bool {
	if !ok {
		return nil
	}
	copy := value
	return &copy
}
