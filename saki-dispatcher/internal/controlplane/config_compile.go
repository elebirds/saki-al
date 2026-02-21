package controlplane

import (
	"crypto/sha256"
	"encoding/binary"
	"encoding/json"
	"fmt"
	"strings"

	"github.com/google/uuid"
	"github.com/spf13/cast"
	"google.golang.org/protobuf/types/known/structpb"

	db "github.com/elebirds/saki/saki-dispatcher/internal/gen/sqlc"
)

func compileRoundConfig(loop loopRow, roundIndex int) map[string]any {
	loopConfig, _ := parseJSONObject(loop.Config)
	pluginConfig := cast.ToStringMap(loopConfig["plugin"])
	modeConfig := cast.ToStringMap(loopConfig["mode"])
	reproConfig := cast.ToStringMap(loopConfig["reproducibility"])
	executionConfig := cast.ToStringMap(loopConfig["execution"])

	globalSeed := strings.TrimSpace(cast.ToString(reproConfig["global_seed"]))
	if globalSeed == "" {
		globalSeed = loop.ID.String()
	}
	splitSeed := deriveScopedSeed(globalSeed, loop.ID, roundIndex, "split")
	trainSeed := deriveScopedSeed(globalSeed, loop.ID, roundIndex, "train")
	samplingSeed := deriveScopedSeed(globalSeed, loop.ID, roundIndex, "sampling")

	deterministicLevel := strings.TrimSpace(cast.ToString(reproConfig["deterministic_level"]))
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
	sampling := cast.ToStringMap(fields["sampling"])
	strategy := strings.TrimSpace(cast.ToString(sampling["strategy"]))
	if strategy == "" {
		strategy = strings.TrimSpace(cast.ToString(fields["query_strategy"]))
	}
	return strategy
}

func extractSamplingStrategyAndTopK(
	loopConfig map[string]any,
	params *structpb.Struct,
	fallbackTopk int,
) (string, int) {
	fields := structToMap(params)
	sampling := cast.ToStringMap(fields["sampling"])
	strategy := strings.TrimSpace(cast.ToString(sampling["strategy"]))
	if strategy == "" {
		strategy = strings.TrimSpace(cast.ToString(loopConfig["query_strategy"]))
	}
	topk := cast.ToInt(sampling["topk"])
	if topk <= 0 {
		topk = cast.ToInt(fields["topk"])
	}
	if topk <= 0 {
		topk = max(1, fallbackTopk)
	}
	return strategy, topk
}

func compileSamplingConfig(loop loopRow, loopConfig map[string]any) map[string]any {
	sampling := cast.ToStringMap(loopConfig["sampling"])
	strategy := strings.TrimSpace(cast.ToString(sampling["strategy"]))
	if strategy == "" {
		strategy = "random_baseline"
	}
	topk := cast.ToInt(sampling["topk"])
	if topk <= 0 {
		topk = max(1, loop.QueryBatchSize)
	}
	unlabeledPageSize := cast.ToInt(sampling["unlabeled_page_size"])
	if unlabeledPageSize <= 0 {
		unlabeledPageSize = 1000
	}
	minCandidatesRequired := cast.ToInt(sampling["min_candidates_required"])
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
