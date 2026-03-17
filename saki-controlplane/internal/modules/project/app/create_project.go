package app

import (
	"context"
	"sort"
	"sync"
	"time"

	"github.com/google/uuid"

	projectrepo "github.com/elebirds/saki/saki-controlplane/internal/modules/project/repo"
)

type Project struct {
	ID        uuid.UUID
	Name      string
	CreatedAt time.Time
	UpdatedAt time.Time
}

type Store interface {
	CreateProject(ctx context.Context, name string) (*Project, error)
	ListProjects(ctx context.Context) ([]Project, error)
	GetProject(ctx context.Context, id uuid.UUID) (*Project, error)
	LinkDataset(ctx context.Context, projectID, datasetID uuid.UUID) (*projectrepo.ProjectDatasetLink, error)
	UnlinkDataset(ctx context.Context, projectID, datasetID uuid.UUID) (bool, error)
	ListProjectDatasetIDs(ctx context.Context, projectID uuid.UUID) ([]uuid.UUID, error)
	GetProjectDatasetLink(ctx context.Context, projectID, datasetID uuid.UUID) (*projectrepo.ProjectDatasetLink, error)
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
	links    map[string]projectrepo.ProjectDatasetLink
}

func NewMemoryStore() *MemoryStore {
	return &MemoryStore{
		projects: make(map[uuid.UUID]Project),
		links:    make(map[string]projectrepo.ProjectDatasetLink),
	}
}

func (s *MemoryStore) CreateProject(_ context.Context, name string) (*Project, error) {
	s.mu.Lock()
	defer s.mu.Unlock()

	project := Project{
		ID:        uuid.New(),
		Name:      name,
		CreatedAt: time.Now().UTC(),
		UpdatedAt: time.Now().UTC(),
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

func (s *MemoryStore) GetProjectDatasetLink(_ context.Context, projectID, datasetID uuid.UUID) (*projectrepo.ProjectDatasetLink, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()

	link, ok := s.links[projectDatasetKey(projectID, datasetID)]
	if !ok {
		return nil, nil
	}
	copy := link
	return &copy, nil
}

func (s *MemoryStore) LinkDataset(_ context.Context, projectID, datasetID uuid.UUID) (*projectrepo.ProjectDatasetLink, error) {
	s.mu.Lock()
	defer s.mu.Unlock()

	link := projectrepo.ProjectDatasetLink{
		ProjectID: projectID,
		DatasetID: datasetID,
		CreatedAt: time.Now().UTC(),
	}
	s.links[projectDatasetKey(projectID, datasetID)] = link
	copy := link
	return &copy, nil
}

func (s *MemoryStore) UnlinkDataset(_ context.Context, projectID, datasetID uuid.UUID) (bool, error) {
	s.mu.Lock()
	defer s.mu.Unlock()

	key := projectDatasetKey(projectID, datasetID)
	_, ok := s.links[key]
	delete(s.links, key)
	return ok, nil
}

func (s *MemoryStore) ListProjectDatasetIDs(_ context.Context, projectID uuid.UUID) ([]uuid.UUID, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()

	ids := make([]uuid.UUID, 0, len(s.links))
	for _, link := range s.links {
		if link.ProjectID == projectID {
			ids = append(ids, link.DatasetID)
		}
	}
	sort.Slice(ids, func(i, j int) bool {
		return ids[i].String() < ids[j].String()
	})
	return ids, nil
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
		ID:        project.ID,
		Name:      project.Name,
		CreatedAt: project.CreatedAt,
		UpdatedAt: project.UpdatedAt,
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
			ID:        project.ID,
			Name:      project.Name,
			CreatedAt: project.CreatedAt,
			UpdatedAt: project.UpdatedAt,
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
		ID:        project.ID,
		Name:      project.Name,
		CreatedAt: project.CreatedAt,
		UpdatedAt: project.UpdatedAt,
	}, nil
}

func (s *RepoStore) GetProjectDatasetLink(ctx context.Context, projectID, datasetID uuid.UUID) (*projectrepo.ProjectDatasetLink, error) {
	return s.repo.GetProjectDatasetLink(ctx, projectID, datasetID)
}

func (s *RepoStore) LinkDataset(ctx context.Context, projectID, datasetID uuid.UUID) (*projectrepo.ProjectDatasetLink, error) {
	return s.repo.LinkDataset(ctx, projectID, datasetID)
}

func (s *RepoStore) UnlinkDataset(ctx context.Context, projectID, datasetID uuid.UUID) (bool, error) {
	return s.repo.UnlinkDataset(ctx, projectID, datasetID)
}

func (s *RepoStore) ListProjectDatasetIDs(ctx context.Context, projectID uuid.UUID) ([]uuid.UUID, error) {
	return s.repo.ListProjectDatasetIDs(ctx, projectID)
}

func projectDatasetKey(projectID, datasetID uuid.UUID) string {
	return projectID.String() + "|" + datasetID.String()
}
