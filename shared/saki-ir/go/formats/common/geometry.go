package common

import "fmt"

type GeometryKind string

const (
	GeometryKindRect       GeometryKind = "rect"
	GeometryKindObb        GeometryKind = "obb"
	GeometryKindObbXYWHR   GeometryKind = "obb_xywhr"
	GeometryKindObbPoly8   GeometryKind = "obb_poly8"
	GeometryKindPolygonSeg GeometryKind = "polygon_segmentation"
)

type GeometryCapability struct {
	InputKind  GeometryKind
	OutputKind GeometryKind
	Supported  bool
}

func ValidateGeometryCapabilities(capabilities []GeometryCapability) error {
	for _, capability := range capabilities {
		if !capability.Supported {
			continue
		}
		switch capability.OutputKind {
		case GeometryKindRect, GeometryKindObb:
		default:
			return fmt.Errorf("supported geometry capability %q cannot output %q", capability.InputKind, capability.OutputKind)
		}
		switch capability.InputKind {
		case GeometryKindObbXYWHR, GeometryKindObbPoly8:
			if capability.OutputKind != GeometryKindObb {
				return fmt.Errorf("%q must normalize into %q", capability.InputKind, GeometryKindObb)
			}
		}
	}
	return nil
}
