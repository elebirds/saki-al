package controlplane

import (
	"strings"

	db "github.com/elebirds/saki/saki-dispatcher/internal/gen/sqlc"
)

func mapLoopForUpdate(record db.GetLoopForUpdateRow) loopRow {
	return loopRow{
		ID:                    record.ID,
		ProjectID:             record.ProjectID,
		BranchID:              record.BranchID,
		Mode:                  asString(record.Mode),
		Phase:                 asString(record.Phase),
		Status:                asString(record.Status),
		CurrentIteration:      int(record.CurrentIteration),
		MaxRounds:             int(record.MaxRounds),
		QueryBatchSize:        int(record.QueryBatchSize),
		QueryStrategy:         record.QueryStrategy,
		ModelArch:             record.ModelArch,
		GlobalConfig:          asString(record.GlobalConfig),
		LastConfirmedCommitID: asString(record.LastConfirmedCommitID),
	}
}

func mapLatestRound(record db.GetLatestRoundByLoopRow) roundRow {
	return roundRow{
		ID:            record.ID,
		RoundIndex:    int(record.RoundIndex),
		SummaryStatus: asString(record.SummaryStatus),
		EndedAt:       timestampPtr(record.EndedAt),
	}
}

func mapLoopStoppableSteps(rows []db.ListLoopStoppableStepsRow) []stoppingStep {
	items := make([]stoppingStep, 0, len(rows))
	for _, row := range rows {
		item := stoppingStep{
			ID:      row.ID,
			State:   asString(row.State),
			Attempt: int(row.Attempt),
		}
		if row.UpdatedAt.Valid {
			item.UpdatedAt = row.UpdatedAt.Time
		}
		items = append(items, item)
	}
	return items
}

func mapStepPayload(record db.GetStepPayloadByIDForUpdateRow) (stepDispatchPayload, error) {
	row := stepDispatchPayload{
		StepID:             record.StepID,
		RoundID:            record.RoundID,
		Status:             asString(record.Status),
		StepType:           asString(record.StepType),
		DispatchKind:       asString(record.DispatchKind),
		RoundIndex:         int(record.RoundIndex),
		Attempt:            int(record.Attempt),
		dependsOnRaw:       asString(record.DependsOnRaw),
		paramsRaw:          asString(record.ParamsRaw),
		InputCommitID:      asString(record.InputCommitID),
		LoopID:             record.LoopID,
		ProjectID:          record.ProjectID,
		PluginID:           record.PluginID,
		Mode:               asString(record.Mode),
		QueryStrategy:      record.QueryStrategy,
		roundParamsRaw:     asString(record.RoundParamsRaw),
		resourcesRaw:       asString(record.ResourcesRaw),
		roundInputCommitID: asString(record.RoundInputCommitID),
	}
	if strings.TrimSpace(row.InputCommitID) == "" {
		row.InputCommitID = row.roundInputCommitID
	}
	var parseErr error
	row.DependsOnStepIDs, parseErr = parseJSONStrings(row.dependsOnRaw)
	if parseErr != nil {
		return stepDispatchPayload{}, parseErr
	}
	row.Params, parseErr = toStruct(row.paramsRaw)
	if parseErr != nil {
		return stepDispatchPayload{}, parseErr
	}
	if row.Params == nil || len(row.Params.GetFields()) == 0 {
		row.Params, parseErr = toStruct(row.roundParamsRaw)
		if parseErr != nil {
			return stepDispatchPayload{}, parseErr
		}
	}
	row.Resources = toResourceSummary(row.resourcesRaw)
	return row, nil
}
