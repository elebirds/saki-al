package apihttp

import (
	"errors"

	"github.com/google/uuid"
)

func parseProjectID(raw string) (uuid.UUID, error) {
	projectID, err := uuid.Parse(raw)
	if err != nil {
		return uuid.Nil, errors.New("invalid project_id")
	}
	return projectID, nil
}

func parseDatasetIDs(raw []string) ([]uuid.UUID, error) {
	if len(raw) == 0 {
		return nil, nil
	}

	ids := make([]uuid.UUID, 0, len(raw))
	for _, item := range raw {
		datasetID, err := uuid.Parse(item)
		if err != nil {
			return nil, errors.New("invalid dataset_id")
		}
		ids = append(ids, datasetID)
	}
	return ids, nil
}
