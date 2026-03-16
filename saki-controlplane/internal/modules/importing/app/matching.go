package app

import (
	"context"
	"errors"
	"path"
	"strings"

	importrepo "github.com/elebirds/saki/saki-controlplane/internal/modules/importing/repo"
	"github.com/google/uuid"
	"github.com/saki-ai/saki/shared/saki-ir/go/formats/common"
)

var (
	ErrAmbiguousSampleMatch = errors.New("ambiguous sample match")
	ErrSampleNotMatched     = errors.New("sample not matched")
)

type SampleMatchFinder interface {
	FindExact(ctx context.Context, projectID uuid.UUID, refType, refValue string) ([]importrepo.SampleMatchRef, error)
}

type sampleMatchDecision struct {
	SampleID uuid.UUID
	Strategy string
	Warning  *common.ConversionIssue
}

func matchSampleRef(ctx context.Context, store SampleMatchFinder, projectID uuid.UUID, ref common.SampleRef) (sampleMatchDecision, error) {
	if matches, err := store.FindExact(ctx, projectID, "dataset_relpath", ref.NormalizedValue); err != nil {
		return sampleMatchDecision{}, err
	} else if len(matches) == 1 {
		return sampleMatchDecision{SampleID: matches[0].SampleID, Strategy: "dataset_relpath"}, nil
	} else if len(matches) > 1 {
		return sampleMatchDecision{}, ErrAmbiguousSampleMatch
	}

	sampleName := deriveSampleName(ref.NormalizedValue)
	if sampleName != "" {
		if matches, err := store.FindExact(ctx, projectID, "sample_name", sampleName); err != nil {
			return sampleMatchDecision{}, err
		} else if len(matches) == 1 {
			return sampleMatchDecision{SampleID: matches[0].SampleID, Strategy: "sample_name"}, nil
		} else if len(matches) > 1 {
			return sampleMatchDecision{}, ErrAmbiguousSampleMatch
		}
	}

	basename := path.Base(ref.NormalizedValue)
	if basename != "" && basename != "." {
		if matches, err := store.FindExact(ctx, projectID, "basename", basename); err != nil {
			return sampleMatchDecision{}, err
		} else if len(matches) == 1 {
			return sampleMatchDecision{
				SampleID: matches[0].SampleID,
				Strategy: "basename",
				Warning: &common.ConversionIssue{
					Code:    "SAMPLE_MATCH_BY_BASENAME",
					Message: "样本通过 basename fallback 匹配",
				},
			}, nil
		} else if len(matches) > 1 {
			return sampleMatchDecision{}, ErrAmbiguousSampleMatch
		}
	}

	return sampleMatchDecision{}, ErrSampleNotMatched
}

func deriveSampleName(normalizedRelpath string) string {
	base := path.Base(normalizedRelpath)
	if base == "." || base == "" {
		return ""
	}
	ext := path.Ext(base)
	return strings.TrimSuffix(base, ext)
}
