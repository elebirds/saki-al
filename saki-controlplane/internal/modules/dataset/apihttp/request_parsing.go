package apihttp

import (
	"errors"

	"github.com/google/uuid"
)

func parseDatasetID(raw string) (uuid.UUID, error) {
	datasetID, err := uuid.Parse(raw)
	if err != nil {
		return uuid.Nil, errors.New("invalid dataset_id")
	}
	return datasetID, nil
}

func parseSampleID(raw string) (uuid.UUID, error) {
	sampleID, err := uuid.Parse(raw)
	if err != nil {
		return uuid.Nil, errors.New("invalid sample_id")
	}
	return sampleID, nil
}
