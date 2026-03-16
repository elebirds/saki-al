package yolo

import (
	"context"
	"fmt"
	"image"
	_ "image/jpeg"
	_ "image/png"
	"os"
	"path/filepath"
	"slices"
	"sort"
	"strconv"
	"strings"

	"github.com/saki-ai/saki/shared/saki-ir/go/formats/common"
	annotationirv1 "github.com/saki-ai/saki/shared/saki-ir/go/gen/annotationirv1"
	"gopkg.in/yaml.v3"
)

var imageSuffixes = map[string]struct{}{
	".jpg":  {},
	".jpeg": {},
	".png":  {},
	".bmp":  {},
	".webp": {},
}

type Parser struct{}

func (Parser) ParseProjectAnnotations(_ context.Context, req ParseRequest) (*common.ParseProjectAnnotationsResult, error) {
	if req.RootDir == "" {
		return nil, fmt.Errorf("root dir is empty")
	}
	split := req.Split
	if split == "" {
		split = "train"
	}

	cfg, err := loadConfig(req)
	if err != nil {
		return nil, err
	}
	classNames := extractClassNames(cfg["names"])
	splitRel := extractSplitRelpath(cfg, split)

	rootDir := filepath.Clean(req.RootDir)
	imagesDir := resolvePath(rootDir, splitRel)
	labelsDir := resolvePath(rootDir, strings.Replace(splitRel, "images", "labels", 1))

	imagePaths, err := collectImagePaths(imagesDir)
	if err != nil {
		return nil, err
	}

	result := &common.ParseProjectAnnotationsResult{
		Capabilities: []common.GeometryCapability{
			{InputKind: common.GeometryKindRect, OutputKind: common.GeometryKindRect, Supported: true},
			{InputKind: common.GeometryKindObbXYWHR, Supported: false},
			{InputKind: common.GeometryKindObbPoly8, Supported: false},
		},
	}
	items := make([]*annotationirv1.DataItemIR, 0, len(imagePaths)*2)
	labelIDs := map[string]string{}

	for sampleIndex, imagePath := range imagePaths {
		relFromRoot, err := filepath.Rel(rootDir, imagePath)
		if err != nil {
			return nil, fmt.Errorf("rel image path: %w", err)
		}
		relFromImages, err := filepath.Rel(imagesDir, imagePath)
		if err != nil {
			return nil, fmt.Errorf("rel images path: %w", err)
		}
		relFromRoot = filepath.ToSlash(relFromRoot)
		relFromImages = filepath.ToSlash(relFromImages)

		width, height, err := readImageSize(imagePath)
		if err != nil {
			result.Report.AddError("YOLO_IMAGE_SIZE_READ_FAILED", fmt.Sprintf("%s 尺寸读取失败: %v", relFromRoot, err))
			continue
		}
		sampleRef, err := common.NewSampleRef(common.SampleRefTypeDatasetRelpath, relFromRoot)
		if err != nil {
			result.Report.AddError("YOLO_IMAGE_PATH_INVALID", fmt.Sprintf("%s 路径非法: %v", relFromRoot, err))
			continue
		}

		sampleID := "yolo-sample-" + strconv.Itoa(sampleIndex+1)
		items = append(items, &annotationirv1.DataItemIR{
			Item: &annotationirv1.DataItemIR_Sample{
				Sample: &annotationirv1.SampleRecord{
					Id:     sampleID,
					Width:  int32(width),
					Height: int32(height),
				},
			},
		})
		result.SampleRefs = append(result.SampleRefs, sampleRef)
		result.Samples = append(result.Samples, common.ParsedSample{
			SampleID: sampleID,
			Refs:     []common.SampleRef{sampleRef},
		})

		labelPath := filepath.Join(labelsDir, filepath.FromSlash(relFromImages))
		labelPath = strings.TrimSuffix(labelPath, filepath.Ext(labelPath)) + ".txt"
		content, err := os.ReadFile(labelPath)
		if err != nil {
			if os.IsNotExist(err) {
				continue
			}
			result.Report.AddError("YOLO_LABEL_READ_FAILED", fmt.Sprintf("%s 读取失败: %v", filepath.ToSlash(labelPath), err))
			continue
		}

		lines := strings.Split(string(content), "\n")
		for lineIndex, raw := range lines {
			line := strings.TrimSpace(raw)
			if line == "" {
				continue
			}
			parts := strings.Fields(line)
			switch len(parts) {
			case 5:
				result.DetectedGeometryKinds = appendKind(result.DetectedGeometryKinds, common.GeometryKindRect)
				classKey := parts[0]
				cx, err1 := strconv.ParseFloat(parts[1], 64)
				cy, err2 := strconv.ParseFloat(parts[2], 64)
				w, err3 := strconv.ParseFloat(parts[3], 64)
				h, err4 := strconv.ParseFloat(parts[4], 64)
				if err1 != nil || err2 != nil || err3 != nil || err4 != nil {
					result.Report.AddError("YOLO_LINE_INVALID", fmt.Sprintf("%s:%d 数值非法", relFromRoot, lineIndex+1))
					continue
				}
				rectX := float32((cx - w/2) * float64(width))
				rectY := float32((cy - h/2) * float64(height))
				rectW := float32(w * float64(width))
				rectH := float32(h * float64(height))
				if rectW <= 0 || rectH <= 0 {
					result.Report.AddError("YOLO_BOX_INVALID", fmt.Sprintf("%s:%d 宽高非法", relFromRoot, lineIndex+1))
					continue
				}

				labelID, ok := labelIDs[classKey]
				if !ok {
					labelID = "yolo-label-" + classKey
					labelIDs[classKey] = labelID
					items = append(items, &annotationirv1.DataItemIR{
						Item: &annotationirv1.DataItemIR_Label{
							Label: &annotationirv1.LabelRecord{
								Id:   labelID,
								Name: resolveClassName(classKey, classNames),
							},
						},
					})
				}
				annotationID := "yolo-ann-" + strconv.Itoa(len(result.Annotations)+1)
				items = append(items, &annotationirv1.DataItemIR{
					Item: &annotationirv1.DataItemIR_Annotation{
						Annotation: &annotationirv1.AnnotationRecord{
							Id:         annotationID,
							SampleId:   sampleID,
							LabelId:    labelID,
							Source:     annotationirv1.AnnotationSource_ANNOTATION_SOURCE_IMPORTED,
							Confidence: 1,
							Geometry: &annotationirv1.Geometry{
								Shape: &annotationirv1.Geometry_Rect{
									Rect: &annotationirv1.RectGeometry{
										X:      rectX,
										Y:      rectY,
										Width:  rectW,
										Height: rectH,
									},
								},
							},
						},
					},
				})
				result.Annotations = append(result.Annotations, common.ParsedAnnotation{
					AnnotationID:       annotationID,
					SampleID:           sampleID,
					PrimarySampleRef:   sampleRef,
					InputGeometryKind:  common.GeometryKindRect,
					OutputGeometryKind: common.GeometryKindRect,
				})
			case 6:
				result.DetectedGeometryKinds = appendKind(result.DetectedGeometryKinds, common.GeometryKindObbXYWHR)
				result.UnsupportedGeometryKinds = appendKind(result.UnsupportedGeometryKinds, common.GeometryKindObbXYWHR)
				result.Report.AddError("YOLO_OBB_XYWHR_UNSUPPORTED", fmt.Sprintf("%s:%d OBB xywhr 当前未实现", relFromRoot, lineIndex+1))
			case 9:
				result.DetectedGeometryKinds = appendKind(result.DetectedGeometryKinds, common.GeometryKindObbPoly8)
				result.UnsupportedGeometryKinds = appendKind(result.UnsupportedGeometryKinds, common.GeometryKindObbPoly8)
				result.Report.AddError("YOLO_OBB_POLY8_UNSUPPORTED", fmt.Sprintf("%s:%d OBB poly8 当前未实现", relFromRoot, lineIndex+1))
			default:
				result.Report.AddError("YOLO_LINE_UNSUPPORTED", fmt.Sprintf("%s:%d 字段数 %d 当前不支持", relFromRoot, lineIndex+1, len(parts)))
			}
		}
	}

	result.Batch = &annotationirv1.DataBatchIR{Items: items}
	if err := result.Validate(); err != nil {
		return nil, err
	}
	return result, nil
}

func loadConfig(req ParseRequest) (map[string]any, error) {
	yamlPath := req.DataYAMLPath
	if yamlPath == "" {
		yamlPath = filepath.Join(req.RootDir, "data.yaml")
	}
	content, err := os.ReadFile(yamlPath)
	if err != nil {
		if os.IsNotExist(err) {
			return map[string]any{}, nil
		}
		return nil, fmt.Errorf("read data.yaml: %w", err)
	}
	var cfg map[string]any
	if err := yaml.Unmarshal(content, &cfg); err != nil {
		return nil, fmt.Errorf("parse data.yaml: %w", err)
	}
	return cfg, nil
}

func extractClassNames(raw any) map[string]string {
	names := map[string]string{}
	switch current := raw.(type) {
	case []any:
		for index, value := range current {
			names[strconv.Itoa(index)] = fmt.Sprint(value)
		}
	case map[string]any:
		for key, value := range current {
			names[key] = fmt.Sprint(value)
		}
	case map[any]any:
		for key, value := range current {
			names[fmt.Sprint(key)] = fmt.Sprint(value)
		}
	}
	return names
}

func extractSplitRelpath(cfg map[string]any, split string) string {
	if raw, ok := cfg[split]; ok {
		if value, ok := raw.(string); ok && value != "" {
			return filepath.ToSlash(value)
		}
	}
	return filepath.ToSlash(filepath.Join("images", split))
}

func resolvePath(root, rel string) string {
	if filepath.IsAbs(rel) {
		return rel
	}
	return filepath.Join(root, filepath.FromSlash(rel))
}

func collectImagePaths(imagesDir string) ([]string, error) {
	entries := make([]string, 0, 8)
	err := filepath.WalkDir(imagesDir, func(path string, d os.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if d.IsDir() {
			return nil
		}
		if _, ok := imageSuffixes[strings.ToLower(filepath.Ext(path))]; !ok {
			return nil
		}
		entries = append(entries, path)
		return nil
	})
	if err != nil {
		return nil, fmt.Errorf("walk images dir: %w", err)
	}
	sort.Strings(entries)
	return entries, nil
}

func readImageSize(filename string) (int, int, error) {
	file, err := os.Open(filename)
	if err != nil {
		return 0, 0, err
	}
	defer file.Close()

	cfg, _, err := image.DecodeConfig(file)
	if err != nil {
		return 0, 0, err
	}
	return cfg.Width, cfg.Height, nil
}

func resolveClassName(classKey string, classNames map[string]string) string {
	if name, ok := classNames[classKey]; ok && name != "" {
		return name
	}
	return "class_" + classKey
}

func appendKind(kinds []common.GeometryKind, kind common.GeometryKind) []common.GeometryKind {
	if slices.Contains(kinds, kind) {
		return kinds
	}
	return append(kinds, kind)
}
