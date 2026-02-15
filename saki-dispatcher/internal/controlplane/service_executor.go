package controlplane

import (
	"context"
	"strings"

	"github.com/google/uuid"

	runtimecontrolv1 "github.com/elebirds/saki/saki-dispatcher/internal/gen/runtimecontrolv1"
	db "github.com/elebirds/saki/saki-dispatcher/internal/gen/sqlc"
)

func (s *Service) OnExecutorRegister(ctx context.Context, register *runtimecontrolv1.Register) error {
	if !s.dbEnabled() || register == nil {
		return nil
	}
	executorID := strings.TrimSpace(register.GetExecutorId())
	if executorID == "" {
		return nil
	}
	version := strings.TrimSpace(register.GetVersion())

	pluginPayloadJSON, err := marshalJSON(map[string]any{
		"plugins": pluginCapabilitiesToMaps(register.GetPlugins()),
	})
	if err != nil {
		return err
	}
	resourcesJSON, err := marshalJSON(resourceSummaryToMap(register.GetResources()))
	if err != nil {
		return err
	}

	executorPGID, err := toPGUUID(uuid.NewString())
	if err != nil {
		return err
	}
	return s.queries.UpsertRuntimeExecutorOnRegister(ctx, db.UpsertRuntimeExecutorOnRegisterParams{
		ExecutorRowID: executorPGID,
		ExecutorID:    executorID,
		Version:       version,
		PluginIds:     []byte(pluginPayloadJSON),
		Resources:     []byte(resourcesJSON),
	})
}

func (s *Service) OnExecutorHeartbeat(ctx context.Context, heartbeat *runtimecontrolv1.Heartbeat) error {
	if !s.dbEnabled() || heartbeat == nil {
		return nil
	}
	executorID := strings.TrimSpace(heartbeat.GetExecutorId())
	if executorID == "" {
		return nil
	}

	status := "idle"
	if heartbeat.GetBusy() {
		status = "busy"
	}
	currentStepID := strings.TrimSpace(heartbeat.GetCurrentStepId())
	resourcesJSON, err := marshalJSON(resourceSummaryToMap(heartbeat.GetResources()))
	if err != nil {
		return err
	}

	executorPGID, err := toPGUUID(uuid.NewString())
	if err != nil {
		return err
	}
	return s.queries.UpsertRuntimeExecutorOnHeartbeat(ctx, db.UpsertRuntimeExecutorOnHeartbeatParams{
		ExecutorRowID: executorPGID,
		ExecutorID:    executorID,
		Status:        status,
		CurrentStepID: toNullablePGText(currentStepID),
		Resources:     []byte(resourcesJSON),
	})
}

func (s *Service) OnExecutorDisconnected(ctx context.Context, executorID string, reason string) error {
	if !s.dbEnabled() {
		return nil
	}
	executorID = strings.TrimSpace(executorID)
	if executorID == "" {
		return nil
	}

	return s.queries.UpdateRuntimeExecutorDisconnected(ctx, db.UpdateRuntimeExecutorDisconnectedParams{
		Reason:     toNullablePGText(reason),
		ExecutorID: executorID,
	})
}
