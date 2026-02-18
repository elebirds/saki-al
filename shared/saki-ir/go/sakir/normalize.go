package sakir

import (
	"math"

	annotationirv1 "github.com/saki-ai/saki/shared/saki-ir/go/gen/annotationirv1"
	"google.golang.org/protobuf/proto"
)

// EPS 是几何宽高的最小严格下界，width/height 必须 > EPS。
//
// Spec: docs/IR_SPEC.md#6-obb-normalization
// Spec: docs/IR_SPEC.md#8-invalid-values
const EPS float32 = 1e-6

// Normalize 原地（in-place）规范化 batch 中的 annotation 几何。
//
// 该函数会修改输入对象：
// - 校验并规范化 Rect/OBB
// - OBB 按 v1 规则执行 swap + angle normalize
//
// Spec: docs/IR_SPEC.md#6-obb-normalization
// Spec: docs/IR_SPEC.md#8-invalid-values
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

// Validate 校验 batch 且不修改输入对象。
//
// 实现方式为 clone 后调用 Normalize，因此任何规范化副作用都不会回写到原输入。
//
// Spec: docs/IR_SPEC.md#8-invalid-values
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
	if !isFinite(float64(obb.GetCx()), float64(obb.GetCy()), float64(obb.GetWidth()), float64(obb.GetHeight()), float64(obb.GetAngleDegCcw())) {
		return newError(ErrIRGeometry, "annotation[%d] obb has NaN/Inf", idx)
	}
	if obb.GetWidth() <= EPS || obb.GetHeight() <= EPS {
		return newError(ErrIRGeometry, "annotation[%d] obb width/height must be > %g", idx, EPS)
	}

	if obb.GetWidth() < obb.GetHeight() {
		w := obb.GetWidth()
		obb.Width = obb.GetHeight()
		obb.Height = w
		obb.AngleDegCcw = obb.GetAngleDegCcw() + 90.0
	}

	obb.AngleDegCcw = normalizeAngleDegCCW(obb.GetAngleDegCcw())
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

func normalizeAngleDegCCW(angle float32) float32 {
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
