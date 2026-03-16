package app

import (
	"context"
	"fmt"
	"strings"

	"github.com/saki-ai/saki/shared/saki-ir/go/formats/coco"
	"github.com/saki-ai/saki/shared/saki-ir/go/formats/common"
	"github.com/saki-ai/saki/shared/saki-ir/go/formats/yolo"
)

type ParseProjectAnnotationsRequest struct {
	FormatProfile string
	SourcePath    string
	Split         string
}

type ProjectAnnotationParser interface {
	ParseProjectAnnotations(ctx context.Context, req ParseProjectAnnotationsRequest) (*common.ParseProjectAnnotationsResult, error)
}

type ParserRegistry struct {
	cocoParser coco.Parser
	yoloParser yolo.Parser
}

func NewParserRegistry() ParserRegistry {
	return ParserRegistry{
		cocoParser: coco.Parser{},
		yoloParser: yolo.Parser{},
	}
}

func (r ParserRegistry) ParseProjectAnnotations(ctx context.Context, req ParseProjectAnnotationsRequest) (*common.ParseProjectAnnotationsResult, error) {
	switch strings.ToLower(req.FormatProfile) {
	case "coco":
		return r.cocoParser.ParseProjectAnnotations(ctx, coco.ParseRequest{
			AnnotationsPath: req.SourcePath,
		})
	case "yolo":
		return r.yoloParser.ParseProjectAnnotations(ctx, yolo.ParseRequest{
			RootDir: req.SourcePath,
			Split:   req.Split,
		})
	default:
		return nil, fmt.Errorf("unsupported format profile %q", req.FormatProfile)
	}
}
