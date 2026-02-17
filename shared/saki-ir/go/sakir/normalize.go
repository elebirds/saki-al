package sakir

import (
	"math"

	annotationirv1 "github.com/saki-ai/saki/shared/saki-ir/go/gen/annotationirv1"
	"google.golang.org/protobuf/proto"
)

const EPS float32 = 1e-6

func Normalize(batch *annotationirv1.DataBatchIR) error {
	if batch == nil {
		return newError(ErrIRSchema, "batch is nil")
	}

	for idx, item := range batch.GetItems() {
		if item.GetAnnotation() == nil {
			continue
		}
		ann := item.GetAnnotation()

		if err := validateConfidence(ann.GetConfidence(), idx); err != nil {
			return err
		}

		geometry := ann.GetGeometry()
		if geometry == nil || geometry.GetShape() == nil {
			return newError(ErrIRGeometry, "annotation[%d] geometry is missing", idx)
		}

		switch shape := geometry.GetShape().(type) {
		case *annotationirv1.Geometry_Rect:
			if err := normalizeRect(shape.Rect, idx); err != nil {
				return err
			}
		case *annotationirv1.Geometry_Obb:
			if err := normalizeObb(shape.Obb, idx); err != nil {
				return err
			}
		default:
			return newError(ErrIRGeometry, "annotation[%d] geometry.shape is missing", idx)
		}
	}

	return nil
}

func Validate(batch *annotationirv1.DataBatchIR) error {
	if batch == nil {
		return newError(ErrIRSchema, "batch is nil")
	}

	copied, ok := proto.Clone(batch).(*annotationirv1.DataBatchIR)
	if !ok {
		return newError(ErrIRSchema, "failed to clone batch")
	}
	return Normalize(copied)
}

func normalizeRect(rect *annotationirv1.RectGeometry, idx int) error {
	if rect == nil {
		return newError(ErrIRGeometry, "annotation[%d] rect is nil", idx)
	}
	if !isFinite(float64(rect.GetX()), float64(rect.GetY()), float64(rect.GetWidth()), float64(rect.GetHeight())) {
		return newError(ErrIRGeometry, "annotation[%d] rect has NaN/Inf", idx)
	}
	if rect.GetWidth() <= EPS || rect.GetHeight() <= EPS {
		return newError(ErrIRGeometry, "annotation[%d] rect width/height must be > %g", idx, EPS)
	}
	return nil
}

func normalizeObb(obb *annotationirv1.ObbGeometry, idx int) error {
	if obb == nil {
		return newError(ErrIRGeometry, "annotation[%d] obb is nil", idx)
	}
	if !isFinite(float64(obb.GetCx()), float64(obb.GetCy()), float64(obb.GetWidth()), float64(obb.GetHeight()), float64(obb.GetAngleDegCw())) {
		return newError(ErrIRGeometry, "annotation[%d] obb has NaN/Inf", idx)
	}
	if obb.GetWidth() <= EPS || obb.GetHeight() <= EPS {
		return newError(ErrIRGeometry, "annotation[%d] obb width/height must be > %g", idx, EPS)
	}

	if obb.GetWidth() < obb.GetHeight() {
		w := obb.GetWidth()
		obb.Width = obb.GetHeight()
		obb.Height = w
		obb.AngleDegCw = obb.GetAngleDegCw() + 90.0
	}

	obb.AngleDegCw = normalizeAngleDegCW(obb.GetAngleDegCw())
	return nil
}

func validateConfidence(confidence float32, idx int) error {
	if !isFinite(float64(confidence)) {
		return newError(ErrIRSchema, "annotation[%d] confidence has NaN/Inf", idx)
	}
	if confidence < 0.0 || confidence > 1.0 {
		return newError(ErrIRSchema, "annotation[%d] confidence must be in [0,1]", idx)
	}
	return nil
}

func normalizeAngleDegCW(angle float32) float32 {
	n := math.Mod(float64(angle)+180.0, 360.0)
	if n < 0 {
		n += 360.0
	}
	n -= 180.0
	if n >= 180.0 {
		n -= 360.0
	}
	return float32(n)
}

func isFinite(values ...float64) bool {
	for _, v := range values {
		if math.IsNaN(v) || math.IsInf(v, 0) {
			return false
		}
	}
	return true
}
