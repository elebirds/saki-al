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
	"github.com/spf13/cast"
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

func toPGTimestamp(ts time.Time) pgtype.Timestamptz {
	return pgtype.Timestamptz{
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

func timestampPtr(ts pgtype.Timestamptz) *time.Time {
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

func extractPredictionSnapshotFromReason(reason map[string]any) map[string]any {
	if len(reason) == 0 {
		return map[string]any{}
	}
	if raw, ok := reason["prediction_snapshot"]; ok {
		if payload, ok := raw.(map[string]any); ok && payload != nil {
			return payload
		}
	}
	if raw, ok := reason["predictionSnapshot"]; ok {
		if payload, ok := raw.(map[string]any); ok && payload != nil {
			return payload
		}
	}
	return map[string]any{}
}

func decodeTaskEvent(event *runtimecontrolv1.TaskEvent) (string, map[string]any, db.Runtimetaskstatus) {
	if event == nil {
		return "", map[string]any{}, ""
	}
	switch payload := event.GetEventPayload().(type) {
	case *runtimecontrolv1.TaskEvent_StatusEvent:
		statusValue, _ := runtimeStatusToTaskStatus(payload.StatusEvent.GetStatus())
		statusText := strings.ToLower(strings.TrimSpace(string(statusValue)))
		return "status", map[string]any{
			"status": statusText,
			"reason": strings.TrimSpace(payload.StatusEvent.GetReason()),
		}, statusValue
	case *runtimecontrolv1.TaskEvent_LogEvent:
		message := payload.LogEvent.GetMessage()
		rawMessage := payload.LogEvent.GetRawMessage()
		if strings.TrimSpace(rawMessage) == "" {
			rawMessage = message
		}
		return "log", map[string]any{
			"level":        strings.TrimSpace(payload.LogEvent.GetLevel()),
			"message":      message,
			"raw_message":  rawMessage,
			"message_key":  strings.TrimSpace(payload.LogEvent.GetMessageKey()),
			"message_args": structToMap(payload.LogEvent.GetMessageArgs()),
			"meta":         structToMap(payload.LogEvent.GetMeta()),
		}, ""
	case *runtimecontrolv1.TaskEvent_ProgressEvent:
		return "progress", map[string]any{
			"epoch":       int(payload.ProgressEvent.GetEpoch()),
			"step":        int(payload.ProgressEvent.GetStep()),
			"total_steps": int(payload.ProgressEvent.GetTotalSteps()),
			"eta_sec":     int(payload.ProgressEvent.GetEtaSec()),
		}, ""
	case *runtimecontrolv1.TaskEvent_MetricEvent:
		metrics := map[string]float64{}
		for metricName, metricValue := range payload.MetricEvent.GetMetrics() {
			metrics[metricName] = metricValue
		}
		return "metric", map[string]any{
			"step":    int(payload.MetricEvent.GetStep()),
			"epoch":   int(payload.MetricEvent.GetEpoch()),
			"metrics": metrics,
		}, ""
	case *runtimecontrolv1.TaskEvent_ArtifactEvent:
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
	default:
		return "log", map[string]any{
			"level":   "WARN",
			"message": "unknown runtime event payload",
		}, ""
	}
}

func stepEventTime(tsSeconds int64) time.Time {
	if tsSeconds <= 0 {
		return time.Now().UTC()
	}
	return time.Unix(tsSeconds, 0).UTC()
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

func toResourceSummary(raw []byte) *runtimecontrolv1.ResourceSummary {
	if len(raw) == 0 {
		return &runtimecontrolv1.ResourceSummary{}
	}
	payload := map[string]any{}
	if err := json.Unmarshal(raw, &payload); err != nil {
		return &runtimecontrolv1.ResourceSummary{}
	}
	summary := &runtimecontrolv1.ResourceSummary{}

	// 使用 cast 简化 float64 -> int32 转换
	summary.GpuCount = cast.ToInt32(payload["gpu_count"])
	summary.CpuWorkers = cast.ToInt32(payload["cpu_workers"])
	summary.MemoryMb = cast.ToInt32(payload["memory_mb"])

	if ids, ok := payload["gpu_device_ids"].([]any); ok {
		for _, item := range ids {
			id := cast.ToInt32(item)
			if id != 0 {
				summary.GpuDeviceIds = append(summary.GpuDeviceIds, id)
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
			"supported_task_types":   normalizeStringSlice(item.GetSupportedTaskTypes()),
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
		return ""
	}
	modeMap, ok := modeRaw.(map[string]any)
	if !ok {
		return ""
	}
	oracleRaw, exists := modeMap["oracle_commit_id"]
	if !exists || oracleRaw == nil {
		return ""
	}
	value := strings.TrimSpace(fmt.Sprintf("%v", oracleRaw))
	if value == "" || strings.EqualFold(value, "<nil>") {
		return ""
	}
	return value
}

func extractSimulationFinalizeTrain(rawConfig []byte) bool {
	payload := map[string]any{}
	if err := json.Unmarshal(rawConfig, &payload); err != nil {
		return true
	}
	modeRaw, ok := payload["mode"]
	if !ok {
		return true
	}
	modeMap, ok := modeRaw.(map[string]any)
	if !ok {
		return true
	}
	finalizeRaw, exists := modeMap["finalize_train"]
	if !exists || finalizeRaw == nil {
		return true
	}
	parsed, err := cast.ToBoolE(finalizeRaw)
	if err != nil {
		return true
	}
	return parsed
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
	return nil
}

func cancelAttemptCommandID(stepID uuid.UUID, attempt int) string {
	raw := fmt.Sprintf("%s:%d", stepID.String(), max(1, attempt))
	sum := sha256.Sum256([]byte(raw))
	return "cancel_attempt:" + hex.EncodeToString(sum[:])
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

// uuidSliceToStringSlice 将 []uuid.UUID 转换为 []string
func uuidSliceToStringSlice(ids []uuid.UUID) []string {
	if len(ids) == 0 {
		return []string{}
	}
	result := make([]string, len(ids))
	for i, id := range ids {
		result[i] = id.String()
	}
	return result
}

// stringSliceToUUIDSlice 将 []string 转换为 []uuid.UUID，跳过无效值
func stringSliceToUUIDSlice(items []string) []uuid.UUID {
	result := make([]uuid.UUID, 0, len(items))
	for _, item := range items {
		value := strings.TrimSpace(item)
		if value == "" {
			continue
		}
		parsed, err := uuid.Parse(value)
		if err != nil {
			continue
		}
		result = append(result, parsed)
	}
	return result
}
