package app

import (
	"context"
	"errors"

	datasetrepo "github.com/elebirds/saki/saki-controlplane/internal/modules/dataset/repo"
	"github.com/google/uuid"
)

var ErrProjectNotFound = errors.New("project not found")
var ErrDatasetNotFound = errors.New("dataset not found")

type DatasetStore interface {
	Get(ctx context.Context, id uuid.UUID) (*datasetrepo.Dataset, error)
}

type LinkedDataset struct {
	ID   uuid.UUID
	Name string
	Type string
}

type LinkProjectDatasetsUseCase struct {
	projects Store
	datasets DatasetStore
}

func NewLinkProjectDatasetsUseCase(projects Store, datasets DatasetStore) *LinkProjectDatasetsUseCase {
	return &LinkProjectDatasetsUseCase{
		projects: projects,
		datasets: datasets,
	}
}

func (u *LinkProjectDatasetsUseCase) Execute(ctx context.Context, projectID uuid.UUID, datasetIDs []uuid.UUID) ([]uuid.UUID, error) {
	if err := ensureProjectExists(ctx, u.projects, projectID); err != nil {
		return nil, err
	}

	requestedIDs := uniqueUUIDs(datasetIDs)
	for _, datasetID := range requestedIDs {
		dataset, err := u.datasets.Get(ctx, datasetID)
		if err != nil {
			return nil, err
		}
		if dataset == nil {
			return nil, ErrDatasetNotFound
		}
	}

	existingIDs, err := u.projects.ListProjectDatasetIDs(ctx, projectID)
	if err != nil {
		return nil, err
	}
	existing := make(map[uuid.UUID]struct{}, len(existingIDs))
	for _, datasetID := range existingIDs {
		existing[datasetID] = struct{}{}
	}

	linkedIDs := make([]uuid.UUID, 0, len(requestedIDs))
	for _, datasetID := range requestedIDs {
		if _, ok := existing[datasetID]; ok {
			continue
		}
		if _, err := u.projects.LinkDataset(ctx, projectID, datasetID); err != nil {
			return nil, err
		}
		existing[datasetID] = struct{}{}
		linkedIDs = append(linkedIDs, datasetID)
	}

	return linkedIDs, nil
}

type UnlinkProjectDatasetsUseCase struct {
	projects Store
}

func NewUnlinkProjectDatasetsUseCase(projects Store) *UnlinkProjectDatasetsUseCase {
	return &UnlinkProjectDatasetsUseCase{projects: projects}
}

func (u *UnlinkProjectDatasetsUseCase) Execute(ctx context.Context, projectID uuid.UUID, datasetIDs []uuid.UUID) (int, error) {
	if err := ensureProjectExists(ctx, u.projects, projectID); err != nil {
		return 0, err
	}

	count := 0
	for _, datasetID := range uniqueUUIDs(datasetIDs) {
		removed, err := u.projects.UnlinkDataset(ctx, projectID, datasetID)
		if err != nil {
			return 0, err
		}
		if removed {
			count++
		}
	}

	return count, nil
}

type ListProjectDatasetIDsUseCase struct {
	projects Store
}

func NewListProjectDatasetIDsUseCase(projects Store) *ListProjectDatasetIDsUseCase {
	return &ListProjectDatasetIDsUseCase{projects: projects}
}

func (u *ListProjectDatasetIDsUseCase) Execute(ctx context.Context, projectID uuid.UUID) ([]uuid.UUID, error) {
	if err := ensureProjectExists(ctx, u.projects, projectID); err != nil {
		return nil, err
	}
	return u.projects.ListProjectDatasetIDs(ctx, projectID)
}

type ListProjectDatasetDetailsUseCase struct {
	projects Store
	datasets DatasetStore
}

func NewListProjectDatasetDetailsUseCase(projects Store, datasets DatasetStore) *ListProjectDatasetDetailsUseCase {
	return &ListProjectDatasetDetailsUseCase{
		projects: projects,
		datasets: datasets,
	}
}

func (u *ListProjectDatasetDetailsUseCase) Execute(ctx context.Context, projectID uuid.UUID) ([]LinkedDataset, error) {
	if err := ensureProjectExists(ctx, u.projects, projectID); err != nil {
		return nil, err
	}

	ids, err := u.projects.ListProjectDatasetIDs(ctx, projectID)
	if err != nil {
		return nil, err
	}

	items := make([]LinkedDataset, 0, len(ids))
	for _, datasetID := range ids {
		dataset, err := u.datasets.Get(ctx, datasetID)
		if err != nil {
			return nil, err
		}
		if dataset == nil {
			continue
		}
		items = append(items, LinkedDataset{
			ID:   dataset.ID,
			Name: dataset.Name,
			Type: dataset.Type,
		})
	}

	return items, nil
}

func ensureProjectExists(ctx context.Context, projects Store, projectID uuid.UUID) error {
	project, err := projects.GetProject(ctx, projectID)
	if err != nil {
		return err
	}
	if project == nil {
		return ErrProjectNotFound
	}
	return nil
}

func uniqueUUIDs(ids []uuid.UUID) []uuid.UUID {
	if len(ids) == 0 {
		return nil
	}

	seen := make(map[uuid.UUID]struct{}, len(ids))
	result := make([]uuid.UUID, 0, len(ids))
	for _, id := range ids {
		if _, ok := seen[id]; ok {
			continue
		}
		seen[id] = struct{}{}
		result = append(result, id)
	}
	return result
}
