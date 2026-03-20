package app

import (
	"cmp"
	"context"
	"strings"

	systemdomain "github.com/elebirds/saki/saki-controlplane/internal/modules/system/domain"
	"github.com/google/uuid"
)

type InstallationGetter interface {
	Get(ctx context.Context) (*systemdomain.Installation, error)
}

type SettingBoolReader interface {
	GetBool(ctx context.Context, installationID uuid.UUID, key string, defaultValue bool) (bool, error)
}

type Status struct {
	InstallState      systemdomain.InstallationState
	AllowSelfRegister bool
	Version           string
}

type StatusUseCase struct {
	installations InstallationGetter
	settings      SettingBoolReader
	version       string
}

func NewStatusUseCase(installations InstallationGetter, settings SettingBoolReader, version string) *StatusUseCase {
	return &StatusUseCase{
		installations: installations,
		settings:      settings,
		version:       cmp.Or(strings.TrimSpace(version), "dev"),
	}
}

func (u *StatusUseCase) Execute(ctx context.Context) (*Status, error) {
	installation, err := u.installations.Get(ctx)
	if err != nil {
		return nil, err
	}

	status := &Status{
		InstallState: systemdomain.InstallationStateUninitialized,
		Version:      u.version,
	}
	if installation == nil {
		return status, nil
	}

	status.InstallState = installation.InstallState
	if status.InstallState == "" {
		status.InstallState = systemdomain.InstallationStateUninitialized
	}
	status.AllowSelfRegister, err = u.settings.GetBool(ctx, installation.ID, SettingKeyAuthAllowSelfRegister, false)
	if err != nil {
		return nil, err
	}
	return status, nil
}
