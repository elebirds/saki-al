package controlplane

import (
	"context"
	"encoding/json"
	"sort"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgtype"
	"google.golang.org/protobuf/types/known/structpb"

	"github.com/elebirds/saki/saki-dispatcher/internal/dispatch"
	runtimecontrolv1 "github.com/elebirds/saki/saki-dispatcher/internal/gen/runtimecontrolv1"
	runtimedomainv1 "github.com/elebirds/saki/saki-dispatcher/internal/gen/runtimedomainv1"
	db "github.com/elebirds/saki/saki-dispatcher/internal/gen/sqlc"
)

func (s *Service) PlanNextRuntimeUpdate(
	ctx context.Context,
	snapshot dispatch.ExecutorRuntimeSnapshot,
) (*runtimecontrolv1.RuntimeUpdateCommand, bool, error) {
	if !s.dbEnabled() {
		return nil, false, nil
	}
	rows, err := s.queries.ListRuntimeDesiredReleases(ctx)
	if err != nil {
		return nil, false, err
	}
	if len(rows) == 0 {
		return nil, false, nil
	}

	pluginRows := make([]db.ListRuntimeDesiredReleasesRow, 0)
	executorRows := make([]db.ListRuntimeDesiredReleasesRow, 0, 1)
	for _, row := range rows {
		switch strings.TrimSpace(row.ComponentType) {
		case "plugin":
			pluginRows = append(pluginRows, row)
		case "executor":
			executorRows = append(executorRows, row)
		}
	}
	sort.Slice(pluginRows, func(i, j int) bool {
		return strings.TrimSpace(pluginRows[i].ComponentName) < strings.TrimSpace(pluginRows[j].ComponentName)
	})

	drifted := false
	for _, row := range pluginRows {
		actualVersion := strings.TrimSpace(snapshot.PluginVersions[strings.TrimSpace(row.ComponentName)])
		targetVersion := strings.TrimSpace(row.Version)
		if actualVersion == targetVersion {
			continue
		}
		drifted = true
		if snapshot.Busy || strings.TrimSpace(snapshot.ActiveUpdateRequestID) != "" || s.domainClient == nil || !s.domainClient.Enabled() {
			return nil, true, nil
		}
		command, buildErr := s.buildRuntimeUpdateCommand(ctx, row, actualVersion)
		return command, true, buildErr
	}
	for _, row := range executorRows {
		actualVersion := strings.TrimSpace(snapshot.Version)
		targetVersion := strings.TrimSpace(row.Version)
		if actualVersion == targetVersion {
			continue
		}
		drifted = true
		if snapshot.Busy || strings.TrimSpace(snapshot.ActiveUpdateRequestID) != "" || s.domainClient == nil || !s.domainClient.Enabled() {
			return nil, true, nil
		}
		command, buildErr := s.buildRuntimeUpdateCommand(ctx, row, actualVersion)
		return command, true, buildErr
	}
	return nil, drifted, nil
}

func (s *Service) buildRuntimeUpdateCommand(
	ctx context.Context,
	row db.ListRuntimeDesiredReleasesRow,
	fromVersion string,
) (*runtimecontrolv1.RuntimeUpdateCommand, error) {
	requestID := uuid.NewString()
	ticket, err := s.domainClient.CreateRuntimeReleaseDownloadTicket(ctx, &runtimedomainv1.RuntimeReleaseDownloadTicketRequest{
		RequestId: requestID,
		ReleaseId: row.ReleaseID.String(),
	})
	if err != nil {
		return nil, err
	}
	headers := ticket.GetHeaders()
	downloadURL := strings.TrimSpace(ticket.GetDownloadUrl())

	return &runtimecontrolv1.RuntimeUpdateCommand{
		RequestId:     requestID,
		ComponentType: toRuntimeComponentType(row.ComponentType),
		ComponentName: strings.TrimSpace(row.ComponentName),
		FromVersion:   strings.TrimSpace(fromVersion),
		TargetVersion: strings.TrimSpace(row.Version),
		ReleaseId:     row.ReleaseID.String(),
		DownloadUrl:   downloadURL,
		Headers:       headers,
		Sha256:        strings.TrimSpace(row.Sha256),
		SizeBytes:     uint64(maxInt64(0, row.SizeBytes)),
		Format:        strings.TrimSpace(row.Format),
		Manifest:      toStructFromJSONBytes(row.ManifestJson),
	}, nil
}

func (s *Service) OnRuntimeUpdateQueued(
	ctx context.Context,
	executorID string,
	command *runtimecontrolv1.RuntimeUpdateCommand,
) error {
	if !s.dbEnabled() || command == nil {
		return nil
	}
	_, err := s.queries.InsertRuntimeUpdateAttempt(ctx, db.InsertRuntimeUpdateAttemptParams{
		ID:             uuid.New(),
		ExecutorID:     strings.TrimSpace(executorID),
		ComponentType:  strings.TrimSpace(runtimeComponentTypeToText(command.GetComponentType())),
		ComponentName:  strings.TrimSpace(command.GetComponentName()),
		RequestID:      strings.TrimSpace(command.GetRequestId()),
		FromVersion:    strings.TrimSpace(command.GetFromVersion()),
		TargetVersion:  strings.TrimSpace(command.GetTargetVersion()),
		Status:         "queued",
		Detail:         toNullablePGText("update queued"),
		StartedAt:      toPGTimestamp(time.Now().UTC()),
		EndedAt:        emptyPGTimestamp(),
		RolledBack:     false,
		RollbackDetail: toNullablePGText(""),
	})
	return err
}

func (s *Service) OnRuntimeUpdateEvent(
	ctx context.Context,
	executorID string,
	event *runtimecontrolv1.RuntimeUpdateEvent,
) error {
	if !s.dbEnabled() || event == nil {
		return nil
	}
	status := runtimeUpdatePhaseToText(event.GetPhase())
	if status == "" {
		status = "queued"
	}
	endedAt := emptyPGTimestamp()
	if isTerminalRuntimeUpdatePhase(event.GetPhase()) {
		endedAt = toPGTimestamp(time.Now().UTC())
	}
	rowsAffected, err := s.queries.UpdateRuntimeUpdateAttemptByRequestID(ctx, db.UpdateRuntimeUpdateAttemptByRequestIDParams{
		Status:         status,
		Detail:         toNullablePGText(event.GetDetail()),
		EndedAt:        endedAt,
		RolledBack:     bool(event.GetRolledBack() || event.GetPhase() == runtimecontrolv1.RuntimeUpdatePhase_RUNTIME_UPDATE_PHASE_ROLLED_BACK),
		RollbackDetail: toNullablePGText(event.GetDetail()),
		RequestID:      strings.TrimSpace(event.GetRequestId()),
	})
	if err != nil {
		return err
	}
	if rowsAffected > 0 {
		return nil
	}
	_, err = s.queries.InsertRuntimeUpdateAttempt(ctx, db.InsertRuntimeUpdateAttemptParams{
		ID:             uuid.New(),
		ExecutorID:     strings.TrimSpace(executorID),
		ComponentType:  strings.TrimSpace(runtimeComponentTypeToText(event.GetComponentType())),
		ComponentName:  strings.TrimSpace(event.GetComponentName()),
		RequestID:      strings.TrimSpace(event.GetRequestId()),
		FromVersion:    strings.TrimSpace(event.GetFromVersion()),
		TargetVersion:  strings.TrimSpace(event.GetTargetVersion()),
		Status:         status,
		Detail:         toNullablePGText(event.GetDetail()),
		StartedAt:      toPGTimestamp(time.Now().UTC()),
		EndedAt:        endedAt,
		RolledBack:     bool(event.GetRolledBack() || event.GetPhase() == runtimecontrolv1.RuntimeUpdatePhase_RUNTIME_UPDATE_PHASE_ROLLED_BACK),
		RollbackDetail: toNullablePGText(event.GetDetail()),
	})
	return err
}

func toRuntimeComponentType(raw string) runtimecontrolv1.RuntimeComponentType {
	switch strings.TrimSpace(raw) {
	case "executor":
		return runtimecontrolv1.RuntimeComponentType_EXECUTOR
	case "plugin":
		return runtimecontrolv1.RuntimeComponentType_PLUGIN
	default:
		return runtimecontrolv1.RuntimeComponentType_RUNTIME_COMPONENT_TYPE_UNSPECIFIED
	}
}

func toStructFromJSONBytes(raw []byte) *structpb.Struct {
	payload := map[string]any{}
	if len(raw) > 0 {
		if err := json.Unmarshal(raw, &payload); err != nil {
			payload = map[string]any{}
		}
	}
	result, err := structpb.NewStruct(payload)
	if err != nil {
		return &structpb.Struct{}
	}
	return result
}

func isTerminalRuntimeUpdatePhase(phase runtimecontrolv1.RuntimeUpdatePhase) bool {
	switch phase {
	case runtimecontrolv1.RuntimeUpdatePhase_RUNTIME_UPDATE_PHASE_SUCCEEDED,
		runtimecontrolv1.RuntimeUpdatePhase_RUNTIME_UPDATE_PHASE_FAILED,
		runtimecontrolv1.RuntimeUpdatePhase_RUNTIME_UPDATE_PHASE_ROLLED_BACK:
		return true
	default:
		return false
	}
}

func emptyPGTimestamp() pgtype.Timestamptz {
	return pgtype.Timestamptz{}
}

func maxInt64(a int64, b int64) int64 {
	if a > b {
		return a
	}
	return b
}
