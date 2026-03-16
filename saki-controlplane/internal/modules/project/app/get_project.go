package app

import (
	"context"

	"github.com/google/uuid"
)

type GetProjectUseCase struct {
	store Store
}

func NewGetProjectUseCase(store Store) *GetProjectUseCase {
	return &GetProjectUseCase{store: store}
}

func (u *GetProjectUseCase) Execute(ctx context.Context, projectID uuid.UUID) (*Project, error) {
	return u.store.GetProject(ctx, projectID)
}
