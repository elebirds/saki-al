package app

import "context"

type ListProjectsUseCase struct {
	store Store
}

func NewListProjectsUseCase(store Store) *ListProjectsUseCase {
	return &ListProjectsUseCase{store: store}
}

func (u *ListProjectsUseCase) Execute(ctx context.Context) ([]Project, error) {
	return u.store.ListProjects(ctx)
}
