package dispatch

import (
	"fmt"
	"sort"
	"strings"
	"sync"
	"time"

	"github.com/google/uuid"

	runtimecontrolv1 "github.com/elebirds/saki/saki-dispatcher/internal/gen/runtimecontrolv1"
)

type ExecutorSession struct {
	ExecutorID string
	Version    string
	PluginIDs  []string

	Busy          bool
	CurrentTaskID string
	Status        string
	IsOnline      bool
	LastSeen      time.Time
	LastError     string

	Queue chan *runtimecontrolv1.RuntimeMessage
}

type PendingAssign struct {
	RequestID  string
	TaskID     string
	ExecutorID string
	CreatedAt  time.Time
}

type AssignTaskAckContext struct {
	RequestID  string
	TaskID     string
	ExecutorID string
	Status     runtimecontrolv1.AckStatus
	Reason     runtimecontrolv1.AckReason
	Detail     string
}

type Dispatcher struct {
	mu sync.RWMutex

	sessions map[string]*ExecutorSession

	pendingAssign map[string]PendingAssign
	pendingStop   map[string]string
	queuedTasks   map[string]struct{}
}

type SummarySnapshot struct {
	OnlineExecutors   int64
	BusyExecutors     int64
	PendingAssign     int64
	PendingStop       int64
	QueuedTaskCount   int64
	LatestHeartbeatAt time.Time
}

type ExecutorSnapshot struct {
	ExecutorID string
	Version    string
	Status     string
	IsOnline   bool

	CurrentTaskID string
	LastSeen      time.Time
	LastError     string

	PendingAssign int64
	PendingStop   int64
}

func NewDispatcher() *Dispatcher {
	return &Dispatcher{
		sessions:      map[string]*ExecutorSession{},
		pendingAssign: map[string]PendingAssign{},
		pendingStop:   map[string]string{},
		queuedTasks:   map[string]struct{}{},
	}
}

func (d *Dispatcher) RegisterExecutor(register *runtimecontrolv1.Register) (*ExecutorSession, error) {
	executorID := strings.TrimSpace(register.GetExecutorId())
	if executorID == "" {
		return nil, fmt.Errorf("executor_id 不能为空")
	}

	pluginIDs := make([]string, 0, len(register.GetPlugins()))
	for _, item := range register.GetPlugins() {
		pluginID := strings.TrimSpace(item.GetPluginId())
		if pluginID == "" {
			continue
		}
		pluginIDs = append(pluginIDs, pluginID)
	}
	sort.Strings(pluginIDs)

	d.mu.Lock()
	defer d.mu.Unlock()

	now := time.Now().UTC()
	existing := d.sessions[executorID]
	if existing == nil {
		existing = &ExecutorSession{
			ExecutorID: executorID,
			Queue:      make(chan *runtimecontrolv1.RuntimeMessage, 128),
		}
		d.sessions[executorID] = existing
	}
	existing.Version = register.GetVersion()
	existing.PluginIDs = pluginIDs
	existing.Busy = false
	existing.CurrentTaskID = ""
	existing.Status = "idle"
	existing.IsOnline = true
	existing.LastSeen = now
	return existing, nil
}

func (d *Dispatcher) UnregisterExecutor(executorID string) {
	executorID = strings.TrimSpace(executorID)
	if executorID == "" {
		return
	}

	d.mu.Lock()
	defer d.mu.Unlock()

	if session, ok := d.sessions[executorID]; ok {
		session.IsOnline = false
		session.Status = "offline"
		session.Busy = false
		session.CurrentTaskID = ""
		session.LastSeen = time.Now().UTC()
	}
	for requestID, pending := range d.pendingAssign {
		if pending.ExecutorID == executorID {
			delete(d.pendingAssign, requestID)
		}
	}
}

func (d *Dispatcher) HandleHeartbeat(heartbeat *runtimecontrolv1.Heartbeat) error {
	executorID := strings.TrimSpace(heartbeat.GetExecutorId())
	if executorID == "" {
		return fmt.Errorf("executor_id 不能为空")
	}

	d.mu.Lock()
	defer d.mu.Unlock()

	session := d.sessions[executorID]
	if session == nil {
		return fmt.Errorf("executor 尚未注册: %s", executorID)
	}
	session.Busy = heartbeat.GetBusy()
	currentTaskID := strings.TrimSpace(heartbeat.GetCurrentTaskId())
	session.CurrentTaskID = currentTaskID
	session.Status = "idle"
	if session.Busy {
		session.Status = "busy"
	}
	session.IsOnline = true
	session.LastSeen = time.Now().UTC()
	return nil
}

func (d *Dispatcher) HandleAck(ack *runtimecontrolv1.Ack) *AssignTaskAckContext {
	if ack == nil {
		return nil
	}
	d.mu.Lock()
	defer d.mu.Unlock()

	switch ack.GetType() {
	case runtimecontrolv1.AckType_ACK_TYPE_ASSIGN_TASK:
		pending, ok := d.pendingAssign[ack.GetAckFor()]
		if ok {
			delete(d.pendingAssign, ack.GetAckFor())
			if ack.GetStatus() != runtimecontrolv1.AckStatus_OK {
				if session := d.sessions[pending.ExecutorID]; session != nil && session.CurrentTaskID == pending.TaskID {
					session.Busy = false
					session.CurrentTaskID = ""
					session.Status = "idle"
				}
			}
			return &AssignTaskAckContext{
				RequestID:  pending.RequestID,
				TaskID:     pending.TaskID,
				ExecutorID: pending.ExecutorID,
				Status:     ack.GetStatus(),
				Reason:     ack.GetReason(),
				Detail:     strings.TrimSpace(ack.GetDetail()),
			}
		}
	case runtimecontrolv1.AckType_ACK_TYPE_STOP_TASK:
		delete(d.pendingStop, ack.GetAckFor())
	}
	return nil
}

func (d *Dispatcher) GetQueue(executorID string) <-chan *runtimecontrolv1.RuntimeMessage {
	executorID = strings.TrimSpace(executorID)
	if executorID == "" {
		return nil
	}

	d.mu.RLock()
	session := d.sessions[executorID]
	d.mu.RUnlock()
	if session == nil {
		return nil
	}

	return session.Queue
}

func (d *Dispatcher) PickExecutor(pluginID string) (string, bool) {
	pluginID = strings.TrimSpace(pluginID)
	d.mu.RLock()
	defer d.mu.RUnlock()

	candidates := make([]*ExecutorSession, 0, len(d.sessions))
	for _, session := range d.sessions {
		if !session.IsOnline || session.Busy {
			continue
		}
		if !supportsPlugin(session, pluginID) {
			continue
		}
		candidates = append(candidates, session)
	}
	if len(candidates) == 0 {
		return "", false
	}
	sort.Slice(candidates, func(i, j int) bool {
		return candidates[i].LastSeen.After(candidates[j].LastSeen)
	})
	return candidates[0].ExecutorID, true
}

func (d *Dispatcher) IsExecutorAvailable(executorID string, pluginID string) bool {
	executorID = strings.TrimSpace(executorID)
	pluginID = strings.TrimSpace(pluginID)
	if executorID == "" {
		return false
	}
	d.mu.RLock()
	defer d.mu.RUnlock()

	session := d.sessions[executorID]
	if session == nil || !session.IsOnline || session.Busy {
		return false
	}
	return supportsPlugin(session, pluginID)
}

func supportsPlugin(session *ExecutorSession, pluginID string) bool {
	if session == nil {
		return false
	}
	pluginID = strings.TrimSpace(pluginID)
	if pluginID == "" || len(session.PluginIDs) == 0 {
		return true
	}
	for _, item := range session.PluginIDs {
		if strings.TrimSpace(item) == pluginID {
			return true
		}
	}
	return false
}

func (d *Dispatcher) DispatchTask(executorID string, requestID string, task *runtimecontrolv1.TaskPayload) bool {
	executorID = strings.TrimSpace(executorID)
	requestID = strings.TrimSpace(requestID)
	if executorID == "" || requestID == "" || task == nil {
		return false
	}
	taskID := strings.TrimSpace(task.GetTaskId())
	if taskID == "" {
		return false
	}

	d.mu.Lock()
	defer d.mu.Unlock()

	session := d.sessions[executorID]
	if session == nil || !session.IsOnline || session.Busy {
		return false
	}

	message := &runtimecontrolv1.RuntimeMessage{
		Payload: &runtimecontrolv1.RuntimeMessage_AssignTask{
			AssignTask: &runtimecontrolv1.AssignTask{
				RequestId: requestID,
				Task:      task,
			},
		},
	}
	select {
	case session.Queue <- message:
		d.pendingAssign[requestID] = PendingAssign{
			RequestID:  requestID,
			TaskID:     taskID,
			ExecutorID: executorID,
			CreatedAt:  time.Now().UTC(),
		}
		session.Busy = true
		session.CurrentTaskID = taskID
		session.Status = "busy"
		return true
	default:
		return false
	}
}

func (d *Dispatcher) StopTask(taskID string, reason string) (string, bool) {
	taskID = strings.TrimSpace(taskID)
	if taskID == "" {
		return "", false
	}
	requestID := uuid.NewString()
	reason = strings.TrimSpace(reason)
	if reason == "" {
		reason = "用户请求停止"
	}

	d.mu.Lock()
	defer d.mu.Unlock()

	var target *ExecutorSession
	for _, session := range d.sessions {
		if !session.IsOnline {
			continue
		}
		if session.CurrentTaskID == taskID {
			target = session
			break
		}
	}
	if target == nil {
		return requestID, false
	}

	message := &runtimecontrolv1.RuntimeMessage{
		Payload: &runtimecontrolv1.RuntimeMessage_StopTask{
			StopTask: &runtimecontrolv1.StopTask{
				RequestId: requestID,
				TaskId:    taskID,
				Reason:    reason,
			},
		},
	}
	select {
	case target.Queue <- message:
		d.pendingStop[requestID] = taskID
		return requestID, true
	default:
		return requestID, false
	}
}

func (d *Dispatcher) QueueTask(taskID string) {
	taskID = strings.TrimSpace(taskID)
	if taskID == "" {
		return
	}
	d.mu.Lock()
	defer d.mu.Unlock()
	d.queuedTasks[taskID] = struct{}{}
}

func (d *Dispatcher) DrainQueuedTaskIDs() []string {
	d.mu.Lock()
	defer d.mu.Unlock()

	ids := make([]string, 0, len(d.queuedTasks))
	for taskID := range d.queuedTasks {
		ids = append(ids, taskID)
		delete(d.queuedTasks, taskID)
	}
	sort.Strings(ids)
	return ids
}

func (d *Dispatcher) Summary() SummarySnapshot {
	d.mu.RLock()
	defer d.mu.RUnlock()

	snapshot := SummarySnapshot{
		PendingAssign:   int64(len(d.pendingAssign)),
		PendingStop:     int64(len(d.pendingStop)),
		QueuedTaskCount: int64(len(d.queuedTasks)),
	}
	for _, session := range d.sessions {
		if !session.IsOnline {
			continue
		}
		snapshot.OnlineExecutors++
		if session.Busy {
			snapshot.BusyExecutors++
		}
		if snapshot.LatestHeartbeatAt.IsZero() || snapshot.LatestHeartbeatAt.Before(session.LastSeen) {
			snapshot.LatestHeartbeatAt = session.LastSeen
		}
	}
	return snapshot
}

func (d *Dispatcher) ListExecutors() []ExecutorSnapshot {
	d.mu.RLock()
	defer d.mu.RUnlock()

	items := make([]ExecutorSnapshot, 0, len(d.sessions))
	for executorID, session := range d.sessions {
		items = append(items, ExecutorSnapshot{
			ExecutorID:    executorID,
			Version:       session.Version,
			Status:        session.Status,
			IsOnline:      session.IsOnline,
			CurrentTaskID: session.CurrentTaskID,
			LastSeen:      session.LastSeen,
			LastError:     session.LastError,
			PendingAssign: d.countPendingAssign(executorID),
			PendingStop:   d.countPendingStopByTask(session.CurrentTaskID),
		})
	}
	sort.Slice(items, func(i, j int) bool {
		if items[i].IsOnline != items[j].IsOnline {
			return items[i].IsOnline
		}
		return items[i].LastSeen.After(items[j].LastSeen)
	})
	return items
}

func (d *Dispatcher) GetExecutor(executorID string) (ExecutorSnapshot, bool) {
	executorID = strings.TrimSpace(executorID)
	d.mu.RLock()
	defer d.mu.RUnlock()

	session := d.sessions[executorID]
	if session == nil {
		return ExecutorSnapshot{}, false
	}
	return ExecutorSnapshot{
		ExecutorID:    executorID,
		Version:       session.Version,
		Status:        session.Status,
		IsOnline:      session.IsOnline,
		CurrentTaskID: session.CurrentTaskID,
		LastSeen:      session.LastSeen,
		LastError:     session.LastError,
		PendingAssign: d.countPendingAssign(executorID),
		PendingStop:   d.countPendingStopByTask(session.CurrentTaskID),
	}, true
}

func (d *Dispatcher) countPendingAssign(executorID string) int64 {
	var total int64
	for _, pending := range d.pendingAssign {
		if pending.ExecutorID == executorID {
			total++
		}
	}
	return total
}

func (d *Dispatcher) countPendingStopByTask(taskID string) int64 {
	if strings.TrimSpace(taskID) == "" {
		return 0
	}
	var total int64
	for _, pendingTaskID := range d.pendingStop {
		if pendingTaskID == taskID {
			total++
		}
	}
	return total
}
