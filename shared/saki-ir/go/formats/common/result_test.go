package common

import (
	"testing"

	annotationirv1 "github.com/saki-ai/saki/shared/saki-ir/go/gen/annotationirv1"
)

func TestNewSampleRefNormalizesByType(t *testing.T) {
	t.Parallel()

	pathRef, err := NewSampleRef(SampleRefTypeDatasetRelpath, "./images\\train\\sample-1.jpg")
	if err != nil {
		t.Fatalf("NewSampleRef(dataset_relpath) failed: %v", err)
	}
	if got, want := pathRef.NormalizedValue, "images/train/sample-1.jpg"; got != want {
		t.Fatalf("dataset_relpath normalized_value got %q want %q", got, want)
	}

	nameRef, err := NewSampleRef(SampleRefTypeSampleName, "  sample-1  ")
	if err != nil {
		t.Fatalf("NewSampleRef(sample_name) failed: %v", err)
	}
	if got, want := nameRef.NormalizedValue, "sample-1"; got != want {
		t.Fatalf("sample_name normalized_value got %q want %q", got, want)
	}

	baseRef, err := NewSampleRef(SampleRefTypeBasename, "images/train/sample-1.jpg")
	if err != nil {
		t.Fatalf("NewSampleRef(basename) failed: %v", err)
	}
	if got, want := baseRef.NormalizedValue, "sample-1.jpg"; got != want {
		t.Fatalf("basename normalized_value got %q want %q", got, want)
	}
}

func TestConversionReportTracksBlockingErrors(t *testing.T) {
	t.Parallel()

	var report ConversionReport
	report.AddWarning("FALLBACK_BASENAME", "matched by basename fallback")
	if report.HasBlockingErrors() {
		t.Fatal("warnings must not mark report as blocking")
	}

	report.AddError("UNSUPPORTED_GEOMETRY", "obb_poly8 is not implemented")
	if !report.HasBlockingErrors() {
		t.Fatal("errors must mark report as blocking")
	}
	if got, want := len(report.Warnings), 1; got != want {
		t.Fatalf("warnings len got %d want %d", got, want)
	}
	if got, want := len(report.Errors), 1; got != want {
		t.Fatalf("errors len got %d want %d", got, want)
	}
}

func TestValidateGeometryCapabilitiesRejectsPoly8OutputKind(t *testing.T) {
	t.Parallel()

	err := ValidateGeometryCapabilities([]GeometryCapability{
		{
			InputKind:  GeometryKindRect,
			OutputKind: GeometryKindRect,
			Supported:  true,
		},
		{
			InputKind:  GeometryKindObbPoly8,
			OutputKind: GeometryKindObbPoly8,
			Supported:  true,
		},
	})
	if err == nil {
		t.Fatal("expected poly8 output capability to be rejected")
	}
}

func TestParseProjectAnnotationsResultValidateRequiresBatch(t *testing.T) {
	t.Parallel()

	result := ParseProjectAnnotationsResult{
		SampleRefs: []SampleRef{
			{
				Type:            SampleRefTypeDatasetRelpath,
				RawValue:        "images/train/sample-1.jpg",
				NormalizedValue: "images/train/sample-1.jpg",
			},
		},
	}
	if err := result.Validate(); err == nil {
		t.Fatal("expected Validate to reject nil batch")
	}

	result.Batch = &annotationirv1.DataBatchIR{Items: []*annotationirv1.DataItemIR{}}
	if err := result.Validate(); err != nil {
		t.Fatalf("Validate failed: %v", err)
	}
}
