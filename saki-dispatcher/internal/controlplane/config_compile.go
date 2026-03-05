package controlplane

import (
	"crypto/sha256"
	"encoding/binary"
	"encoding/json"
	"fmt"
	"strings"

	"github.com/spf13/cast"
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
		panic(fmt.Sprintf("loop %s missing config.reproducibility.global_seed", loop.ID.String()))
	}
	splitSeed := deriveScopedSeed(globalSeed, "split")
	trainSeed := deriveScopedSeed(globalSeed, "train")
	samplingSeed := deriveScopedSeed(globalSeed, "sampling")

	deterministicLevel := strings.TrimSpace(toString(reproConfig["deterministic_level"]))
	deterministicLevel, deterministicEnabled, strongDeterministicEnabled := parseDeterministicLevel(deterministicLevel)
	reproConfig["global_seed"] = globalSeed
	reproConfig["deterministic_level"] = deterministicLevel

	payload := map[string]any{
		"loop_id":              loop.ID.String(),
		"round_index":          roundIndex,
		"mode":                 string(loop.Mode),
		"plugin_id":            loop.ModelArch,
		"plugin":               pluginConfig,
		"mode_config":          modeConfig,
		"reproducibility":      reproConfig,
		"execution":            executionConfig,
		"split_seed":           int(splitSeed),
		"train_seed":           int(trainSeed),
		"sampling_seed":        int(samplingSeed),
		"deterministic_level":  deterministicLevel,
		"deterministic":        deterministicEnabled,
		"strong_deterministic": strongDeterministicEnabled,
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
	reviewPoolMultiplier := toInt(sampling["review_pool_multiplier"], 3)
	if reviewPoolMultiplier <= 0 {
		reviewPoolMultiplier = 1
	}
	reviewPoolSize := max(topk, topk*reviewPoolMultiplier)
	return map[string]any{
		"strategy":                strategy,
		"topk":                    topk,
		"unlabeled_page_size":     max(1, unlabeledPageSize),
		"min_candidates_required": minCandidatesRequired,
		"review_pool_multiplier":  reviewPoolMultiplier,
		"review_pool_size":        reviewPoolSize,
	}
}

func deriveScopedSeed(globalSeed string, scope string) uint32 {
	raw := fmt.Sprintf("%s:%s", strings.TrimSpace(globalSeed), scope)
	sum := sha256.Sum256([]byte(raw))
	return binary.BigEndian.Uint32(sum[:4])
}

func parseDeterministicLevel(level string) (string, bool, bool) {
	switch strings.ToLower(strings.TrimSpace(level)) {
	case "deterministic":
		return "deterministic", true, false
	case "strong_deterministic":
		return "strong_deterministic", true, true
	default:
		return "off", false, false
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
	result := cast.ToString(value)
	return strings.TrimSpace(result)
}

func toInt(value any, defaultValue int) int {
	result, err := cast.ToIntE(value)
	if err != nil {
		return defaultValue
	}
	return result
}
