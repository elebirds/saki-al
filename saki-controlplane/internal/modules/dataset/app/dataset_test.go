package app

import (
	"context"
	"testing"
)

func TestDatasetUseCasesCreateListGetUpdateDelete(t *testing.T) {
	store := NewMemoryStore()

	create := NewCreateDatasetUseCase(store)
	list := NewListDatasetsUseCase(store)
	get := NewGetDatasetUseCase(store)
	update := NewUpdateDatasetUseCase(store)
	remove := NewDeleteDatasetUseCase(store)

	created, err := create.Execute(context.Background(), CreateDatasetInput{
		Name: " dataset-a ",
		Type: " image ",
	})
	if err != nil {
		t.Fatalf("create dataset: %v", err)
	}
	if created.Name != "dataset-a" || created.Type != "image" {
		t.Fatalf("unexpected created dataset: %+v", created)
	}

	listed, err := list.Execute(context.Background(), ListDatasetsInput{})
	if err != nil {
		t.Fatalf("list datasets: %v", err)
	}
	if listed.Total != 1 || listed.Offset != 0 || listed.Limit != 20 || listed.Size != 1 || listed.HasMore {
		t.Fatalf("unexpected listed datasets envelope: %+v", listed)
	}
	if len(listed.Items) != 1 || listed.Items[0].ID != created.ID {
		t.Fatalf("unexpected listed datasets: %+v", listed.Items)
	}

	loaded, err := get.Execute(context.Background(), created.ID)
	if err != nil {
		t.Fatalf("get dataset: %v", err)
	}
	if loaded == nil || loaded.ID != created.ID {
		t.Fatalf("unexpected loaded dataset: %+v", loaded)
	}

	updated, err := update.Execute(context.Background(), UpdateDatasetInput{
		ID:   created.ID,
		Name: " dataset-b ",
		Type: " lidar ",
	})
	if err != nil {
		t.Fatalf("update dataset: %v", err)
	}
	if updated.Name != "dataset-b" || updated.Type != "lidar" {
		t.Fatalf("unexpected updated dataset: %+v", updated)
	}

	deletedOK, err := remove.Execute(context.Background(), created.ID)
	if err != nil {
		t.Fatalf("delete dataset: %v", err)
	}
	if !deletedOK {
		t.Fatal("expected delete to report success")
	}

	deleted, err := get.Execute(context.Background(), created.ID)
	if err != nil {
		t.Fatalf("get deleted dataset: %v", err)
	}
	if deleted != nil {
		t.Fatalf("expected dataset to be deleted, got %+v", deleted)
	}
}

func TestListDatasetsUseCaseNormalizesPaginationAndQuery(t *testing.T) {
	store := NewMemoryStore()
	create := NewCreateDatasetUseCase(store)
	list := NewListDatasetsUseCase(store)

	for _, input := range []CreateDatasetInput{
		{Name: "alpha", Type: "image"},
		{Name: "beta", Type: "image"},
		{Name: "alpine", Type: "image"},
	} {
		if _, err := create.Execute(context.Background(), input); err != nil {
			t.Fatalf("seed dataset: %v", err)
		}
	}

	result, err := list.Execute(context.Background(), ListDatasetsInput{
		Page:  2,
		Limit: 1,
		Query: " alp ",
	})
	if err != nil {
		t.Fatalf("list datasets: %v", err)
	}
	if result.Total != 2 || result.Offset != 1 || result.Limit != 1 || result.Size != 1 || result.HasMore {
		t.Fatalf("unexpected list result: %+v", result)
	}
	if len(result.Items) != 1 || result.Items[0].Name != "alpine" {
		t.Fatalf("unexpected list items: %+v", result.Items)
	}
}

func TestCreateDatasetRejectsEmptyNameOrType(t *testing.T) {
	store := NewMemoryStore()
	useCase := NewCreateDatasetUseCase(store)

	if _, err := useCase.Execute(context.Background(), CreateDatasetInput{Name: "   ", Type: "image"}); err == nil {
		t.Fatal("expected empty name to fail")
	}
	if _, err := useCase.Execute(context.Background(), CreateDatasetInput{Name: "dataset-a", Type: "   "}); err == nil {
		t.Fatal("expected empty type to fail")
	}
}
