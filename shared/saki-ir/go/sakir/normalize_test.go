package sakir

import (
	"errors"
	"math"
	"sort"
	"testing"

	annotationirv1 "github.com/saki-ai/saki/shared/saki-ir/go/gen/annotationirv1"
)

func TestNormalizeOBBGoldenCases(t *testing.T) {
	cases := []struct {
		name           string
		w              float32
		h              float32
		angle          float32
		expectW        float32
		expectH        float32
		expectAngleCCW float32
	}{
		{"no-swap", 4, 2, 0, 4, 2, 0},
		{"swap-90", 2, 4, 0, 4, 2, 90},
		{"swap-wrap", 1, 5, 100, 5, 1, -170},
		{"swap-boundary", 3, 6, 179, 6, 3, -91},
		{"angle-180", 5, 3, 180, 5, 3, -180},
		{"angle-neg181", 5, 3, -181, 5, 3, 179},
		{"swap-neg181", 2, 8, -181, 8, 2, -91},
		{"swap-270", 2, 8, 270, 8, 2, 0},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			batch := makeOBBBatch(tc.w, tc.h, tc.angle, 0.5)
			if err := Normalize(batch); err != nil {
				t.Fatalf("Normalize failed: %v", err)
			}
			obb := batch.GetItems()[0].GetAnnotation().GetGeometry().GetObb()
			assertAlmostEqual(t, obb.GetWidth(), tc.expectW)
			assertAlmostEqual(t, obb.GetHeight(), tc.expectH)
			assertAlmostEqual(t, obb.GetAngleDegCcw(), tc.expectAngleCCW)
		})
	}
}

func TestRectInvalidCases(t *testing.T) {
	cases := []*annotationirv1.DataBatchIR{
		makeRectBatch(0, 0, 0, 10, 0.5),
		makeRectBatch(0, 0, 10, -1, 0.5),
		makeRectBatch(float32(math.NaN()), 0, 10, 10, 0.5),
		makeRectBatch(0, float32(math.Inf(1)), 10, 10, 0.5),
	}

	for _, batch := range cases {
		err := Validate(batch)
		assertErrCode(t, err, ErrIRGeometry)
	}
}

func TestConfidenceInvalidCases(t *testing.T) {
	cases := []float32{-0.1, 1.1, float32(math.NaN()), float32(math.Inf(1))}
	for _, c := range cases {
		err := Validate(makeOBBBatch(4, 2, 0, c))
		assertErrCode(t, err, ErrIRSchema)
	}
}

func TestValidateDoesNotModifyInput(t *testing.T) {
	batch := makeOBBBatch(2, 4, 15, 0.4)
	before := batch.GetItems()[0].GetAnnotation().GetGeometry().GetObb().GetAngleDegCcw()

	if err := Validate(batch); err != nil {
		t.Fatalf("Validate failed: %v", err)
	}
	after := batch.GetItems()[0].GetAnnotation().GetGeometry().GetObb().GetAngleDegCcw()
	if before != after {
		t.Fatalf("Validate modified input: before=%v after=%v", before, after)
	}
}

func TestOBBVerticesInvariantAfterNormalize(t *testing.T) {
	batch := makeOBBBatch(2, 8, 35, 0.8)
	obbBefore := batch.GetItems()[0].GetAnnotation().GetGeometry().GetObb()
	verticesBefore := ObbToVerticesLocal(obbBefore)

	if err := Normalize(batch); err != nil {
		t.Fatalf("Normalize failed: %v", err)
	}

	obbAfter := batch.GetItems()[0].GetAnnotation().GetGeometry().GetObb()
	verticesAfter := ObbToVerticesLocal(obbAfter)
	assertVertexSetEqual(t, verticesBefore, verticesAfter, 1e-4)
}

func TestOBBVerticesDirectionForZeroAngle(t *testing.T) {
	obb := &annotationirv1.ObbGeometry{
		Cx:          10,
		Cy:          10,
		Width:       6,
		Height:      2,
		AngleDegCcw: 0,
	}
	vertices := ObbToVerticesLocal(obb)
	tl := vertices[0]
	tr := vertices[1]
	br := vertices[2]

	if !(tr.X > tl.X) {
		t.Fatalf("expected width edge along +x, got TL=%v TR=%v", tl, tr)
	}
	if math.Abs(float64(tr.Y-tl.Y)) > 1e-5 {
		t.Fatalf("expected TL/TR nearly same y, got TL=%v TR=%v", tl, tr)
	}
	if !(br.Y > tr.Y) {
		t.Fatalf("expected height edge along +y, got TR=%v BR=%v", tr, br)
	}
}

func TestOBBVerticesDirectionForPositive90CCW(t *testing.T) {
	obb := &annotationirv1.ObbGeometry{
		Cx:          0,
		Cy:          0,
		Width:       2,
		Height:      1,
		AngleDegCcw: 90,
	}
	vertices := ObbToVerticesLocal(obb)
	tl := vertices[0]
	tr := vertices[1]
	dx := float64(tr.X - tl.X)
	dy := float64(tr.Y - tl.Y)
	if math.Abs(dx-0.0) > 1e-5 {
		t.Fatalf("expected dx ~= 0, got %f", dx)
	}
	if math.Abs(dy-2.0) > 1e-5 {
		t.Fatalf("expected dy ~= 2, got %f", dy)
	}
}

func TestOBBVerticesScreenOrder(t *testing.T) {
	obb := &annotationirv1.ObbGeometry{
		Cx:          10,
		Cy:          10,
		Width:       6,
		Height:      2,
		AngleDegCcw: 30,
	}
	vertices := ObbToVerticesScreen(obb)
	tl := vertices[0]
	tr := vertices[1]
	br := vertices[2]
	bl := vertices[3]

	if !(tl.X <= tr.X+1e-5) {
		t.Fatalf("expected TL at left of TR: TL=%v TR=%v", tl, tr)
	}
	if !(bl.X <= br.X+1e-5) {
		t.Fatalf("expected BL at left of BR: BL=%v BR=%v", bl, br)
	}
	if !(tl.Y <= bl.Y+1e-5) {
		t.Fatalf("expected TL above BL: TL=%v BL=%v", tl, bl)
	}
	if !(tr.Y <= br.Y+1e-5) {
		t.Fatalf("expected TR above BR: TR=%v BR=%v", tr, br)
	}
}

func makeOBBBatch(w, h, angle, confidence float32) *annotationirv1.DataBatchIR {
	return &annotationirv1.DataBatchIR{
		Items: []*annotationirv1.DataItemIR{
			{
				Item: &annotationirv1.DataItemIR_Annotation{
					Annotation: &annotationirv1.AnnotationRecord{
						Id:         "ann-1",
						SampleId:   "sample-1",
						LabelId:    "label-1",
						Confidence: confidence,
						Geometry: &annotationirv1.Geometry{
							Shape: &annotationirv1.Geometry_Obb{
								Obb: &annotationirv1.ObbGeometry{
									Cx:          100,
									Cy:          50,
									Width:       w,
									Height:      h,
									AngleDegCcw: angle,
								},
							},
						},
					},
				},
			},
		},
	}
}

func makeRectBatch(x, y, w, h, confidence float32) *annotationirv1.DataBatchIR {
	return &annotationirv1.DataBatchIR{
		Items: []*annotationirv1.DataItemIR{
			{
				Item: &annotationirv1.DataItemIR_Annotation{
					Annotation: &annotationirv1.AnnotationRecord{
						Id:         "ann-r",
						SampleId:   "sample-1",
						LabelId:    "label-1",
						Confidence: confidence,
						Geometry: &annotationirv1.Geometry{
							Shape: &annotationirv1.Geometry_Rect{
								Rect: &annotationirv1.RectGeometry{X: x, Y: y, Width: w, Height: h},
							},
						},
					},
				},
			},
		},
	}
}

func assertErrCode(t *testing.T, err error, code string) {
	t.Helper()
	if err == nil {
		t.Fatalf("expected error code %s, got nil", code)
	}
	var irErr *Error
	if !errors.As(err, &irErr) {
		t.Fatalf("expected *Error, got %T (%v)", err, err)
	}
	if irErr.Code != code {
		t.Fatalf("expected code %s, got %s", code, irErr.Code)
	}
}

func assertAlmostEqual(t *testing.T, got, want float32) {
	t.Helper()
	if math.Abs(float64(got-want)) > 1e-5 {
		t.Fatalf("got %v, want %v", got, want)
	}
}

func assertVertexSetEqual(t *testing.T, a [4]Point, b [4]Point, tol float64) {
	t.Helper()

	sa := sortVertices(a)
	sb := sortVertices(b)
	for i := 0; i < 4; i++ {
		if math.Abs(sa[i][0]-sb[i][0]) > tol || math.Abs(sa[i][1]-sb[i][1]) > tol {
			t.Fatalf("vertex set mismatch at %d: got=%v want=%v", i, sa, sb)
		}
	}
}

func sortVertices(vertices [4]Point) [][2]float64 {
	points := make([][2]float64, 0, len(vertices))
	for _, p := range vertices {
		points = append(points, [2]float64{float64(p.X), float64(p.Y)})
	}
	sort.Slice(points, func(i, j int) bool {
		if points[i][0] == points[j][0] {
			return points[i][1] < points[j][1]
		}
		return points[i][0] < points[j][0]
	})
	return points
}
