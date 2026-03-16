package common

import (
	"fmt"
	"path"
	"strings"
)

type SampleRefType string

const (
	SampleRefTypeDatasetRelpath SampleRefType = "dataset_relpath"
	SampleRefTypeSampleName     SampleRefType = "sample_name"
	SampleRefTypeBasename       SampleRefType = "basename"
	SampleRefTypeExternalRef    SampleRefType = "external_ref"
	SampleRefTypeAssetSHA256    SampleRefType = "asset_sha256"
)

type SampleRef struct {
	Type            SampleRefType
	RawValue        string
	NormalizedValue string
}

func NewSampleRef(refType SampleRefType, value string) (SampleRef, error) {
	normalized, err := normalizeSampleRefValue(refType, value)
	if err != nil {
		return SampleRef{}, err
	}
	return SampleRef{
		Type:            refType,
		RawValue:        value,
		NormalizedValue: normalized,
	}, nil
}

func normalizeSampleRefValue(refType SampleRefType, value string) (string, error) {
	trimmed := strings.TrimSpace(value)
	if trimmed == "" {
		return "", fmt.Errorf("sample ref %s value is empty", refType)
	}

	switch refType {
	case SampleRefTypeDatasetRelpath:
		return normalizeDatasetRelpath(trimmed)
	case SampleRefTypeSampleName, SampleRefTypeExternalRef, SampleRefTypeAssetSHA256:
		return trimmed, nil
	case SampleRefTypeBasename:
		cleaned, err := normalizeDatasetRelpath(trimmed)
		if err != nil {
			return "", err
		}
		base := path.Base(cleaned)
		if base == "." || base == "/" || base == "" {
			return "", fmt.Errorf("sample ref %s value %q has invalid basename", refType, value)
		}
		return base, nil
	default:
		return "", fmt.Errorf("unsupported sample ref type %q", refType)
	}
}

func normalizeDatasetRelpath(value string) (string, error) {
	candidate := strings.ReplaceAll(value, "\\", "/")
	candidate = path.Clean(candidate)
	candidate = strings.TrimPrefix(candidate, "./")

	if candidate == "." || candidate == "" {
		return "", fmt.Errorf("dataset_relpath %q is empty after normalization", value)
	}
	if strings.HasPrefix(candidate, "/") {
		return "", fmt.Errorf("dataset_relpath %q must be relative", value)
	}
	if candidate == ".." || strings.HasPrefix(candidate, "../") {
		return "", fmt.Errorf("dataset_relpath %q escapes root", value)
	}
	return candidate, nil
}
