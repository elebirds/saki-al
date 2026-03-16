package coco

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"slices"
	"strconv"

	"github.com/saki-ai/saki/shared/saki-ir/go/formats/common"
	annotationirv1 "github.com/saki-ai/saki/shared/saki-ir/go/gen/annotationirv1"
)

type Parser struct{}

func (Parser) ParseProjectAnnotations(_ context.Context, req ParseRequest) (*common.ParseProjectAnnotationsResult, error) {
	if req.AnnotationsPath == "" {
		return nil, fmt.Errorf("annotations path is empty")
	}

	file, err := os.Open(req.AnnotationsPath)
	if err != nil {
		return nil, fmt.Errorf("open coco annotations: %w", err)
	}
	defer file.Close()

	decoder := json.NewDecoder(file)
	decoder.UseNumber()

	var doc document
	if err := decoder.Decode(&doc); err != nil {
		return nil, fmt.Errorf("decode coco annotations: %w", err)
	}

	result := &common.ParseProjectAnnotationsResult{
		Capabilities: []common.GeometryCapability{
			{InputKind: common.GeometryKindRect, OutputKind: common.GeometryKindRect, Supported: true},
			{InputKind: common.GeometryKindObbXYWHR, Supported: false},
			{InputKind: common.GeometryKindObbPoly8, Supported: false},
			{InputKind: common.GeometryKindPolygonSeg, Supported: false},
		},
	}

	items := make([]*annotationirv1.DataItemIR, 0, len(doc.Categories)+len(doc.Images)+len(doc.Annotations))
	categoryToLabelID := make(map[string]string, len(doc.Categories))
	imageToSampleID := make(map[string]string, len(doc.Images))
	imageToSampleRef := make(map[string]common.SampleRef, len(doc.Images))

	for index, cat := range doc.Categories {
		categoryKey, ok := keyOf(cat.ID)
		if !ok {
			result.Report.AddError("COCO_CATEGORY_ID_MISSING", fmt.Sprintf("categories[%d].id 缺失或非法", index))
			continue
		}
		labelID := "coco-label-" + categoryKey
		categoryToLabelID[categoryKey] = labelID
		name := cat.Name
		if name == "" {
			name = "category_" + categoryKey
		}
		items = append(items, &annotationirv1.DataItemIR{
			Item: &annotationirv1.DataItemIR_Label{
				Label: &annotationirv1.LabelRecord{
					Id:   labelID,
					Name: name,
				},
			},
		})
	}

	for index, img := range doc.Images {
		imageKey, ok := keyOf(img.ID)
		if !ok {
			result.Report.AddError("COCO_IMAGE_ID_MISSING", fmt.Sprintf("images[%d].id 缺失或非法", index))
			continue
		}
		if img.Width <= 0 || img.Height <= 0 {
			result.Report.AddError("COCO_IMAGE_SIZE_INVALID", fmt.Sprintf("images[%d] width/height 非法", index))
			continue
		}
		sampleRef, err := common.NewSampleRef(common.SampleRefTypeDatasetRelpath, img.FileName)
		if err != nil {
			result.Report.AddError("COCO_IMAGE_PATH_INVALID", fmt.Sprintf("images[%d].file_name 非法: %v", index, err))
			continue
		}

		sampleID := "coco-sample-" + imageKey
		imageToSampleID[imageKey] = sampleID
		imageToSampleRef[imageKey] = sampleRef
		result.SampleRefs = append(result.SampleRefs, sampleRef)
		result.Samples = append(result.Samples, common.ParsedSample{
			SampleID: sampleID,
			Refs:     []common.SampleRef{sampleRef},
		})
		items = append(items, &annotationirv1.DataItemIR{
			Item: &annotationirv1.DataItemIR_Sample{
				Sample: &annotationirv1.SampleRecord{
					Id:          sampleID,
					DownloadUrl: img.CocoURL,
					Width:       img.Width,
					Height:      img.Height,
				},
			},
		})
	}

	detectedKinds := make([]common.GeometryKind, 0, 2)
	unsupportedKinds := make([]common.GeometryKind, 0, 1)

	for index, ann := range doc.Annotations {
		if ann.Segmentation != nil {
			detectedKinds = appendKind(detectedKinds, common.GeometryKindPolygonSeg)
			unsupportedKinds = appendKind(unsupportedKinds, common.GeometryKindPolygonSeg)
			result.Report.AddError("COCO_SEGMENTATION_UNSUPPORTED", fmt.Sprintf("annotations[%d].segmentation 当前未实现", index))
			continue
		}
		detectedKinds = appendKind(detectedKinds, common.GeometryKindRect)

		imageKey, ok := keyOf(ann.ImageID)
		if !ok {
			result.Report.AddError("COCO_ANNOTATION_IMAGE_ID_INVALID", fmt.Sprintf("annotations[%d].image_id 缺失或非法", index))
			continue
		}
		categoryKey, ok := keyOf(ann.CategoryID)
		if !ok {
			result.Report.AddError("COCO_ANNOTATION_CATEGORY_ID_INVALID", fmt.Sprintf("annotations[%d].category_id 缺失或非法", index))
			continue
		}
		sampleID, ok := imageToSampleID[imageKey]
		if !ok {
			result.Report.AddError("COCO_ANNOTATION_IMAGE_NOT_FOUND", fmt.Sprintf("annotations[%d] 引用了不存在的 image_id=%s", index, imageKey))
			continue
		}
		labelID, ok := categoryToLabelID[categoryKey]
		if !ok {
			result.Report.AddError("COCO_ANNOTATION_CATEGORY_NOT_FOUND", fmt.Sprintf("annotations[%d] 引用了不存在的 category_id=%s", index, categoryKey))
			continue
		}
		if len(ann.BBox) != 4 {
			result.Report.AddError("COCO_BBOX_INVALID", fmt.Sprintf("annotations[%d].bbox 必须是长度 4", index))
			continue
		}
		x, y, w, h := ann.BBox[0], ann.BBox[1], ann.BBox[2], ann.BBox[3]
		if w <= 0 || h <= 0 {
			result.Report.AddError("COCO_BBOX_INVALID", fmt.Sprintf("annotations[%d].bbox 宽高非法", index))
			continue
		}

		annotationID := "coco-ann-" + annotationKey(ann.ID, index)
		confidence := float32(1.0)
		if ann.Score != nil {
			confidence = *ann.Score
		}

		items = append(items, &annotationirv1.DataItemIR{
			Item: &annotationirv1.DataItemIR_Annotation{
				Annotation: &annotationirv1.AnnotationRecord{
					Id:         annotationID,
					SampleId:   sampleID,
					LabelId:    labelID,
					Source:     annotationirv1.AnnotationSource_ANNOTATION_SOURCE_IMPORTED,
					Confidence: confidence,
					Geometry: &annotationirv1.Geometry{
						Shape: &annotationirv1.Geometry_Rect{
							Rect: &annotationirv1.RectGeometry{
								X:      x,
								Y:      y,
								Width:  w,
								Height: h,
							},
						},
					},
				},
			},
		})

		result.Annotations = append(result.Annotations, common.ParsedAnnotation{
			AnnotationID:       annotationID,
			SampleID:           sampleID,
			PrimarySampleRef:   imageToSampleRef[imageKey],
			InputGeometryKind:  common.GeometryKindRect,
			OutputGeometryKind: common.GeometryKindRect,
		})
	}

	result.Batch = &annotationirv1.DataBatchIR{Items: items}
	result.DetectedGeometryKinds = detectedKinds
	result.UnsupportedGeometryKinds = unsupportedKinds
	if err := result.Validate(); err != nil {
		return nil, err
	}
	return result, nil
}

func keyOf(value any) (string, bool) {
	switch current := value.(type) {
	case nil:
		return "", false
	case string:
		if current == "" {
			return "", false
		}
		return current, true
	case json.Number:
		return current.String(), true
	case float64:
		return strconv.FormatInt(int64(current), 10), true
	case float32:
		return strconv.FormatInt(int64(current), 10), true
	case int:
		return strconv.Itoa(current), true
	case int32:
		return strconv.FormatInt(int64(current), 10), true
	case int64:
		return strconv.FormatInt(current, 10), true
	default:
		return "", false
	}
}

func annotationKey(value any, index int) string {
	if key, ok := keyOf(value); ok {
		return key
	}
	return filepath.Base(strconv.Itoa(index))
}

func appendKind(kinds []common.GeometryKind, kind common.GeometryKind) []common.GeometryKind {
	if slices.Contains(kinds, kind) {
		return kinds
	}
	return append(kinds, kind)
}
