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
	CurrentStepID string
	Status        string
	IsOnline      bool
	LastSeen      time.Time
	LastError     string

	Queue chan *runtimecontrolv1.RuntimeMessage
}

type PendingAssign struct {
	RequestID  string
	StepID     string
	ExecutorID string
	CreatedAt  time.Time
}

type Dispatcher struct {
	mu sync.RWMutex

	sessions map[string]*ExecutorSession

	pendingAssign map[string]PendingAssign
	pendingStop   map[string]string
	queuedSteps   map[string]struct{}
}

type SummarySnapshot struct {
	OnlineExecutors   int64
	BusyExecutors     int64
	PendingAssign     int64
	PendingStop       int64
	QueuedStepCount   int64
	LatestHeartbeatAt time.Time
}

type ExecutorSnapshot struct {
	ExecutorID string
	Version    string
	Status     string
	IsOnline   bool

	CurrentStepID string
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
		queuedSteps:   map[string]struct{}{},
	}
}

func (d *Dispatcher) RegisterExecutor(register *runtimecontrolv1.Register) (*ExecutorSession, error) {
	executorID := strings.TrimSpace(register.GetExecutorId())
	if executorID == "" {
		return nil, fmt.Errorf("executor_id is required")
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
	existing.CurrentStepID = ""
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
		session.CurrentStepID = ""
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
		return fmt.Errorf("executor_id is required")
	}

	d.mu.Lock()
	defer d.mu.Unlock()

	session := d.sessions[executorID]
	if session == nil {
		return fmt.Errorf("executor not registered: %s", executorID)
	}
	session.Busy = heartbeat.GetBusy()
	currentStepID := strings.TrimSpace(heartbeat.GetCurrentStepId())
	session.CurrentStepID = currentStepID
	session.Status = "idle"
	if session.Busy {
		session.Status = "busy"
	}
	session.IsOnline = true
	session.LastSeen = time.Now().UTC()
	return nil
}

func (d *Dispatcher) HandleAck(ack *runtimecontrolv1.Ack) {
	d.mu.Lock()
	defer d.mu.Unlock()

	switch ack.GetType() {
	case runtimecontrolv1.AckType_ACK_TYPE_ASSIGN_STEP:
		pending, ok := d.pendingAssign[ack.GetAckFor()]
		if ok {
			delete(d.pendingAssign, ack.GetAckFor())
			if ack.GetStatus() != runtimecontrolv1.AckStatus_OK {
				if session := d.sessions[pending.ExecutorID]; session != nil && session.CurrentStepID == pending.StepID {
					session.Busy = false
					session.CurrentStepID = ""
					session.Status = "idle"
				}
			}
		}
	case runtimecontrolv1.AckType_ACK_TYPE_STOP_STEP:
		delete(d.pendingStop, ack.GetAckFor())
	}
}

func (d *Dispatcher) EnqueueOutgoing(executorID string, message *runtimecontrolv1.RuntimeMessage) bool {
	executorID = strings.TrimSpace(executorID)
	if executorID == "" || message == nil {
		return false
	}

	d.mu.RLock()
	session := d.sessions[executorID]
	d.mu.RUnlock()
	if session == nil {
		return false
	}

	select {
	case session.Queue <- message:
		return true
	default:
		return false
	}
}

func (d *Dispatcher) PullOutgoing(executorID string, timeout time.Duration) *runtimecontrolv1.RuntimeMessage {
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

	if timeout <= 0 {
		select {
		case message := <-session.Queue:
			return message
		default:
			return nil
		}
	}

	timer := time.NewTimer(timeout)
	defer timer.Stop()
	select {
	case message := <-session.Queue:
		return message
	case <-timer.C:
		return nil
	}
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
		if pluginID != "" && len(session.PluginIDs) > 0 {
			matched := false
			for _, item := range session.PluginIDs {
				if item == pluginID {
					matched = true
					break
				}
			}
			if !matched {
				continue
			}
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

func (d *Dispatcher) DispatchStep(executorID string, requestID string, step *runtimecontrolv1.StepPayload) bool {
	executorID = strings.TrimSpace(executorID)
	requestID = strings.TrimSpace(requestID)
	if executorID == "" || requestID == "" || step == nil {
		return false
	}
	stepID := strings.TrimSpace(step.GetStepId())
	if stepID == "" {
		return false
	}

	d.mu.Lock()
	defer d.mu.Unlock()

	session := d.sessions[executorID]
	if session == nil || !session.IsOnline || session.Busy {
		return false
	}

	message := &runtimecontrolv1.RuntimeMessage{
		Payload: &runtimecontrolv1.RuntimeMessage_AssignStep{
			AssignStep: &runtimecontrolv1.AssignStep{
				RequestId: requestID,
				Step:      step,
			},
		},
	}
	select {
	case session.Queue <- message:
		d.pendingAssign[requestID] = PendingAssign{
			RequestID:  requestID,
			StepID:     stepID,
			ExecutorID: executorID,
			CreatedAt:  time.Now().UTC(),
		}
		session.Busy = true
		session.CurrentStepID = stepID
		session.Status = "busy"
		return true
	default:
		return false
	}
}

func (d *Dispatcher) StopStep(stepID string, reason string) (string, bool) {
	stepID = strings.TrimSpace(stepID)
	if stepID == "" {
		return "", false
	}
	requestID := uuid.NewString()
	reason = strings.TrimSpace(reason)
	if reason == "" {
		reason = "user requested stop"
	}

	d.mu.Lock()
	defer d.mu.Unlock()

	var target *ExecutorSession
	for _, session := range d.sessions {
		if !session.IsOnline {
			continue
		}
		if session.CurrentStepID == stepID {
			target = session
			break
		}
	}
	if target == nil {
		return requestID, false
	}

	message := &runtimecontrolv1.RuntimeMessage{
		Payload: &runtimecontrolv1.RuntimeMessage_StopStep{
			StopStep: &runtimecontrolv1.StopStep{
				RequestId: requestID,
				StepId:    stepID,
				Reason:    reason,
			},
		},
	}
	select {
	case target.Queue <- message:
		d.pendingStop[requestID] = stepID
		return requestID, true
	default:
		return requestID, false
	}
}

func (d *Dispatcher) QueueStep(stepID string) {
	stepID = strings.TrimSpace(stepID)
	if stepID == "" {
		return
	}
	d.mu.Lock()
	defer d.mu.Unlock()
	d.queuedSteps[stepID] = struct{}{}
}

func (d *Dispatcher) DrainQueuedStepIDs() []string {
	d.mu.Lock()
	defer d.mu.Unlock()

	ids := make([]string, 0, len(d.queuedSteps))
	for stepID := range d.queuedSteps {
		ids = append(ids, stepID)
		delete(d.queuedSteps, stepID)
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
		QueuedStepCount: int64(len(d.queuedSteps)),
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
			CurrentStepID: session.CurrentStepID,
			LastSeen:      session.LastSeen,
			LastError:     session.LastError,
			PendingAssign: d.countPendingAssign(executorID),
			PendingStop:   d.countPendingStopByStep(session.CurrentStepID),
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
		CurrentStepID: session.CurrentStepID,
		LastSeen:      session.LastSeen,
		LastError:     session.LastError,
		PendingAssign: d.countPendingAssign(executorID),
		PendingStop:   d.countPendingStopByStep(session.CurrentStepID),
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

func (d *Dispatcher) countPendingStopByStep(stepID string) int64 {
	if strings.TrimSpace(stepID) == "" {
		return 0
	}
	var total int64
	for _, pendingStepID := range d.pendingStop {
		if pendingStepID == stepID {
			total++
		}
	}
	return total
}
