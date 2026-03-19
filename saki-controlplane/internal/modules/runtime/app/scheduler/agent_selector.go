package scheduler

import (
	"slices"

	"github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/app/commands"
)

type AgentSelector struct{}

var _ commands.AssignTaskAgentSelector = (*AgentSelector)(nil)

func NewAgentSelector() *AgentSelector {
	return &AgentSelector{}
}

func (*AgentSelector) SelectAgent(task commands.PendingTask, agents []commands.AgentRecord) *commands.AgentRecord {
	// 当前迁移阶段还没有把任务能力声明落成独立持久化列；
	// selector 只消费 PendingTask.RequiredCapabilities，空集合就按“通用任务”处理。
	requiredCapabilities := slices.Clone(task.RequiredCapabilities)
	var best *commands.AgentRecord
	var bestAvailableSlots int32 = -1

	for i := range agents {
		candidate := agents[i]
		if candidate.Status != "online" {
			continue
		}
		if !agentSupportsAll(candidate.Capabilities, requiredCapabilities) {
			continue
		}

		maxConcurrency := candidate.MaxConcurrency
		if maxConcurrency <= 0 {
			maxConcurrency = commands.DefaultAgentMaxConcurrency
		}
		availableSlots := maxConcurrency - int32(len(candidate.RunningTaskIDs))
		if availableSlots <= 0 {
			continue
		}

		if best == nil ||
			availableSlots > bestAvailableSlots ||
			(availableSlots == bestAvailableSlots && candidate.LastSeenAt.After(best.LastSeenAt)) ||
			(availableSlots == bestAvailableSlots && candidate.LastSeenAt.Equal(best.LastSeenAt) && candidate.ID < best.ID) {
			selected := candidate
			selected.Capabilities = slices.Clone(candidate.Capabilities)
			selected.RunningTaskIDs = slices.Clone(candidate.RunningTaskIDs)
			best = &selected
			bestAvailableSlots = availableSlots
		}
	}

	return best
}

func agentSupportsAll(capabilities, required []string) bool {
	if len(required) == 0 {
		return true
	}

	lookup := make(map[string]struct{}, len(capabilities))
	for _, capability := range capabilities {
		lookup[capability] = struct{}{}
	}
	for _, capability := range required {
		if _, ok := lookup[capability]; !ok {
			return false
		}
	}
	return true
}
