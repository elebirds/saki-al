package controlplane

import (
	"time"

	"github.com/google/uuid"
	"google.golang.org/protobuf/types/known/structpb"

	runtimecontrolv1 "github.com/elebirds/saki/saki-dispatcher/internal/gen/runtimecontrolv1"
	db "github.com/elebirds/saki/saki-dispatcher/internal/gen/sqlc"
)

type loopRow struct {
	ID                    uuid.UUID
	ProjectID             uuid.UUID
	BranchID              uuid.UUID
	Mode                  db.Loopmode
	Phase                 db.Loopphase
	Status                db.Loopstatus
	CurrentIteration      int
	MaxRounds             int
	QueryBatchSize        int
	QueryStrategy         string
	ModelArch             string
	GlobalConfig          []byte
	LastConfirmedCommitID *uuid.UUID
}

type roundRow struct {
	ID            uuid.UUID
	RoundIndex    int
	SummaryStatus db.Roundstatus
	EndedAt       *time.Time
}

type commandLogEntry struct {
	ID     uuid.UUID
	Status string
	Detail string
}

type stepDispatchPayload struct {
	StepID           uuid.UUID
	RoundID          uuid.UUID
	LoopID           uuid.UUID
	ProjectID        uuid.UUID
	InputCommitID    *uuid.UUID
	StepType         db.Steptype
	DispatchKind     db.Stepdispatchkind
	PluginID         string
	Mode             db.Loopmode
	QueryStrategy    string
	RoundIndex       int
	Attempt          int
	Status           db.Stepstatus
	DependsOnStepIDs []uuid.UUID
	Params           *structpb.Struct
	Resources        *runtimecontrolv1.ResourceSummary

	dependsOnRaw       []byte
	paramsRaw          []byte
	roundParamsRaw     []byte
	resourcesRaw       []byte
	roundInputCommitID *uuid.UUID
}

// stoppingStep is used by STOPPING drain logic.
type stoppingStep struct {
	ID        uuid.UUID
	State     db.Stepstatus
	Attempt   int
	UpdatedAt time.Time
}

func mapLoopForUpdate(record db.GetLoopForUpdateRow) loopRow {
	return loopRow{
		ID:                    record.ID,
		ProjectID:             record.ProjectID,
		BranchID:              record.BranchID,
		Mode:                  record.Mode,
		Phase:                 record.Phase,
		Status:                record.Status,
		CurrentIteration:      int(record.CurrentIteration),
		MaxRounds:             int(record.MaxRounds),
		QueryBatchSize:        int(record.QueryBatchSize),
		QueryStrategy:         record.QueryStrategy,
		ModelArch:             record.ModelArch,
		GlobalConfig:          record.GlobalConfig,
		LastConfirmedCommitID: record.LastConfirmedCommitID,
	}
}

func mapLatestRound(record db.GetLatestRoundByLoopRow) roundRow {
	return roundRow{
		ID:            record.ID,
		RoundIndex:    int(record.RoundIndex),
		SummaryStatus: record.SummaryStatus,
		EndedAt:       timestampPtr(record.EndedAt),
	}
}

func mapLoopStoppableSteps(rows []db.ListLoopStoppableStepsRow) []stoppingStep {
	items := make([]stoppingStep, 0, len(rows))
	for _, row := range rows {
		item := stoppingStep{
			ID:      row.ID,
			State:   row.State,
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
		Status:             record.Status,
		StepType:           record.StepType,
		DispatchKind:       record.DispatchKind,
		RoundIndex:         int(record.RoundIndex),
		Attempt:            int(record.Attempt),
		dependsOnRaw:       record.DependsOnRaw,
		paramsRaw:          record.ParamsRaw,
		InputCommitID:      record.InputCommitID,
		LoopID:             record.LoopID,
		ProjectID:          record.ProjectID,
		PluginID:           record.PluginID,
		Mode:               record.Mode,
		QueryStrategy:      record.QueryStrategy,
		roundParamsRaw:     record.RoundParamsRaw,
		resourcesRaw:       record.ResourcesRaw,
		roundInputCommitID: record.RoundInputCommitID,
	}
	if row.InputCommitID == nil {
		row.InputCommitID = row.roundInputCommitID
	}
	var parseErr error
	row.DependsOnStepIDs, parseErr = parseJSONUUIDs(row.dependsOnRaw)
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

func stepSpecsByMode(mode db.Loopmode) []db.Steptype {
	switch mode {
	case modeSIM:
		return []db.Steptype{
			db.SteptypeTRAIN,
			db.SteptypeSCORE,
			db.SteptypeEVAL,
			db.SteptypeSELECT,
			db.SteptypeACTIVATESAMPLES,
			db.SteptypeADVANCEBRANCH,
		}
	case modeManual:
		return []db.Steptype{
			db.SteptypeTRAIN,
			db.SteptypeEVAL,
			db.SteptypeEXPORT,
		}
	default:
		return []db.Steptype{
			db.SteptypeTRAIN,
			db.SteptypeSCORE,
			db.SteptypeEVAL,
			db.SteptypeSELECT,
		}
	}
}

func toRuntimeStepType(raw db.Steptype) runtimecontrolv1.RuntimeStepType {
	switch raw {
	case db.SteptypeTRAIN:
		return runtimecontrolv1.RuntimeStepType_TRAIN
	case db.SteptypeSCORE:
		return runtimecontrolv1.RuntimeStepType_SCORE
	case db.SteptypeSELECT:
		return runtimecontrolv1.RuntimeStepType_SELECT
	case db.SteptypeACTIVATESAMPLES:
		return runtimecontrolv1.RuntimeStepType_ACTIVATE_SAMPLES
	case db.SteptypeADVANCEBRANCH:
		return runtimecontrolv1.RuntimeStepType_ADVANCE_BRANCH
	case db.SteptypeWAITANNOTATION:
		return runtimecontrolv1.RuntimeStepType_WAIT_ANNOTATION
	case db.SteptypeEVAL:
		return runtimecontrolv1.RuntimeStepType_EVAL
	case db.SteptypeEXPORT:
		return runtimecontrolv1.RuntimeStepType_EXPORT
	case db.SteptypeUPLOADARTIFACT:
		return runtimecontrolv1.RuntimeStepType_UPLOAD_ARTIFACT
	case db.Steptype("CUSTOM"):
		return runtimecontrolv1.RuntimeStepType_CUSTOM
	default:
		return runtimecontrolv1.RuntimeStepType_RUNTIME_STEP_TYPE_UNSPECIFIED
	}
}

func toRuntimeStepDispatchKind(raw db.Stepdispatchkind) runtimecontrolv1.RuntimeStepDispatchKind {
	switch raw {
	case db.StepdispatchkindDISPATCHABLE:
		return runtimecontrolv1.RuntimeStepDispatchKind_DISPATCHABLE
	case db.StepdispatchkindORCHESTRATOR:
		return runtimecontrolv1.RuntimeStepDispatchKind_ORCHESTRATOR
	default:
		return runtimecontrolv1.RuntimeStepDispatchKind_RUNTIME_STEP_DISPATCH_KIND_UNSPECIFIED
	}
}

func toRuntimeLoopMode(raw db.Loopmode) runtimecontrolv1.RuntimeLoopMode {
	switch raw {
	case modeAL:
		return runtimecontrolv1.RuntimeLoopMode_ACTIVE_LEARNING
	case modeSIM:
		return runtimecontrolv1.RuntimeLoopMode_SIMULATION
	case modeManual:
		return runtimecontrolv1.RuntimeLoopMode_MANUAL
	default:
		return runtimecontrolv1.RuntimeLoopMode_RUNTIME_LOOP_MODE_UNSPECIFIED
	}
}

func runtimeStatusToStepStatus(status runtimecontrolv1.RuntimeStepStatus) db.Stepstatus {
	switch status {
	case runtimecontrolv1.RuntimeStepStatus_PENDING:
		return stepPending
	case runtimecontrolv1.RuntimeStepStatus_DISPATCHING:
		return stepDispatching
	case runtimecontrolv1.RuntimeStepStatus_RUNNING:
		return stepRunning
	case runtimecontrolv1.RuntimeStepStatus_RETRYING:
		return stepRetrying
	case runtimecontrolv1.RuntimeStepStatus_SUCCEEDED:
		return stepSucceeded
	case runtimecontrolv1.RuntimeStepStatus_FAILED:
		return stepFailed
	case runtimecontrolv1.RuntimeStepStatus_CANCELLED:
		return stepCancelled
	case runtimecontrolv1.RuntimeStepStatus_SKIPPED:
		return stepSkipped
	default:
		return ""
	}
}
