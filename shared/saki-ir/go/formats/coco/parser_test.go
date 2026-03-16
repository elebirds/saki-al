package coco

import (
	"context"
	"path/filepath"
	"testing"

	"github.com/saki-ai/saki/shared/saki-ir/go/formats/common"
	annotationirv1 "github.com/saki-ai/saki/shared/saki-ir/go/gen/annotationirv1"
)

func TestParserParseProjectAnnotationsCOCOBBox(t *testing.T) {
	t.Parallel()

	parser := Parser{}
	result, err := parser.ParseProjectAnnotations(context.Background(), ParseRequest{
		AnnotationsPath: filepath.Join("testdata", "bbox", "annotations.json"),
	})
	if err != nil {
		t.Fatalf("ParseProjectAnnotations failed: %v", err)
	}
	if result.Report.HasBlockingErrors() {
		t.Fatalf("unexpected blocking errors: %+v", result.Report.Errors)
	}

	if got, want := len(result.SampleRefs), 1; got != want {
		t.Fatalf("sample refs len got %d want %d", got, want)
	}
	if got, want := result.SampleRefs[0].NormalizedValue, "images/train/sample-1.jpg"; got != want {
		t.Fatalf("sample ref normalized_value got %q want %q", got, want)
	}

	if got, want := len(result.DetectedGeometryKinds), 1; got != want {
		t.Fatalf("detected geometry kinds len got %d want %d", got, want)
	}
	if got, want := result.DetectedGeometryKinds[0], common.GeometryKindRect; got != want {
		t.Fatalf("detected geometry kind got %q want %q", got, want)
	}

	var labels []*annotationirv1.LabelRecord
	var samples []*annotationirv1.SampleRecord
	var anns []*annotationirv1.AnnotationRecord
	for _, item := range result.Batch.GetItems() {
		switch entry := item.GetItem().(type) {
		case *annotationirv1.DataItemIR_Label:
			labels = append(labels, entry.Label)
		case *annotationirv1.DataItemIR_Sample:
			samples = append(samples, entry.Sample)
		case *annotationirv1.DataItemIR_Annotation:
			anns = append(anns, entry.Annotation)
		}
	}
	if got, want := len(labels), 1; got != want {
		t.Fatalf("labels len got %d want %d", got, want)
	}
	if got, want := labels[0].GetName(), "car"; got != want {
		t.Fatalf("label name got %q want %q", got, want)
	}
	if got, want := len(samples), 1; got != want {
		t.Fatalf("samples len got %d want %d", got, want)
	}
	if got, want := samples[0].GetWidth(), int32(1280); got != want {
		t.Fatalf("sample width got %d want %d", got, want)
	}
	if got, want := samples[0].GetHeight(), int32(720); got != want {
		t.Fatalf("sample height got %d want %d", got, want)
	}
	if got, want := len(anns), 1; got != want {
		t.Fatalf("annotations len got %d want %d", got, want)
	}
	rect := anns[0].GetGeometry().GetRect()
	if rect == nil {
		t.Fatal("expected rect geometry")
	}
	if got, want := rect.GetX(), float32(10); got != want {
		t.Fatalf("rect x got %v want %v", got, want)
	}
	if got, want := rect.GetY(), float32(20); got != want {
		t.Fatalf("rect y got %v want %v", got, want)
	}
	if got, want := rect.GetWidth(), float32(100); got != want {
		t.Fatalf("rect width got %v want %v", got, want)
	}
	if got, want := rect.GetHeight(), float32(50); got != want {
		t.Fatalf("rect height got %v want %v", got, want)
	}
}

func TestParserParseProjectAnnotationsReportsUnsupportedSegmentation(t *testing.T) {
	t.Parallel()

	parser := Parser{}
	result, err := parser.ParseProjectAnnotations(context.Background(), ParseRequest{
		AnnotationsPath: filepath.Join("testdata", "segmentation", "annotations.json"),
	})
	if err != nil {
		t.Fatalf("ParseProjectAnnotations failed: %v", err)
	}
	if !result.Report.HasBlockingErrors() {
		t.Fatal("expected unsupported segmentation to produce blocking errors")
	}
	if got, want := len(result.UnsupportedGeometryKinds), 1; got != want {
		t.Fatalf("unsupported geometry kinds len got %d want %d", got, want)
	}
	if got, want := result.UnsupportedGeometryKinds[0], common.GeometryKindPolygonSeg; got != want {
		t.Fatalf("unsupported geometry kind got %q want %q", got, want)
	}
}
