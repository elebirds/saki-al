package app

import (
	"context"
	"errors"
	"testing"

	datasetrepo "github.com/elebirds/saki/saki-controlplane/internal/modules/dataset/repo"
	projectrepo "github.com/elebirds/saki/saki-controlplane/internal/modules/project/repo"
	"github.com/google/uuid"
)

func TestProjectDatasetLinkUseCaseSkipsExistingLinksAndPreservesInputOrder(t *testing.T) {
	projectID := uuid.New()
	existingID := uuid.New()
	newID := uuid.New()

	projects := &fakeProjectDatasetStore{
		project: &Project{ID: projectID, Name: "project-a"},
		listIDs: []uuid.UUID{existingID},
	}
	datasets := &fakeProjectDatasetDatasetStore{
		items: map[uuid.UUID]*datasetrepo.Dataset{
			existingID: {ID: existingID, Name: "existing", Type: "image"},
			newID:      {ID: newID, Name: "new", Type: "image"},
		},
	}

	uc := NewLinkProjectDatasetsUseCase(projects, datasets)

	linkedIDs, err := uc.Execute(context.Background(), projectID, []uuid.UUID{existingID, newID, existingID})
	if err != nil {
		t.Fatalf("execute: %v", err)
	}
	if len(linkedIDs) != 1 || linkedIDs[0] != newID {
		t.Fatalf("unexpected linked ids: %+v", linkedIDs)
	}
	if len(projects.linkCalls) != 1 || projects.linkCalls[0] != newID {
		t.Fatalf("unexpected link calls: %+v", projects.linkCalls)
	}
	if len(datasets.getCalls) != 2 || datasets.getCalls[0] != existingID || datasets.getCalls[1] != newID {
		t.Fatalf("unexpected dataset get calls: %+v", datasets.getCalls)
	}
}

func TestProjectDatasetLinkUseCaseReturnsDatasetNotFound(t *testing.T) {
	projectID := uuid.New()
	missingID := uuid.New()

	projects := &fakeProjectDatasetStore{
		project: &Project{ID: projectID, Name: "project-a"},
	}
	datasets := &fakeProjectDatasetDatasetStore{}

	uc := NewLinkProjectDatasetsUseCase(projects, datasets)

	_, err := uc.Execute(context.Background(), projectID, []uuid.UUID{missingID})
	if !errors.Is(err, ErrDatasetNotFound) {
		t.Fatalf("expected ErrDatasetNotFound, got %v", err)
	}
	if len(projects.linkCalls) != 0 {
		t.Fatalf("expected no link calls, got %+v", projects.linkCalls)
	}
}

func TestProjectDatasetUnlinkUseCaseCountsRemovedLinks(t *testing.T) {
	projectID := uuid.New()
	datasetA := uuid.New()
	datasetB := uuid.New()

	projects := &fakeProjectDatasetStore{
		project:        &Project{ID: projectID, Name: "project-a"},
		unlinkResults:  map[uuid.UUID]bool{datasetA: true, datasetB: false},
	}
	uc := NewUnlinkProjectDatasetsUseCase(projects)

	count, err := uc.Execute(context.Background(), projectID, []uuid.UUID{datasetA, datasetB, datasetA})
	if err != nil {
		t.Fatalf("execute: %v", err)
	}
	if count != 1 {
		t.Fatalf("expected unlink count 1, got %d", count)
	}
	if len(projects.unlinkCalls) != 2 || projects.unlinkCalls[0] != datasetA || projects.unlinkCalls[1] != datasetB {
		t.Fatalf("unexpected unlink calls: %+v", projects.unlinkCalls)
	}
}

func TestProjectDatasetListUseCasesRequireExistingProject(t *testing.T) {
	projectID := uuid.New()

	linkUC := NewLinkProjectDatasetsUseCase(&fakeProjectDatasetStore{}, &fakeProjectDatasetDatasetStore{})
	if _, err := linkUC.Execute(context.Background(), projectID, []uuid.UUID{uuid.New()}); !errors.Is(err, ErrProjectNotFound) {
		t.Fatalf("expected ErrProjectNotFound from link, got %v", err)
	}

	unlinkUC := NewUnlinkProjectDatasetsUseCase(&fakeProjectDatasetStore{})
	if _, err := unlinkUC.Execute(context.Background(), projectID, []uuid.UUID{uuid.New()}); !errors.Is(err, ErrProjectNotFound) {
		t.Fatalf("expected ErrProjectNotFound from unlink, got %v", err)
	}

	listIDsUC := NewListProjectDatasetIDsUseCase(&fakeProjectDatasetStore{})
	if _, err := listIDsUC.Execute(context.Background(), projectID); !errors.Is(err, ErrProjectNotFound) {
		t.Fatalf("expected ErrProjectNotFound from list ids, got %v", err)
	}

	listDetailsUC := NewListProjectDatasetDetailsUseCase(&fakeProjectDatasetStore{}, &fakeProjectDatasetDatasetStore{})
	if _, err := listDetailsUC.Execute(context.Background(), projectID); !errors.Is(err, ErrProjectNotFound) {
		t.Fatalf("expected ErrProjectNotFound from list details, got %v", err)
	}
}

func TestProjectDatasetListDetailsUseCaseUsesProjectScopeAndSkipsMissingDatasets(t *testing.T) {
	projectID := uuid.New()
	datasetA := uuid.New()
	missingID := uuid.New()
	datasetB := uuid.New()

	projects := &fakeProjectDatasetStore{
		project: &Project{ID: projectID, Name: "project-a"},
		listIDs: []uuid.UUID{datasetA, missingID, datasetB},
	}
	datasets := &fakeProjectDatasetDatasetStore{
		items: map[uuid.UUID]*datasetrepo.Dataset{
			datasetA: {ID: datasetA, Name: "dataset-a", Type: "image"},
			datasetB: {ID: datasetB, Name: "dataset-b", Type: "video"},
		},
	}

	uc := NewListProjectDatasetDetailsUseCase(projects, datasets)

	items, err := uc.Execute(context.Background(), projectID)
	if err != nil {
		t.Fatalf("execute: %v", err)
	}
	if len(items) != 2 {
		t.Fatalf("expected 2 dataset details, got %+v", items)
	}
	if items[0].ID != datasetA || items[0].Name != "dataset-a" || items[0].Type != "image" {
		t.Fatalf("unexpected first dataset detail: %+v", items[0])
	}
	if items[1].ID != datasetB || items[1].Name != "dataset-b" || items[1].Type != "video" {
		t.Fatalf("unexpected second dataset detail: %+v", items[1])
	}
}

type fakeProjectDatasetStore struct {
	project *Project
	listIDs []uuid.UUID

	linkCalls []uuid.UUID

	unlinkCalls   []uuid.UUID
	unlinkResults map[uuid.UUID]bool
}

func (f *fakeProjectDatasetStore) CreateProject(context.Context, string) (*Project, error) {
	return nil, nil
}

func (f *fakeProjectDatasetStore) ListProjects(context.Context) ([]Project, error) {
	return nil, nil
}

func (f *fakeProjectDatasetStore) GetProject(_ context.Context, id uuid.UUID) (*Project, error) {
	if f.project == nil || f.project.ID != id {
		return nil, nil
	}
	copy := *f.project
	return &copy, nil
}

func (f *fakeProjectDatasetStore) LinkDataset(_ context.Context, projectID, datasetID uuid.UUID) (*projectrepo.ProjectDatasetLink, error) {
	f.linkCalls = append(f.linkCalls, datasetID)
	return &projectrepo.ProjectDatasetLink{
		ProjectID: projectID,
		DatasetID: datasetID,
	}, nil
}

func (f *fakeProjectDatasetStore) UnlinkDataset(_ context.Context, _, datasetID uuid.UUID) (bool, error) {
	f.unlinkCalls = append(f.unlinkCalls, datasetID)
	return f.unlinkResults[datasetID], nil
}

func (f *fakeProjectDatasetStore) ListProjectDatasetIDs(context.Context, uuid.UUID) ([]uuid.UUID, error) {
	return append([]uuid.UUID(nil), f.listIDs...), nil
}

func (f *fakeProjectDatasetStore) GetProjectDatasetLink(_ context.Context, projectID, datasetID uuid.UUID) (*projectrepo.ProjectDatasetLink, error) {
	for _, linkedID := range f.listIDs {
		if linkedID == datasetID {
			return &projectrepo.ProjectDatasetLink{
				ProjectID: projectID,
				DatasetID: datasetID,
			}, nil
		}
	}
	return nil, nil
}

type fakeProjectDatasetDatasetStore struct {
	items    map[uuid.UUID]*datasetrepo.Dataset
	getCalls []uuid.UUID
}

func (f *fakeProjectDatasetDatasetStore) Get(_ context.Context, id uuid.UUID) (*datasetrepo.Dataset, error) {
	f.getCalls = append(f.getCalls, id)
	if f.items == nil {
		return nil, nil
	}
	dataset := f.items[id]
	if dataset == nil {
		return nil, nil
	}
	copy := *dataset
	return &copy, nil
}
