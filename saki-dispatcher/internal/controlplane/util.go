package controlplane

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgtype"
	"google.golang.org/protobuf/types/known/structpb"

	runtimecontrolv1 "github.com/elebirds/saki/saki-dispatcher/internal/gen/runtimecontrolv1"
	db "github.com/elebirds/saki/saki-dispatcher/internal/gen/sqlc"
)

func parseUUID(raw string) (uuid.UUID, error) {
	return uuid.Parse(strings.TrimSpace(raw))
}

func parseUUIDs(raw []string) ([]uuid.UUID, error) {
	items := make([]uuid.UUID, 0, len(raw))
	for _, item := range raw {
		id, err := parseUUID(item)
		if err != nil {
			return nil, err
		}
		items = append(items, id)
	}
	return items, nil
}

func parseNullableUUID(raw string) (*uuid.UUID, error) {
	value := strings.TrimSpace(raw)
	if value == "" {
		return nil, nil
	}
	id, err := parseUUID(value)
	if err != nil {
		return nil, err
	}
	return &id, nil
}

func toPGText(raw string) pgtype.Text {
	return pgtype.Text{
		String: strings.TrimSpace(raw),
		Valid:  true,
	}
}

func toNullablePGText(raw string) pgtype.Text {
	value := strings.TrimSpace(raw)
	if value == "" {
		return pgtype.Text{}
	}
	return pgtype.Text{String: value, Valid: true}
}

func toPGTimestamp(ts time.Time) pgtype.Timestamp {
	return pgtype.Timestamp{
		Time:  ts,
		Valid: true,
	}
}

func toPGInt4(value *int) pgtype.Int4 {
	if value == nil {
		return pgtype.Int4{}
	}
	return pgtype.Int4{Int32: int32(*value), Valid: true}
}

func timestampPtr(ts pgtype.Timestamp) *time.Time {
	if !ts.Valid {
		return nil
	}
	value := ts.Time.UTC()
	return &value
}

func toStruct(raw []byte) (*structpb.Struct, error) {
	if len(raw) == 0 {
		raw = []byte(`{}`)
	}
	payload := map[string]any{}
	if err := json.Unmarshal(raw, &payload); err != nil {
		return &structpb.Struct{}, nil
	}
	structPayload, err := structpb.NewStruct(payload)
	if err != nil {
		return &structpb.Struct{}, nil
	}
	return structPayload, nil
}

func marshalJSON(value any) (string, error) {
	encoded, err := json.Marshal(value)
	if err != nil {
		return "", err
	}
	return string(encoded), nil
}

func marshalArtifacts(items []*runtimecontrolv1.ArtifactItem) (string, error) {
	artifacts := map[string]any{}
	for _, item := range items {
		name := strings.TrimSpace(item.GetName())
		if name == "" {
			continue
		}
		artifacts[name] = map[string]any{
			"kind": strings.TrimSpace(item.GetKind()),
			"uri":  strings.TrimSpace(item.GetUri()),
			"meta": structToMap(item.GetMeta()),
		}
	}
	return marshalJSON(artifacts)
}

func parseJSONObject(raw []byte) (map[string]any, error) {
	if len(raw) == 0 {
		return map[string]any{}, nil
	}
	payload := map[string]any{}
	if err := json.Unmarshal(raw, &payload); err != nil {
		return map[string]any{}, nil
	}
	return payload, nil
}

func structToMap(payload *structpb.Struct) map[string]any {
	if payload == nil {
		return map[string]any{}
	}
	items := payload.AsMap()
	if items == nil {
		return map[string]any{}
	}
	return items
}

func decodeStepEvent(event *runtimecontrolv1.StepEvent) (string, map[string]any, db.Stepstatus) {
	if event == nil {
		return "", map[string]any{}, ""
	}
	switch payload := event.GetEventPayload().(type) {
	case *runtimecontrolv1.StepEvent_StatusEvent:
		statusValue := runtimeStatusToStepStatus(payload.StatusEvent.GetStatus())
		return "status", map[string]any{
			"status": string(statusValue),
			"reason": strings.TrimSpace(payload.StatusEvent.GetReason()),
		}, statusValue
	case *runtimecontrolv1.StepEvent_LogEvent:
		return "log", map[string]any{
			"level":   strings.TrimSpace(payload.LogEvent.GetLevel()),
			"message": payload.LogEvent.GetMessage(),
		}, ""
	case *runtimecontrolv1.StepEvent_ProgressEvent:
		return "progress", map[string]any{
			"epoch":       int(payload.ProgressEvent.GetEpoch()),
			"step":        int(payload.ProgressEvent.GetStep()),
			"total_steps": int(payload.ProgressEvent.GetTotalSteps()),
			"eta_sec":     int(payload.ProgressEvent.GetEtaSec()),
		}, ""
	case *runtimecontrolv1.StepEvent_MetricEvent:
		metrics := map[string]float64{}
		for metricName, metricValue := range payload.MetricEvent.GetMetrics() {
			metrics[metricName] = metricValue
		}
		return "metric", map[string]any{
			"step":    int(payload.MetricEvent.GetStep()),
			"epoch":   int(payload.MetricEvent.GetEpoch()),
			"metrics": metrics,
		}, ""
	case *runtimecontrolv1.StepEvent_ArtifactEvent:
		artifact := payload.ArtifactEvent.GetArtifact()
		if artifact == nil {
			return "artifact", map[string]any{}, ""
		}
		return "artifact", map[string]any{
			"kind": strings.TrimSpace(artifact.GetKind()),
			"name": strings.TrimSpace(artifact.GetName()),
			"uri":  strings.TrimSpace(artifact.GetUri()),
			"meta": structToMap(artifact.GetMeta()),
		}, ""
	case *runtimecontrolv1.StepEvent_ArtifactLocalReadyEvent:
		return "artifact_local_ready", map[string]any{
			"relative_path": strings.TrimSpace(payload.ArtifactLocalReadyEvent.GetRelativePath()),
			"size_bytes":    payload.ArtifactLocalReadyEvent.GetSizeBytes(),
			"sha256":        strings.TrimSpace(payload.ArtifactLocalReadyEvent.GetSha256()),
			"kind":          strings.TrimSpace(payload.ArtifactLocalReadyEvent.GetKind()),
			"required":      payload.ArtifactLocalReadyEvent.GetRequired(),
		}, ""
	case *runtimecontrolv1.StepEvent_ArtifactUploadedEvent:
		return "artifact_uploaded", map[string]any{
			"relative_path": strings.TrimSpace(payload.ArtifactUploadedEvent.GetRelativePath()),
			"storage_uri":   strings.TrimSpace(payload.ArtifactUploadedEvent.GetStorageUri()),
			"etag":          strings.TrimSpace(payload.ArtifactUploadedEvent.GetEtag()),
			"checksum":      strings.TrimSpace(payload.ArtifactUploadedEvent.GetChecksum()),
			"kind":          strings.TrimSpace(payload.ArtifactUploadedEvent.GetKind()),
			"required":      payload.ArtifactUploadedEvent.GetRequired(),
		}, ""
	default:
		return "log", map[string]any{
			"level":   "WARN",
			"message": "unknown runtime event payload",
		}, ""
	}
}

func stepEventTime(tsMillis int64) time.Time {
	if tsMillis <= 0 {
		return time.Now().UTC()
	}
	return time.UnixMilli(tsMillis).UTC()
}

func ptrInt(value int) *int {
	return &value
}

func parseJSONUUIDs(raw []byte) ([]uuid.UUID, error) {
	if len(raw) == 0 {
		return []uuid.UUID{}, nil
	}
	var result []string
	if err := json.Unmarshal(raw, &result); err != nil {
		return []uuid.UUID{}, nil
	}
	items := make([]uuid.UUID, 0, len(result))
	for _, item := range result {
		value := strings.TrimSpace(item)
		if value == "" {
			continue
		}
		parsed, err := uuid.Parse(value)
		if err != nil {
			return nil, err
		}
		items = append(items, parsed)
	}
	return items, nil
}

func parseJSONStringMap(raw []byte) (map[string]string, error) {
	result := map[string]string{}
	if len(raw) == 0 {
		return result, nil
	}
	payload := map[string]any{}
	if err := json.Unmarshal(raw, &payload); err != nil {
		return result, nil
	}
	for key, value := range payload {
		trimmed := strings.TrimSpace(key)
		if trimmed == "" {
			continue
		}
		result[trimmed] = fmt.Sprintf("%v", value)
	}
	return result, nil
}

func toResourceSummary(raw []byte) *runtimecontrolv1.ResourceSummary {
	if len(raw) == 0 {
		return &runtimecontrolv1.ResourceSummary{}
	}
	payload := map[string]any{}
	if err := json.Unmarshal(raw, &payload); err != nil {
		return &runtimecontrolv1.ResourceSummary{}
	}
	summary := &runtimecontrolv1.ResourceSummary{}
	if value, ok := payload["gpu_count"].(float64); ok {
		summary.GpuCount = int32(value)
	}
	if value, ok := payload["cpu_workers"].(float64); ok {
		summary.CpuWorkers = int32(value)
	}
	if value, ok := payload["memory_mb"].(float64); ok {
		summary.MemoryMb = int32(value)
	}
	if ids, ok := payload["gpu_device_ids"].([]any); ok {
		for _, item := range ids {
			if numeric, ok := item.(float64); ok {
				summary.GpuDeviceIds = append(summary.GpuDeviceIds, int32(numeric))
			}
		}
	}
	return summary
}

func pluginCapabilitiesToMaps(plugins []*runtimecontrolv1.PluginCapability) []map[string]any {
	items := make([]map[string]any, 0, len(plugins))
	for _, item := range plugins {
		if item == nil {
			continue
		}
		pluginID := strings.TrimSpace(item.GetPluginId())
		if pluginID == "" {
			continue
		}
		supportedAccelerators := make([]string, 0, len(item.GetSupportedAccelerators()))
		for _, accelerator := range item.GetSupportedAccelerators() {
			text := strings.ToLower(strings.TrimSpace(strings.TrimPrefix(accelerator.String(), "ACCELERATOR_TYPE_")))
			if text == "" || text == "unspecified" {
				continue
			}
			supportedAccelerators = append(supportedAccelerators, text)
		}
		items = append(items, map[string]any{
			"plugin_id":              pluginID,
			"display_name":           strings.TrimSpace(item.GetDisplayName()),
			"version":                strings.TrimSpace(item.GetVersion()),
			"supported_step_types":   normalizeStringSlice(item.GetSupportedStepTypes()),
			"supported_strategies":   normalizeStringSlice(item.GetSupportedStrategies()),
			"supported_accelerators": supportedAccelerators,
			"supports_auto_fallback": item.GetSupportsAutoFallback(),
			"request_config_schema":  structToMap(item.GetRequestConfigSchema()),
			"default_request_config": structToMap(item.GetDefaultRequestConfig()),
		})
	}
	return items
}

func resourceSummaryToMap(summary *runtimecontrolv1.ResourceSummary) map[string]any {
	if summary == nil {
		return map[string]any{}
	}
	accelerators := make([]map[string]any, 0, len(summary.GetAccelerators()))
	for _, item := range summary.GetAccelerators() {
		if item == nil {
			continue
		}
		acceleratorType := strings.ToLower(strings.TrimSpace(strings.TrimPrefix(item.GetType().String(), "ACCELERATOR_TYPE_")))
		if acceleratorType == "" {
			acceleratorType = "unspecified"
		}
		accelerators = append(accelerators, map[string]any{
			"type":         acceleratorType,
			"available":    item.GetAvailable(),
			"device_count": item.GetDeviceCount(),
			"device_ids":   normalizeStringSlice(item.GetDeviceIds()),
		})
	}
	gpuDeviceIDs := make([]int32, 0, len(summary.GetGpuDeviceIds()))
	for _, item := range summary.GetGpuDeviceIds() {
		gpuDeviceIDs = append(gpuDeviceIDs, item)
	}
	return map[string]any{
		"gpu_count":      summary.GetGpuCount(),
		"gpu_device_ids": gpuDeviceIDs,
		"cpu_workers":    summary.GetCpuWorkers(),
		"memory_mb":      summary.GetMemoryMb(),
		"accelerators":   accelerators,
	}
}

func normalizeStringSlice(raw []string) []string {
	items := make([]string, 0, len(raw))
	for _, item := range raw {
		value := strings.TrimSpace(item)
		if value == "" {
			continue
		}
		items = append(items, value)
	}
	return items
}

func extractOracleCommitID(rawConfig []byte) string {
	payload := map[string]any{}
	if err := json.Unmarshal(rawConfig, &payload); err != nil {
		return ""
	}
	modeRaw, ok := payload["mode"]
	if !ok {
		// fallback for legacy payload
		simulationRaw, legacyOK := payload["simulation"]
		if !legacyOK {
			return ""
		}
		simulationMap, mapOK := simulationRaw.(map[string]any)
		if !mapOK {
			return ""
		}
		return strings.TrimSpace(fmt.Sprintf("%v", simulationMap["oracle_commit_id"]))
	}
	modeMap, ok := modeRaw.(map[string]any)
	if !ok {
		return ""
	}
	return strings.TrimSpace(fmt.Sprintf("%v", modeMap["oracle_commit_id"]))
}

func extractRoundResources(rawConfig []byte) map[string]any {
	payload := map[string]any{}
	if err := json.Unmarshal(rawConfig, &payload); err != nil {
		return nil
	}
	executionRaw, ok := payload["execution"]
	if ok {
		if executionMap, mapOK := executionRaw.(map[string]any); mapOK {
			if resourcesRaw, exists := executionMap["round_resources_default"]; exists {
				if resources, resourcesOK := resourcesRaw.(map[string]any); resourcesOK {
					return resources
				}
			}
		}
	}

	// fallback for legacy payload
	resourcesRaw, ok := payload["round_resources_default"]
	if !ok {
		return nil
	}
	resources, ok := resourcesRaw.(map[string]any)
	if !ok {
		return nil
	}
	return resources
}

func activationCommandID(stepPayload stepDispatchPayload) string {
	inputCommitID := ""
	if stepPayload.InputCommitID != nil {
		inputCommitID = stepPayload.InputCommitID.String()
	}
	raw := fmt.Sprintf(
		"%s:%d:%s:%d:%s",
		stepPayload.LoopID.String(),
		stepPayload.RoundIndex,
		stepPayload.StepID.String(),
		stepPayload.Attempt,
		inputCommitID,
	)
	sum := sha256.Sum256([]byte(raw))
	return "activate_samples:" + hex.EncodeToString(sum[:])
}

func advanceBranchCommandID(stepPayload stepDispatchPayload, commitID uuid.UUID) string {
	raw := fmt.Sprintf(
		"%s:%d:%s:%d:%s",
		stepPayload.LoopID.String(),
		stepPayload.RoundIndex,
		stepPayload.StepID.String(),
		stepPayload.Attempt,
		commitID.String(),
	)
	sum := sha256.Sum256([]byte(raw))
	return "advance_branch:" + hex.EncodeToString(sum[:])
}

func cancelAttemptCommandID(stepID uuid.UUID, attempt int) string {
	raw := fmt.Sprintf("%s:%d", stepID.String(), max(1, attempt))
	sum := sha256.Sum256([]byte(raw))
	return "cancel_attempt:" + hex.EncodeToString(sum[:])
}

func max(a, b int) int {
	if a > b {
		return a
	}
	return b
}

func max64(a, b int64) int64 {
	if a > b {
		return a
	}
	return b
}

func loopAdvisoryKey(loopID uuid.UUID) (int64, bool) {
	value := int64(0)
	for i := 0; i < 8; i++ {
		value = (value << 8) | int64(loopID[i])
	}
	if value < 0 {
		value = -value
	}
	if value == 0 {
		value = 1
	}
	return value, true
}
