package runtime

import (
	"slices"
	"sync"
)

// SlotManager 是 agent 本地并发真相：
// controlplane 只能看到心跳上报的 running_task_ids，不能替 agent 持有隐藏队列。
// admission 满了就立即拒绝，避免把排队语义偷偷塞回 controlplane/agent 边界里。
type SlotManager struct {
	mu    sync.Mutex
	slots map[string]*activeExecution
	limit int
}

func NewSlotManager(limit int) *SlotManager {
	return &SlotManager{
		slots: make(map[string]*activeExecution),
		limit: normalizeServiceMaxConcurrency(limit),
	}
}

func (m *SlotManager) Admit(execution *activeExecution) error {
	if execution == nil || execution.executionID == "" {
		return errAgentBusy
	}

	m.mu.Lock()
	defer m.mu.Unlock()

	if len(m.slots) >= m.limit {
		return errAgentBusy
	}
	m.slots[execution.executionID] = execution
	return nil
}

func (m *SlotManager) Cancel(taskID, executionID string) bool {
	m.mu.Lock()
	execution, ok := m.slots[executionID]
	if !ok || execution == nil || execution.taskID != taskID {
		m.mu.Unlock()
		return false
	}
	cancel := execution.cancel
	m.mu.Unlock()

	if cancel != nil {
		cancel()
	}
	return true
}

func (m *SlotManager) Release(executionID string) {
	if executionID == "" {
		return
	}

	m.mu.Lock()
	defer m.mu.Unlock()
	delete(m.slots, executionID)
}

func (m *SlotManager) RunningTaskIDs() []string {
	m.mu.Lock()
	defer m.mu.Unlock()

	taskIDs := make([]string, 0, len(m.slots))
	for _, execution := range m.slots {
		if execution == nil || execution.taskID == "" {
			continue
		}
		taskIDs = append(taskIDs, execution.taskID)
	}
	slices.Sort(taskIDs)
	return taskIDs
}
