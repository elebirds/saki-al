package app

import "context"

type TypeInfo struct {
	Value                  string
	Label                  string
	Description            string
	Color                  string
	Enabled                bool
	AllowedAnnotationTypes []string
	MustAnnotationTypes    []string
	BannedAnnotationTypes  []string
}

type TypesCatalog struct {
	TaskTypes    []TypeInfo
	DatasetTypes []TypeInfo
}

type TypesUseCase struct{}

func NewTypesUseCase() *TypesUseCase {
	return &TypesUseCase{}
}

func (u *TypesUseCase) Execute(context.Context) (*TypesCatalog, error) {
	return &TypesCatalog{
		TaskTypes: []TypeInfo{
			{
				Value:                 "classification",
				Label:                 "Classification",
				Description:           "Image classification task - assign one label per image",
				Color:                 "purple",
				Enabled:               false,
				BannedAnnotationTypes: []string{"rect", "obb"},
			},
			{
				Value:                  "detection",
				Label:                  "Detection",
				Description:            "Object detection task - locate and classify objects with bounding boxes",
				Color:                  "green",
				Enabled:                true,
				AllowedAnnotationTypes: []string{"rect", "obb"},
			},
			{
				Value:                 "segmentation",
				Label:                 "Segmentation",
				Description:           "Semantic segmentation task - pixel-level classification",
				Color:                 "yellow",
				Enabled:               false,
				BannedAnnotationTypes: []string{"rect", "obb"},
			},
		},
		DatasetTypes: []TypeInfo{
			{
				Value:       "classic",
				Label:       "Classic Annotation",
				Description: "Standard image annotation with rectangles and OBB",
				Color:       "cyan",
				Enabled:     true,
			},
			{
				Value:               "fedo",
				Label:               "FEDO Dual-View",
				Description:         "Satellite electron energy data annotation with Time-Energy and L-ωd synchronized views",
				Color:               "purple",
				Enabled:             true,
				MustAnnotationTypes: []string{"obb"},
			},
		},
	}, nil
}
