package common

import (
	"fmt"

	annotationirv1 "github.com/saki-ai/saki/shared/saki-ir/go/gen/annotationirv1"
	"github.com/saki-ai/saki/shared/saki-ir/go/sakir"
)

type ParseProjectAnnotationsResult struct {
	Batch                    *annotationirv1.DataBatchIR
	SampleRefs               []SampleRef
	Samples                  []ParsedSample
	Annotations              []ParsedAnnotation
	Report                   ConversionReport
	DetectedGeometryKinds    []GeometryKind
	UnsupportedGeometryKinds []GeometryKind
	Capabilities             []GeometryCapability
}

type ParsedSample struct {
	SampleID string
	Refs     []SampleRef
}

type ParsedAnnotation struct {
	AnnotationID       string
	SampleID           string
	PrimarySampleRef   SampleRef
	InputGeometryKind  GeometryKind
	OutputGeometryKind GeometryKind
}

func (r ParseProjectAnnotationsResult) Validate() error {
	if r.Batch == nil {
		return fmt.Errorf("parse result batch is nil")
	}
	if err := sakir.Validate(r.Batch); err != nil {
		return err
	}
	if err := ValidateGeometryCapabilities(r.Capabilities); err != nil {
		return err
	}
	return nil
}
