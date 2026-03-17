package app

import (
	"context"
	"errors"
	"testing"

	datasetrepo "github.com/elebirds/saki/saki-controlplane/internal/modules/dataset/repo"
	"github.com/google/uuid"
)

func TestCreateDatasetUseCaseTrimsAndValidates(t *testing.T) {
	store := &fakeDatasetStore{}
	uc := NewCreateDatasetUseCase(store)

	out, err := uc.Execute(context.Background(), CreateDatasetInput{
		Name: "  ds-a  ",
		Type: "  fedo  ",
	})
	if err != nil {
		t.Fatalf("execute: %v", err)
	}
	if !store.createCalled {
		t.Fatal("expected store CreateDataset to be called")
	}
	if store.createdName != "ds-a" || store.createdType != "fedo" {
		t.Fatalf("expected trimmed name/type, got name=%q type=%q", store.createdName, store.createdType)
	}
	if out == nil || out.Name != "ds-a" || out.Type != "fedo" {
		t.Fatalf("unexpected output: %+v", out)
	}
}

func TestCreateDatasetUseCaseRejectsBlankAfterTrim(t *testing.T) {
	store := &fakeDatasetStore{}
	uc := NewCreateDatasetUseCase(store)

	_, err := uc.Execute(context.Background(), CreateDatasetInput{
		Name: "   ",
		Type: "x",
	})
	if !errors.Is(err, ErrInvalidDataset) {
		t.Fatalf("expected ErrInvalidDataset, got %v", err)
	}
	if store.createCalled {
		t.Fatal("expected store CreateDataset not to be called")
	}
}

func TestUpdateDatasetUseCaseRejectsBlankAfterTrim(t *testing.T) {
	store := &fakeDatasetStore{}
	uc := NewUpdateDatasetUseCase(store)

	_, err := uc.Execute(context.Background(), UpdateDatasetInput{
		ID:   uuid.New(),
		Name: "ok",
		Type: "  ",
	})
	if !errors.Is(err, ErrInvalidDataset) {
		t.Fatalf("expected ErrInvalidDataset, got %v", err)
	}
	if store.updateCalled {
		t.Fatal("expected store UpdateDataset not to be called")
	}
}

func TestUpdateDatasetUseCaseTrimsAndValidates(t *testing.T) {
	store := &fakeDatasetStore{}
	uc := NewUpdateDatasetUseCase(store)

	id := uuid.New()
	out, err := uc.Execute(context.Background(), UpdateDatasetInput{
		ID:   id,
		Name: "  n  ",
		Type: "  t  ",
	})
	if err != nil {
		t.Fatalf("execute: %v", err)
	}
	if !store.updateCalled {
		t.Fatal("expected store UpdateDataset to be called")
	}
	if store.updatedID != id || store.updatedName != "n" || store.updatedType != "t" {
		t.Fatalf("unexpected store args: id=%s name=%q type=%q", store.updatedID, store.updatedName, store.updatedType)
	}
	if out == nil || out.ID != id || out.Name != "n" || out.Type != "t" {
		t.Fatalf("unexpected output: %+v", out)
	}
}

func TestListDatasetsUseCaseTrimsQueryAndCalculatesOffset(t *testing.T) {
	store := &fakeDatasetStore{
		listResult: &datasetrepo.DatasetPage{
			Items: []datasetrepo.Dataset{
				{ID: uuid.New(), Name: "alpine", Type: "image"},
			},
			Total:  2,
			Offset: 1,
			Limit:  1,
		},
	}
	uc := NewListDatasetsUseCase(store)

	out, err := uc.Execute(context.Background(), ListDatasetsInput{
		Page:  2,
		Limit: 1,
		Query: " alp ",
	})
	if err != nil {
		t.Fatalf("execute: %v", err)
	}
	if !store.listCalled {
		t.Fatal("expected store ListDatasets to be called")
	}
	if store.listQuery != "alp" || store.listOffset != 1 || store.listLimit != 1 {
		t.Fatalf("unexpected list params: query=%q offset=%d limit=%d", store.listQuery, store.listOffset, store.listLimit)
	}
	if out == nil || out.Total != 2 || out.Offset != 1 || out.Limit != 1 || out.Size != 1 || out.HasMore {
		t.Fatalf("unexpected output: %+v", out)
	}
	if len(out.Items) != 1 || out.Items[0].Name != "alpine" {
		t.Fatalf("unexpected output items: %+v", out.Items)
	}
}

type fakeDatasetStore struct {
	createCalled bool
	createdName  string
	createdType  string

	listCalled  bool
	listQuery   string
	listOffset  int
	listLimit   int
	listResult  *datasetrepo.DatasetPage

	updateCalled bool
	updatedID    uuid.UUID
	updatedName  string
	updatedType  string

	deleteCalled  bool
	deleteID      uuid.UUID
	deleteResult  bool
}

func (f *fakeDatasetStore) Create(_ context.Context, params datasetrepo.CreateDatasetParams) (*datasetrepo.Dataset, error) {
	f.createCalled = true
	f.createdName = params.Name
	f.createdType = params.Type
	return &datasetrepo.Dataset{ID: uuid.New(), Name: params.Name, Type: params.Type}, nil
}

func (f *fakeDatasetStore) Get(context.Context, uuid.UUID) (*datasetrepo.Dataset, error) {
	return nil, nil
}

func (f *fakeDatasetStore) List(_ context.Context, params datasetrepo.ListDatasetsParams) (*datasetrepo.DatasetPage, error) {
	f.listCalled = true
	f.listQuery = params.Query
	f.listOffset = params.Offset
	f.listLimit = params.Limit
	if f.listResult == nil {
		return &datasetrepo.DatasetPage{
			Items:  nil,
			Total:  0,
			Offset: params.Offset,
			Limit:  params.Limit,
		}, nil
	}
	return f.listResult, nil
}

func (f *fakeDatasetStore) Update(_ context.Context, params datasetrepo.UpdateDatasetParams) (*datasetrepo.Dataset, error) {
	f.updateCalled = true
	f.updatedID = params.ID
	f.updatedName = params.Name
	f.updatedType = params.Type
	return &datasetrepo.Dataset{ID: params.ID, Name: params.Name, Type: params.Type}, nil
}

func (f *fakeDatasetStore) Delete(_ context.Context, id uuid.UUID) (bool, error) {
	f.deleteCalled = true
	f.deleteID = id
	return f.deleteResult, nil
}
