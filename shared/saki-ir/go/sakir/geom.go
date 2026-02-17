package sakir

import (
	"math"

	annotationirv1 "github.com/saki-ai/saki/shared/saki-ir/go/gen/annotationirv1"
)

type Point struct {
	X float32
	Y float32
}

func RectTLToCenter(rect *annotationirv1.RectGeometry) (cx, cy, width, height float32) {
	if rect == nil {
		return 0, 0, 0, 0
	}
	cx = rect.GetX() + rect.GetWidth()/2
	cy = rect.GetY() + rect.GetHeight()/2
	return cx, cy, rect.GetWidth(), rect.GetHeight()
}

func RectCenterToTL(cx, cy, width, height float32) (x, y, w, h float32) {
	x = cx - width/2
	y = cy - height/2
	return x, y, width, height
}

// RectToVertices 返回顺时针顶点顺序：TL, TR, BR, BL。
func RectToVertices(rect *annotationirv1.RectGeometry) [4]Point {
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

// ObbToVertices 返回顺时针顶点顺序：TL, TR, BR, BL。
func ObbToVertices(obb *annotationirv1.ObbGeometry) [4]Point {
	if obb == nil {
		return [4]Point{}
	}

	cx := float64(obb.GetCx())
	cy := float64(obb.GetCy())
	hw := float64(obb.GetWidth()) / 2.0
	hh := float64(obb.GetHeight()) / 2.0
	theta := float64(obb.GetAngleDegCw()) * math.Pi / 180.0
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
		rx := dx*cosT + dy*sinT
		ry := -dx*sinT + dy*cosT
		out[i] = Point{X: float32(cx + rx), Y: float32(cy + ry)}
	}
	return out
}
