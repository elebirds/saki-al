package app

import (
	"context"
	"errors"
)

var ErrMissingAccessStore = errors.New("access store is required")

type BootstrapSeedUseCase struct {
	store BootstrapStore
}

func NewBootstrapSeedUseCase(store BootstrapStore) *BootstrapSeedUseCase {
	return &BootstrapSeedUseCase{store: store}
}

func (u *BootstrapSeedUseCase) Execute(ctx context.Context, principals []BootstrapPrincipalSpec) error {
	if len(principals) == 0 {
		return nil
	}
	if u.store == nil {
		return ErrMissingAccessStore
	}

	for _, principal := range principals {
		if _, err := u.store.UpsertBootstrapPrincipal(ctx, principal); err != nil {
			return err
		}
	}
	return nil
}
