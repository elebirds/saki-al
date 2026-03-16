package app

import (
	"context"
	"sync"

	"github.com/google/uuid"

	projectrepo "github.com/elebirds/saki/saki-controlplane/internal/modules/project/repo"
)

type Project struct {
	ID   uuid.UUID
	Name string
}

type Store interface {
	CreateProject(ctx context.Context, name string) (*Project, error)
	ListProjects(ctx context.Context) ([]Project, error)
	GetProject(ctx context.Context, id uuid.UUID) (*Project, error)
}

type CreateProjectUseCase struct {
	store Store
}

func NewCreateProjectUseCase(store Store) *CreateProjectUseCase {
	return &CreateProjectUseCase{store: store}
}

func (u *CreateProjectUseCase) Execute(ctx context.Context, name string) (*Project, error) {
	return u.store.CreateProject(ctx, name)
}

type MemoryStore struct {
	mu       sync.RWMutex
	projects map[uuid.UUID]Project
	order    []uuid.UUID
}

func NewMemoryStore() *MemoryStore {
	return &MemoryStore{
		projects: make(map[uuid.UUID]Project),
	}
}

func (s *MemoryStore) CreateProject(_ context.Context, name string) (*Project, error) {
	s.mu.Lock()
	defer s.mu.Unlock()

	project := Project{
		ID:   uuid.New(),
		Name: name,
	}
	s.projects[project.ID] = project
	s.order = append(s.order, project.ID)

	return &project, nil
}

func (s *MemoryStore) ListProjects(context.Context) ([]Project, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()

	projects := make([]Project, 0, len(s.order))
	for _, id := range s.order {
		projects = append(projects, s.projects[id])
	}

	return projects, nil
}

func (s *MemoryStore) GetProject(_ context.Context, id uuid.UUID) (*Project, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()

	project, ok := s.projects[id]
	if !ok {
		return nil, nil
	}

	copy := project
	return &copy, nil
}

type RepoStore struct {
	repo *projectrepo.ProjectRepo
}

func NewRepoStore(repo *projectrepo.ProjectRepo) *RepoStore {
	return &RepoStore{repo: repo}
}

func (s *RepoStore) CreateProject(ctx context.Context, name string) (*Project, error) {
	project, err := s.repo.CreateProject(ctx, projectrepo.CreateProjectParams{Name: name})
	if err != nil {
		return nil, err
	}

	return &Project{
		ID:   project.ID,
		Name: project.Name,
	}, nil
}

func (s *RepoStore) ListProjects(ctx context.Context) ([]Project, error) {
	projects, err := s.repo.ListProjects(ctx)
	if err != nil {
		return nil, err
	}

	result := make([]Project, 0, len(projects))
	for _, project := range projects {
		result = append(result, Project{
			ID:   project.ID,
			Name: project.Name,
		})
	}

	return result, nil
}

func (s *RepoStore) GetProject(ctx context.Context, id uuid.UUID) (*Project, error) {
	project, err := s.repo.GetProject(ctx, id)
	if err != nil || project == nil {
		return nil, err
	}

	return &Project{
		ID:   project.ID,
		Name: project.Name,
	}, nil
}
