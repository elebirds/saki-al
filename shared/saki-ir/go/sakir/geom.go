package sakir

import (
	"math"
	"sort"

	annotationirv1 "github.com/saki-ai/saki/shared/saki-ir/go/gen/annotationirv1"
)

const screenSortEps = 1e-6

// Point 表示二维坐标点。
type Point struct {
	// X 是点的横坐标。
	X float32
	// Y 是点的纵坐标。
	Y float32
}

// RectTLToCenter 将 Rect(TL) 转换为中心语义 (cx, cy, width, height)。
//
// Spec: docs/IR_SPEC.md#4-rect-semantics
func RectTLToCenter(rect *annotationirv1.RectGeometry) (cx, cy, width, height float32) {
	if rect == nil {
		return 0, 0, 0, 0
	}
	cx = rect.GetX() + rect.GetWidth()/2
	cy = rect.GetY() + rect.GetHeight()/2
	return cx, cy, rect.GetWidth(), rect.GetHeight()
}

// RectCenterToTL 将中心语义转换为 Rect(TL) 的 (x, y, width, height)。
//
// Spec: docs/IR_SPEC.md#4-rect-semantics
func RectCenterToTL(cx, cy, width, height float32) (x, y, w, h float32) {
	x = cx - width/2
	y = cy - height/2
	return x, y, width, height
}

// RectToVerticesScreen 返回屏幕顺序顶点：TL, TR, BR, BL。
//
// Spec: docs/IR_SPEC.md#7-vertices-and-aabb
func RectToVerticesScreen(rect *annotationirv1.RectGeometry) [4]Point {
	if rect == nil {
		return [4]Point{}
	}
	x := rect.GetX()
	y := rect.GetY()
	w := rect.GetWidth()
	h := rect.GetHeight()
	return [4]Point{
		{X: x, Y: y},
		{X: x + w, Y: y},
		{X: x + w, Y: y + h},
		{X: x, Y: y + h},
	}
}

// RectToVertices 是兼容别名，等价 RectToVerticesScreen。
func RectToVertices(rect *annotationirv1.RectGeometry) [4]Point {
	return RectToVerticesScreen(rect)
}

// ObbToVerticesLocal 返回 OBB 局部角点顺序：TL, TR, BR, BL。
//
// 注意：这是局部角点顺序，不是屏幕排序。
//
// Spec: docs/IR_SPEC.md#5-obb-semantics
// Spec: docs/IR_SPEC.md#7-vertices-and-aabb
func ObbToVerticesLocal(obb *annotationirv1.ObbGeometry) [4]Point {
	if obb == nil {
		return [4]Point{}
	}

	cx := float64(obb.GetCx())
	cy := float64(obb.GetCy())
	hw := float64(obb.GetWidth()) / 2.0
	hh := float64(obb.GetHeight()) / 2.0
	theta := float64(obb.GetAngleDegCcw()) * math.Pi / 180.0
	cosT := math.Cos(theta)
	sinT := math.Sin(theta)

	corners := [4][2]float64{
		{-hw, -hh},
		{hw, -hh},
		{hw, hh},
		{-hw, hh},
	}

	var out [4]Point
	for i, c := range corners {
		dx := c[0]
		dy := c[1]
		rx := dx*cosT - dy*sinT
		ry := dx*sinT + dy*cosT
		out[i] = Point{X: float32(cx + rx), Y: float32(cy + ry)}
	}
	return out
}

// ObbToVerticesScreen 返回屏幕排序顶点：TL, TR, BR, BL。
//
// Spec: docs/IR_SPEC.md#7-vertices-and-aabb
func ObbToVerticesScreen(obb *annotationirv1.ObbGeometry) [4]Point {
	local := ObbToVerticesLocal(obb)
	return sortVerticesScreen(local, screenSortEps)
}

// ObbToVertices 是兼容别名，等价 ObbToVerticesLocal。
func ObbToVertices(obb *annotationirv1.ObbGeometry) [4]Point {
	return ObbToVerticesLocal(obb)
}

// VerticesToAABB 由顶点集合计算 AABB (x, y, w, h)。
func VerticesToAABB(vertices [4]Point) (x, y, w, h float32) {
	minX := float64(vertices[0].X)
	minY := float64(vertices[0].Y)
	maxX := minX
	maxY := minY
	for i := 1; i < len(vertices); i++ {
		vx := float64(vertices[i].X)
		vy := float64(vertices[i].Y)
		minX = math.Min(minX, vx)
		minY = math.Min(minY, vy)
		maxX = math.Max(maxX, vx)
		maxY = math.Max(maxY, vy)
	}
	return float32(minX), float32(minY), float32(maxX - minX), float32(maxY - minY)
}

func sortVerticesScreen(vertices [4]Point, eps float64) [4]Point {
	type withKey struct {
		p  Point
		qx int64
		qy int64
	}

	quant := func(v float64) int64 {
		if eps <= 0 {
			return int64(math.Round(v * 1e6))
		}
		return int64(math.Round(v / eps))
	}

	values := make([]withKey, 0, 4)
	for _, p := range vertices {
		values = append(values, withKey{p: p, qx: quant(float64(p.X)), qy: quant(float64(p.Y))})
	}

	sort.Slice(values, func(i, j int) bool {
		if values[i].qy != values[j].qy {
			return values[i].qy < values[j].qy
		}
		if values[i].qx != values[j].qx {
			return values[i].qx < values[j].qx
		}
		if values[i].p.Y != values[j].p.Y {
			return values[i].p.Y < values[j].p.Y
		}
		return values[i].p.X < values[j].p.X
	})

	top := []Point{values[0].p, values[1].p}
	bottom := []Point{values[2].p, values[3].p}
	sort.Slice(top, func(i, j int) bool { return top[i].X < top[j].X })
	sort.Slice(bottom, func(i, j int) bool { return bottom[i].X < bottom[j].X })

	return [4]Point{top[0], top[1], bottom[1], bottom[0]}
}
