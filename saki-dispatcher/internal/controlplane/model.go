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
	Lifecycle             db.Looplifecycle
	CurrentIteration      int
	MaxRounds             int
	QueryBatchSize        int
	MinNewLabelsPerRound  int
	ModelArch             string
	Config                []byte
	LastConfirmedCommitID *uuid.UUID
}

type roundRow struct {
	ID                            uuid.UUID
	RoundIndex                    int
	AttemptIndex                  int
	SummaryStatus                 db.Roundstatus
	EndedAt                       *time.Time
	ConfirmedAt                   *time.Time
	ConfirmedRevealedCount        int
	ConfirmedSelectedCount        int
	ConfirmedEffectiveMinRequired int
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
	RoundIndex       int
	Attempt          int
	Status           db.Stepstatus
	UpdatedAt        *time.Time
	DependsOnStepIDs []uuid.UUID
	Params           *structpb.Struct
	Resources        *runtimecontrolv1.ResourceSummary

	dependsOnRaw       []byte
	paramsRaw          []byte
	roundParamsRaw     []byte
	resourcesRaw       []byte
	roundInputCommitID *uuid.UUID
}

type loopModeStepSpec struct {
	StepType     db.Steptype
	DispatchKind db.Stepdispatchkind
	Phase        db.Loopphase
}

var loopModeStepPlan = map[db.Loopmode][]loopModeStepSpec{
	modeAL: {
		{StepType: db.SteptypeTRAIN, DispatchKind: db.StepdispatchkindDISPATCHABLE, Phase: phaseALTrain},
		{StepType: db.SteptypeEVAL, DispatchKind: db.StepdispatchkindDISPATCHABLE, Phase: phaseALEval},
		{StepType: db.SteptypeSCORE, DispatchKind: db.StepdispatchkindDISPATCHABLE, Phase: phaseALScore},
		{StepType: db.SteptypeSELECT, DispatchKind: db.StepdispatchkindORCHESTRATOR, Phase: phaseALSelect},
	},
	modeSIM: {
		{StepType: db.SteptypeTRAIN, DispatchKind: db.StepdispatchkindDISPATCHABLE, Phase: phaseSimTrain},
		{StepType: db.SteptypeEVAL, DispatchKind: db.StepdispatchkindDISPATCHABLE, Phase: phaseSimEval},
		{StepType: db.SteptypeSCORE, DispatchKind: db.StepdispatchkindDISPATCHABLE, Phase: phaseSimScore},
		{StepType: db.SteptypeSELECT, DispatchKind: db.StepdispatchkindORCHESTRATOR, Phase: phaseSimSelect},
	},
	modeManual: {
		{StepType: db.SteptypeTRAIN, DispatchKind: db.StepdispatchkindDISPATCHABLE, Phase: phaseManualTrain},
		{StepType: db.SteptypeEVAL, DispatchKind: db.StepdispatchkindDISPATCHABLE, Phase: phaseManualEval},
	},
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
		Lifecycle:             record.Lifecycle,
		CurrentIteration:      int(record.CurrentIteration),
		MaxRounds:             int(record.MaxRounds),
		QueryBatchSize:        int(record.QueryBatchSize),
		MinNewLabelsPerRound:  int(record.MinNewLabelsPerRound),
		ModelArch:             record.ModelArch,
		Config:                record.Config,
		LastConfirmedCommitID: record.LastConfirmedCommitID,
	}
}

func mapLoopByID(record db.GetLoopByIDRow) loopRow {
	return loopRow{
		ID:                    record.ID,
		ProjectID:             record.ProjectID,
		BranchID:              record.BranchID,
		Mode:                  record.Mode,
		Phase:                 record.Phase,
		Lifecycle:             record.Lifecycle,
		CurrentIteration:      int(record.CurrentIteration),
		MaxRounds:             int(record.MaxRounds),
		QueryBatchSize:        int(record.QueryBatchSize),
		MinNewLabelsPerRound:  int(record.MinNewLabelsPerRound),
		ModelArch:             record.ModelArch,
		Config:                record.Config,
		LastConfirmedCommitID: record.LastConfirmedCommitID,
	}
}

func mapLatestRound(record db.GetLatestRoundByLoopRow) roundRow {
	return roundRow{
		ID:                            record.ID,
		RoundIndex:                    int(record.RoundIndex),
		AttemptIndex:                  int(record.AttemptIndex),
		SummaryStatus:                 record.SummaryStatus,
		EndedAt:                       timestampPtr(record.EndedAt),
		ConfirmedAt:                   timestampPtr(record.ConfirmedAt),
		ConfirmedRevealedCount:        int(record.ConfirmedRevealedCount),
		ConfirmedSelectedCount:        int(record.ConfirmedSelectedCount),
		ConfirmedEffectiveMinRequired: int(record.ConfirmedEffectiveMinRequired),
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
		UpdatedAt:          timestampPtr(record.UpdatedAt),
		dependsOnRaw:       record.DependsOnRaw,
		paramsRaw:          record.ParamsRaw,
		InputCommitID:      record.InputCommitID,
		LoopID:             record.LoopID,
		ProjectID:          record.ProjectID,
		PluginID:           record.PluginID,
		Mode:               record.Mode,
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

func stepPlanByMode(mode db.Loopmode) []loopModeStepSpec {
	specs, ok := loopModeStepPlan[mode]
	if !ok || len(specs) == 0 {
		return nil
	}
	result := make([]loopModeStepSpec, len(specs))
	copy(result, specs)
	return result
}

func phaseForStep(mode db.Loopmode, stepType db.Steptype) (db.Loopphase, bool) {
	for _, item := range stepPlanByMode(mode) {
		if item.StepType == stepType {
			return item.Phase, true
		}
	}
	return "", false
}

func toRuntimeTaskType(raw db.Steptype) runtimecontrolv1.RuntimeTaskType {
	switch raw {
	case db.SteptypeTRAIN:
		return runtimecontrolv1.RuntimeTaskType_TRAIN
	case db.SteptypeEVAL:
		return runtimecontrolv1.RuntimeTaskType_EVAL
	case db.SteptypeSCORE:
		return runtimecontrolv1.RuntimeTaskType_SCORE
	case db.SteptypeSELECT:
		return runtimecontrolv1.RuntimeTaskType_SELECT
	case db.SteptypePREDICT:
		return runtimecontrolv1.RuntimeTaskType_PREDICT
	case db.SteptypeCUSTOM:
		return runtimecontrolv1.RuntimeTaskType_CUSTOM
	default:
		return runtimecontrolv1.RuntimeTaskType_RUNTIME_TASK_TYPE_UNSPECIFIED
	}
}

func toRuntimeTaskDispatchKind(raw db.Stepdispatchkind) runtimecontrolv1.RuntimeTaskDispatchKind {
	switch raw {
	case db.StepdispatchkindDISPATCHABLE:
		return runtimecontrolv1.RuntimeTaskDispatchKind_DISPATCHABLE
	case db.StepdispatchkindORCHESTRATOR:
		return runtimecontrolv1.RuntimeTaskDispatchKind_ORCHESTRATOR
	default:
		return runtimecontrolv1.RuntimeTaskDispatchKind_RUNTIME_TASK_DISPATCH_KIND_UNSPECIFIED
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

func runtimeStatusToStepStatus(status runtimecontrolv1.RuntimeTaskStatus) db.Stepstatus {
	switch status {
	case runtimecontrolv1.RuntimeTaskStatus_PENDING:
		return stepPending
	case runtimecontrolv1.RuntimeTaskStatus_DISPATCHING:
		return stepDispatching
	case runtimecontrolv1.RuntimeTaskStatus_SYNCING_ENV:
		return stepSyncingEnv
	case runtimecontrolv1.RuntimeTaskStatus_PROBING_RUNTIME:
		return stepProbingRt
	case runtimecontrolv1.RuntimeTaskStatus_BINDING_DEVICE:
		return stepBindingDev
	case runtimecontrolv1.RuntimeTaskStatus_RUNNING:
		return stepRunning
	case runtimecontrolv1.RuntimeTaskStatus_RETRYING:
		return stepRetrying
	case runtimecontrolv1.RuntimeTaskStatus_SUCCEEDED:
		return stepSucceeded
	case runtimecontrolv1.RuntimeTaskStatus_FAILED:
		return stepFailed
	case runtimecontrolv1.RuntimeTaskStatus_CANCELLED:
		return stepCancelled
	case runtimecontrolv1.RuntimeTaskStatus_SKIPPED:
		return stepSkipped
	default:
		return ""
	}
}
