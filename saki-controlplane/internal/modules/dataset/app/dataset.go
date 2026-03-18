package app

import (
	"context"
	"errors"
	"slices"
	"sort"
	"strings"
	"sync"
	"time"

	datasetrepo "github.com/elebirds/saki/saki-controlplane/internal/modules/dataset/repo"
	"github.com/google/uuid"
)

var ErrInvalidDatasetInput = errors.New("invalid dataset input")
var ErrInvalidDataset = ErrInvalidDatasetInput

type Dataset struct {
	ID   uuid.UUID
	Name string
	Type string
}

type CreateDatasetInput struct {
	Name string
	Type string
}

type UpdateDatasetInput struct {
	ID   uuid.UUID
	Name string
	Type string
}

type ListDatasetsInput struct {
	Page  int
	Limit int
	Query string
}

type ListDatasetsResult struct {
	Items   []Dataset
	Total   int
	Offset  int
	Limit   int
	Size    int
	HasMore bool
}

type Store interface {
	Create(ctx context.Context, params datasetrepo.CreateDatasetParams) (*datasetrepo.Dataset, error)
	Get(ctx context.Context, id uuid.UUID) (*datasetrepo.Dataset, error)
	List(ctx context.Context, params datasetrepo.ListDatasetsParams) (*datasetrepo.DatasetPage, error)
	Update(ctx context.Context, params datasetrepo.UpdateDatasetParams) (*datasetrepo.Dataset, error)
	Delete(ctx context.Context, id uuid.UUID) (bool, error)
}

type CreateDatasetUseCase struct {
	store Store
}

func NewCreateDatasetUseCase(store Store) *CreateDatasetUseCase {
	return &CreateDatasetUseCase{store: store}
}

func (u *CreateDatasetUseCase) Execute(ctx context.Context, input CreateDatasetInput) (*Dataset, error) {
	name, dtype, err := normalizeDatasetFields(input.Name, input.Type)
	if err != nil {
		return nil, err
	}
	created, err := u.store.Create(ctx, datasetrepo.CreateDatasetParams{
		Name: name,
		Type: dtype,
	})
	if err != nil {
		return nil, err
	}
	return fromRepoDataset(created), nil
}

type ListDatasetsUseCase struct {
	store Store
}

func NewListDatasetsUseCase(store Store) *ListDatasetsUseCase {
	return &ListDatasetsUseCase{store: store}
}

func (u *ListDatasetsUseCase) Execute(ctx context.Context, input ListDatasetsInput) (*ListDatasetsResult, error) {
	params := normalizeListDatasetsInput(input)
	page, err := u.store.List(ctx, params)
	if err != nil {
		return nil, err
	}
	if page == nil {
		return &ListDatasetsResult{
			Items:   nil,
			Total:   0,
			Offset:  params.Offset,
			Limit:   params.Limit,
			Size:    0,
			HasMore: false,
		}, nil
	}

	items := make([]Dataset, 0, len(page.Items))
	for i := range page.Items {
		items = append(items, *fromRepoDataset(&page.Items[i]))
	}

	return &ListDatasetsResult{
		Items:   items,
		Total:   page.Total,
		Offset:  page.Offset,
		Limit:   page.Limit,
		Size:    len(items),
		HasMore: page.Offset+len(items) < page.Total,
	}, nil
}

type GetDatasetUseCase struct {
	store Store
}

func NewGetDatasetUseCase(store Store) *GetDatasetUseCase {
	return &GetDatasetUseCase{store: store}
}

func (u *GetDatasetUseCase) Execute(ctx context.Context, id uuid.UUID) (*Dataset, error) {
	row, err := u.store.Get(ctx, id)
	if err != nil || row == nil {
		return nil, err
	}
	return fromRepoDataset(row), nil
}

type UpdateDatasetUseCase struct {
	store Store
}

func NewUpdateDatasetUseCase(store Store) *UpdateDatasetUseCase {
	return &UpdateDatasetUseCase{store: store}
}

func (u *UpdateDatasetUseCase) Execute(ctx context.Context, input UpdateDatasetInput) (*Dataset, error) {
	name, dtype, err := normalizeDatasetFields(input.Name, input.Type)
	if err != nil {
		return nil, err
	}
	row, err := u.store.Update(ctx, datasetrepo.UpdateDatasetParams{
		ID:   input.ID,
		Name: name,
		Type: dtype,
	})
	if err != nil || row == nil {
		return nil, err
	}
	return fromRepoDataset(row), nil
}

type MemoryStore struct {
	mu    sync.RWMutex
	items map[uuid.UUID]datasetrepo.Dataset
}

func NewMemoryStore() *MemoryStore {
	return &MemoryStore{
		items: make(map[uuid.UUID]datasetrepo.Dataset),
	}
}

func (s *MemoryStore) Create(_ context.Context, params datasetrepo.CreateDatasetParams) (*datasetrepo.Dataset, error) {
	s.mu.Lock()
	defer s.mu.Unlock()

	now := time.Now().UTC()
	dataset := datasetrepo.Dataset{
		ID:        uuid.New(),
		Name:      params.Name,
		Type:      params.Type,
		CreatedAt: now,
		UpdatedAt: now,
	}
	s.items[dataset.ID] = dataset

	copy := dataset
	return &copy, nil
}

func (s *MemoryStore) Get(_ context.Context, id uuid.UUID) (*datasetrepo.Dataset, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()

	dataset, ok := s.items[id]
	if !ok {
		return nil, nil
	}
	copy := dataset
	return &copy, nil
}

func (s *MemoryStore) List(_ context.Context, params datasetrepo.ListDatasetsParams) (*datasetrepo.DatasetPage, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()

	query := strings.ToLower(strings.TrimSpace(params.Query))
	items := make([]datasetrepo.Dataset, 0, len(s.items))
	for _, dataset := range s.items {
		if query != "" && !strings.Contains(strings.ToLower(dataset.Name), query) {
			continue
		}
		items = append(items, dataset)
	}

	sort.Slice(items, func(i, j int) bool {
		if items[i].Name != items[j].Name {
			return items[i].Name < items[j].Name
		}
		return items[i].ID.String() < items[j].ID.String()
	})

	total := len(items)
	start := min(max(params.Offset, 0), total)
	end := min(start+max(params.Limit, 0), total)
	pageItems := slices.Clone(items[start:end])

	return &datasetrepo.DatasetPage{
		Items:  pageItems,
		Total:  total,
		Offset: params.Offset,
		Limit:  params.Limit,
	}, nil
}

func (s *MemoryStore) Update(_ context.Context, params datasetrepo.UpdateDatasetParams) (*datasetrepo.Dataset, error) {
	s.mu.Lock()
	defer s.mu.Unlock()

	dataset, ok := s.items[params.ID]
	if !ok {
		return nil, nil
	}

	dataset.Name = params.Name
	dataset.Type = params.Type
	dataset.UpdatedAt = time.Now().UTC()
	s.items[params.ID] = dataset

	copy := dataset
	return &copy, nil
}

func (s *MemoryStore) Delete(_ context.Context, id uuid.UUID) (bool, error) {
	s.mu.Lock()
	defer s.mu.Unlock()

	_, ok := s.items[id]
	delete(s.items, id)
	return ok, nil
}

type RepoStore struct {
	repo *datasetrepo.DatasetRepo
}

func NewRepoStore(repo *datasetrepo.DatasetRepo) *RepoStore {
	return &RepoStore{repo: repo}
}

func (s *RepoStore) Create(ctx context.Context, params datasetrepo.CreateDatasetParams) (*datasetrepo.Dataset, error) {
	return s.repo.Create(ctx, params)
}

func (s *RepoStore) Get(ctx context.Context, id uuid.UUID) (*datasetrepo.Dataset, error) {
	return s.repo.Get(ctx, id)
}

func (s *RepoStore) List(ctx context.Context, params datasetrepo.ListDatasetsParams) (*datasetrepo.DatasetPage, error) {
	return s.repo.List(ctx, params)
}

func (s *RepoStore) Update(ctx context.Context, params datasetrepo.UpdateDatasetParams) (*datasetrepo.Dataset, error) {
	return s.repo.Update(ctx, params)
}

func (s *RepoStore) Delete(ctx context.Context, id uuid.UUID) (bool, error) {
	return s.repo.Delete(ctx, id)
}

func normalizeDatasetFields(name, dtype string) (string, string, error) {
	normalizedName := strings.TrimSpace(name)
	normalizedType := strings.TrimSpace(dtype)
	if normalizedName == "" || normalizedType == "" {
		return "", "", ErrInvalidDatasetInput
	}
	return normalizedName, normalizedType, nil
}

func normalizeListDatasetsInput(input ListDatasetsInput) datasetrepo.ListDatasetsParams {
	page := input.Page
	if page <= 0 {
		page = 1
	}

	limit := input.Limit
	if limit <= 0 {
		limit = 20
	}
	if limit > 200 {
		limit = 200
	}

	return datasetrepo.ListDatasetsParams{
		Query:  strings.TrimSpace(input.Query),
		Offset: (page - 1) * limit,
		Limit:  limit,
	}
}

func fromRepoDataset(row *datasetrepo.Dataset) *Dataset {
	if row == nil {
		return nil
	}
	return &Dataset{
		ID:   row.ID,
		Name: row.Name,
		Type: row.Type,
	}
}
