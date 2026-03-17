package app

import (
	"context"
	"errors"
	"testing"

	importrepo "github.com/elebirds/saki/saki-controlplane/internal/modules/importing/repo"
	"github.com/google/uuid"
	"github.com/saki-ai/saki/shared/saki-ir/go/formats/common"
)

func TestMatchSampleRefPrefersDatasetRelpath(t *testing.T) {
	t.Parallel()

	datasetID := uuid.New()
	sampleID := uuid.New()
	store := fakeMatchStore{
		rows: map[string][]importrepo.SampleMatchRef{
			matchKey(datasetID, "dataset_relpath", "images/train/sample-1.jpg"): {
				{SampleID: sampleID, RefType: "dataset_relpath", RefValue: "images/train/sample-1.jpg"},
			},
		},
	}

	ref, err := common.NewSampleRef(common.SampleRefTypeDatasetRelpath, "images/train/sample-1.jpg")
	if err != nil {
		t.Fatalf("NewSampleRef failed: %v", err)
	}

	decision, err := matchSampleRef(context.Background(), store, datasetID, ref)
	if err != nil {
		t.Fatalf("matchSampleRef failed: %v", err)
	}
	if got, want := decision.SampleID, sampleID; got != want {
		t.Fatalf("sample id got %s want %s", got, want)
	}
	if got, want := decision.Strategy, "dataset_relpath"; got != want {
		t.Fatalf("strategy got %q want %q", got, want)
	}
}

func TestMatchSampleRefFallsBackToSampleNameAndBasename(t *testing.T) {
	t.Parallel()

	datasetID := uuid.New()
	sampleID := uuid.New()
	store := fakeMatchStore{
		rows: map[string][]importrepo.SampleMatchRef{
			matchKey(datasetID, "sample_name", "sample-1"): {
				{SampleID: sampleID, RefType: "sample_name", RefValue: "sample-1"},
			},
		},
	}

	ref, err := common.NewSampleRef(common.SampleRefTypeDatasetRelpath, "images/train/sample-1.jpg")
	if err != nil {
		t.Fatalf("NewSampleRef failed: %v", err)
	}

	decision, err := matchSampleRef(context.Background(), store, datasetID, ref)
	if err != nil {
		t.Fatalf("matchSampleRef failed: %v", err)
	}
	if got, want := decision.SampleID, sampleID; got != want {
		t.Fatalf("sample id got %s want %s", got, want)
	}
	if got, want := decision.Strategy, "sample_name"; got != want {
		t.Fatalf("strategy got %q want %q", got, want)
	}

	store = fakeMatchStore{
		rows: map[string][]importrepo.SampleMatchRef{
			matchKey(datasetID, "basename", "sample-1.jpg"): {
				{SampleID: sampleID, RefType: "basename", RefValue: "sample-1.jpg"},
			},
		},
	}
	decision, err = matchSampleRef(context.Background(), store, datasetID, ref)
	if err != nil {
		t.Fatalf("matchSampleRef basename failed: %v", err)
	}
	if got, want := decision.Strategy, "basename"; got != want {
		t.Fatalf("strategy got %q want %q", got, want)
	}
	if decision.Warning == nil {
		t.Fatal("expected basename fallback warning")
	}
}

func TestMatchSampleRefRejectsAmbiguousFallback(t *testing.T) {
	t.Parallel()

	datasetID := uuid.New()
	store := fakeMatchStore{
		rows: map[string][]importrepo.SampleMatchRef{
			matchKey(datasetID, "basename", "sample-1.jpg"): {
				{SampleID: uuid.New(), RefType: "basename", RefValue: "sample-1.jpg"},
				{SampleID: uuid.New(), RefType: "basename", RefValue: "sample-1.jpg"},
			},
		},
	}

	ref, err := common.NewSampleRef(common.SampleRefTypeDatasetRelpath, "images/train/sample-1.jpg")
	if err != nil {
		t.Fatalf("NewSampleRef failed: %v", err)
	}

	_, err = matchSampleRef(context.Background(), store, datasetID, ref)
	if !errors.Is(err, ErrAmbiguousSampleMatch) {
		t.Fatalf("expected ErrAmbiguousSampleMatch, got %v", err)
	}
}

type fakeMatchStore struct {
	rows map[string][]importrepo.SampleMatchRef
	err  error
}

func (s fakeMatchStore) FindExact(ctx context.Context, datasetID uuid.UUID, refType, refValue string) ([]importrepo.SampleMatchRef, error) {
	if s.err != nil {
		return nil, s.err
	}
	return s.rows[matchKey(datasetID, refType, refValue)], nil
}

func matchKey(datasetID uuid.UUID, refType, refValue string) string {
	return datasetID.String() + "|" + refType + "|" + refValue
}
