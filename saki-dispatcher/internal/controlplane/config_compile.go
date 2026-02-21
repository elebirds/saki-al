package controlplane

import (
	"crypto/sha256"
	"encoding/binary"
	"encoding/json"
	"fmt"
	"strconv"
	"strings"

	"github.com/google/uuid"
	"google.golang.org/protobuf/types/known/structpb"

	db "github.com/elebirds/saki/saki-dispatcher/internal/gen/sqlc"
)

func compileRoundConfig(loop loopRow, roundIndex int) map[string]any {
	loopConfig, _ := parseJSONObject(loop.Config)
	pluginConfig := ensureMap(loopConfig["plugin"])
	modeConfig := ensureMap(loopConfig["mode"])
	reproConfig := ensureMap(loopConfig["reproducibility"])
	executionConfig := ensureMap(loopConfig["execution"])

	globalSeed := strings.TrimSpace(toString(reproConfig["global_seed"]))
	if globalSeed == "" {
		globalSeed = loop.ID.String()
	}
	splitSeed := deriveScopedSeed(globalSeed, loop.ID, roundIndex, "split")
	trainSeed := deriveScopedSeed(globalSeed, loop.ID, roundIndex, "train")
	samplingSeed := deriveScopedSeed(globalSeed, loop.ID, roundIndex, "sampling")

	deterministicLevel := strings.TrimSpace(toString(reproConfig["deterministic_level"]))
	if deterministicLevel == "" {
		deterministicLevel = "standard"
	}
	reproConfig["global_seed"] = globalSeed
	reproConfig["deterministic_level"] = deterministicLevel

	payload := map[string]any{
		"loop_id":         loop.ID.String(),
		"round_index":     roundIndex,
		"mode":            string(loop.Mode),
		"plugin_id":       loop.ModelArch,
		"plugin":          pluginConfig,
		"mode_config":     modeConfig,
		"reproducibility": reproConfig,
		"execution":       executionConfig,
		"split_seed":      int(splitSeed),
		"train_seed":      int(trainSeed),
		"sampling_seed":   int(samplingSeed),
		"deterministic":   isDeterministicLevel(deterministicLevel),
	}
	if loop.Mode != modeManual {
		payload["sampling"] = compileSamplingConfig(loop, loopConfig)
	}
	return payload
}

func compileStepConfig(roundConfig map[string]any, stepType db.Steptype, mode db.Loopmode) map[string]any {
	stepConfig := cloneMap(roundConfig)
	stepConfig["step_type"] = strings.ToLower(string(stepType))
	if mode == modeManual {
		delete(stepConfig, "sampling")
		return stepConfig
	}
	switch stepType {
	case db.SteptypeTRAIN, db.SteptypeSCORE, db.SteptypeCUSTOM:
		return stepConfig
	default:
		// 非采样步骤避免无意义配置噪音
		delete(stepConfig, "sampling")
		return stepConfig
	}
}

func extractSamplingStrategyFromStruct(params *structpb.Struct) string {
	fields := structToMap(params)
	sampling := ensureMap(fields["sampling"])
	strategy := strings.TrimSpace(toString(sampling["strategy"]))
	if strategy == "" {
		strategy = strings.TrimSpace(toString(fields["query_strategy"]))
	}
	return strategy
}

func extractSamplingStrategyAndTopK(
	loopConfig map[string]any,
	params *structpb.Struct,
	fallbackTopk int,
) (string, int) {
	fields := structToMap(params)
	sampling := ensureMap(fields["sampling"])
	strategy := strings.TrimSpace(toString(sampling["strategy"]))
	if strategy == "" {
		strategy = strings.TrimSpace(toString(loopConfig["query_strategy"]))
	}
	topk := toInt(sampling["topk"], 0)
	if topk <= 0 {
		topk = toInt(fields["topk"], 0)
	}
	if topk <= 0 {
		topk = max(1, fallbackTopk)
	}
	return strategy, topk
}

func compileSamplingConfig(loop loopRow, loopConfig map[string]any) map[string]any {
	sampling := ensureMap(loopConfig["sampling"])
	strategy := strings.TrimSpace(toString(sampling["strategy"]))
	if strategy == "" {
		strategy = "random_baseline"
	}
	topk := toInt(sampling["topk"], 0)
	if topk <= 0 {
		topk = max(1, loop.QueryBatchSize)
	}
	unlabeledPageSize := toInt(sampling["unlabeled_page_size"], 1000)
	minCandidatesRequired := toInt(sampling["min_candidates_required"], 1)
	if minCandidatesRequired <= 0 {
		minCandidatesRequired = 1
	}
	return map[string]any{
		"strategy":                strategy,
		"topk":                    topk,
		"unlabeled_page_size":     max(1, unlabeledPageSize),
		"min_candidates_required": minCandidatesRequired,
	}
}

func deriveScopedSeed(globalSeed string, loopID uuid.UUID, roundIndex int, scope string) uint32 {
	raw := fmt.Sprintf("%s:%s:%d:%s", strings.TrimSpace(globalSeed), loopID.String(), roundIndex, scope)
	sum := sha256.Sum256([]byte(raw))
	return binary.BigEndian.Uint32(sum[:4])
}

func isDeterministicLevel(level string) bool {
	switch strings.ToLower(strings.TrimSpace(level)) {
	case "strict", "high", "full", "on", "true", "deterministic":
		return true
	default:
		return false
	}
}

func ensureMap(value any) map[string]any {
	if mapped, ok := value.(map[string]any); ok {
		return mapped
	}
	return map[string]any{}
}

func cloneMap(value map[string]any) map[string]any {
	raw, err := json.Marshal(value)
	if err != nil {
		return map[string]any{}
	}
	out := map[string]any{}
	if err := json.Unmarshal(raw, &out); err != nil {
		return map[string]any{}
	}
	return out
}

func toString(value any) string {
	switch typed := value.(type) {
	case string:
		return typed
	case fmt.Stringer:
		return typed.String()
	default:
		return strings.TrimSpace(fmt.Sprintf("%v", value))
	}
}

func toInt(value any, defaultValue int) int {
	switch typed := value.(type) {
	case int:
		return typed
	case int32:
		return int(typed)
	case int64:
		return int(typed)
	case float32:
		return int(typed)
	case float64:
		return int(typed)
	case string:
		parsed, err := strconv.Atoi(strings.TrimSpace(typed))
		if err == nil {
			return parsed
		}
	}
	return defaultValue
}
