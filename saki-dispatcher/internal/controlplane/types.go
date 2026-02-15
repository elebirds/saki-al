package controlplane

import (
	"time"

	"google.golang.org/protobuf/types/known/structpb"

	runtimecontrolv1 "github.com/elebirds/saki/saki-dispatcher/internal/gen/runtimecontrolv1"
)

type loopRow struct {
	ID                    string
	ProjectID             string
	BranchID              string
	Mode                  string
	Phase                 string
	Status                string
	CurrentIteration      int
	MaxRounds             int
	QueryBatchSize        int
	QueryStrategy         string
	ModelArch             string
	GlobalConfig          string
	LastConfirmedCommitID string
}

type roundRow struct {
	ID            string
	RoundIndex    int
	SummaryStatus string
	EndedAt       *time.Time
}

type commandLogEntry struct {
	ID     string
	Status string
	Detail string
}

type stepDispatchPayload struct {
	StepID           string
	RoundID          string
	LoopID           string
	ProjectID        string
	InputCommitID    string
	StepType         string
	DispatchKind     string
	PluginID         string
	Mode             string
	QueryStrategy    string
	RoundIndex       int
	Attempt          int
	Status           string
	DependsOnStepIDs []string
	Params           *structpb.Struct
	Resources        *runtimecontrolv1.ResourceSummary

	dependsOnRaw       string
	paramsRaw          string
	roundParamsRaw     string
	resourcesRaw       string
	roundInputCommitID string
}

// stoppingStep is used by STOPPING drain logic.
type stoppingStep struct {
	ID        string
	State     string
	Attempt   int
	UpdatedAt time.Time
}
