package yolo

import (
	"context"
	"image"
	"image/color"
	"image/png"
	"os"
	"path/filepath"
	"testing"

	"github.com/saki-ai/saki/shared/saki-ir/go/formats/common"
	annotationirv1 "github.com/saki-ai/saki/shared/saki-ir/go/gen/annotationirv1"
)

func TestParserParseProjectAnnotationsYOLODet(t *testing.T) {
	t.Parallel()

	root := t.TempDir()
	mustWriteFile(t, filepath.Join(root, "data.yaml"), "train: images/train\nnames:\n  0: car\n")
	mustWritePNG(t, filepath.Join(root, "images", "train", "sample1.png"), 200, 100)
	mustWriteFile(t, filepath.Join(root, "labels", "train", "sample1.txt"), "0 0.5 0.5 0.2 0.4\n")

	parser := Parser{}
	result, err := parser.ParseProjectAnnotations(context.Background(), ParseRequest{
		RootDir: root,
		Split:   "train",
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
	if got, want := result.SampleRefs[0].NormalizedValue, "images/train/sample1.png"; got != want {
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
	if got, want := samples[0].GetWidth(), int32(200); got != want {
		t.Fatalf("sample width got %d want %d", got, want)
	}
	if got, want := samples[0].GetHeight(), int32(100); got != want {
		t.Fatalf("sample height got %d want %d", got, want)
	}
	if got, want := len(anns), 1; got != want {
		t.Fatalf("annotations len got %d want %d", got, want)
	}
	rect := anns[0].GetGeometry().GetRect()
	if rect == nil {
		t.Fatal("expected rect geometry")
	}
	if got, want := rect.GetX(), float32(80); got != want {
		t.Fatalf("rect x got %v want %v", got, want)
	}
	if got, want := rect.GetY(), float32(30); got != want {
		t.Fatalf("rect y got %v want %v", got, want)
	}
	if got, want := rect.GetWidth(), float32(40); got != want {
		t.Fatalf("rect width got %v want %v", got, want)
	}
	if got, want := rect.GetHeight(), float32(40); got != want {
		t.Fatalf("rect height got %v want %v", got, want)
	}
}

func TestParserParseProjectAnnotationsYOLOReportsUnsupportedOBB(t *testing.T) {
	t.Parallel()

	root := t.TempDir()
	mustWriteFile(t, filepath.Join(root, "data.yaml"), "train: images/train\nnames:\n  0: car\n")
	mustWritePNG(t, filepath.Join(root, "images", "train", "sample1.png"), 200, 100)
	mustWriteFile(t, filepath.Join(root, "labels", "train", "sample1.txt"), "0 0.5 0.5 0.2 0.4 45\n")

	parser := Parser{}
	result, err := parser.ParseProjectAnnotations(context.Background(), ParseRequest{
		RootDir: root,
		Split:   "train",
	})
	if err != nil {
		t.Fatalf("ParseProjectAnnotations failed: %v", err)
	}
	if !result.Report.HasBlockingErrors() {
		t.Fatal("expected OBB line to produce blocking errors")
	}
	if got, want := len(result.UnsupportedGeometryKinds), 1; got != want {
		t.Fatalf("unsupported geometry kinds len got %d want %d", got, want)
	}
	if got, want := result.UnsupportedGeometryKinds[0], common.GeometryKindObbXYWHR; got != want {
		t.Fatalf("unsupported geometry kind got %q want %q", got, want)
	}
}

func mustWriteFile(t *testing.T, filename, content string) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(filename), 0o755); err != nil {
		t.Fatalf("MkdirAll(%s) failed: %v", filename, err)
	}
	if err := os.WriteFile(filename, []byte(content), 0o644); err != nil {
		t.Fatalf("WriteFile(%s) failed: %v", filename, err)
	}
}

func mustWritePNG(t *testing.T, filename string, width, height int) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(filename), 0o755); err != nil {
		t.Fatalf("MkdirAll(%s) failed: %v", filename, err)
	}
	file, err := os.Create(filename)
	if err != nil {
		t.Fatalf("Create(%s) failed: %v", filename, err)
	}
	defer file.Close()

	img := image.NewRGBA(image.Rect(0, 0, width, height))
	for y := 0; y < height; y++ {
		for x := 0; x < width; x++ {
			img.Set(x, y, color.RGBA{R: 255, A: 255})
		}
	}
	if err := png.Encode(file, img); err != nil {
		t.Fatalf("png.Encode(%s) failed: %v", filename, err)
	}
}
