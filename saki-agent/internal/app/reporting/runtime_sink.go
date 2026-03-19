package reporting

import (
	"context"
	"encoding/json"

	runtimev1 "github.com/elebirds/saki/saki-agent/internal/gen/runtime/v1"
	workerv1 "github.com/elebirds/saki/saki-agent/internal/gen/worker/v1"
)

type TaskEventPusher interface {
	PushTaskEvent(ctx context.Context, envelope *runtimev1.TaskEventEnvelope) error
}

type RuntimeSink struct {
	pusher      TaskEventPusher
	agentID     string
	taskID      string
	executionID string
}

func NewRuntimeSink(pusher TaskEventPusher, agentID, taskID, executionID string) *RuntimeSink {
	return &RuntimeSink{
		pusher:      pusher,
		agentID:     agentID,
		taskID:      taskID,
		executionID: executionID,
	}
}

func (s *RuntimeSink) ReportWorkerEvent(ctx context.Context, event *workerv1.WorkerEvent) error {
	if s.pusher == nil || event == nil {
		return nil
	}

	envelope := &runtimev1.TaskEventEnvelope{
		AgentId:     s.agentID,
		TaskId:      s.taskID,
		ExecutionId: s.executionID,
	}

	switch event.GetEventType() {
	case "progress":
		var payload struct {
			Percent int32  `json:"percent"`
			Message string `json:"message"`
		}
		if err := json.Unmarshal(event.GetPayload(), &payload); err != nil {
			return nil
		}
		envelope.Payload = &runtimev1.TaskEventEnvelope_Progress{
			Progress: &runtimev1.TaskProgressEvent{
				Percent: payload.Percent,
				Message: payload.Message,
			},
		}
	case "log":
		var payload struct {
			Level   string `json:"level"`
			Message string `json:"message"`
		}
		if err := json.Unmarshal(event.GetPayload(), &payload); err != nil {
			return nil
		}
		envelope.Payload = &runtimev1.TaskEventEnvelope_Log{
			Log: &runtimev1.TaskLogEvent{
				Level:   payload.Level,
				Message: payload.Message,
			},
		}
	case "result":
		envelope.Payload = &runtimev1.TaskEventEnvelope_Result{
			Result: &runtimev1.TaskResultEvent{
				Payload: append([]byte(nil), event.GetPayload()...),
			},
		}
	default:
		return nil
	}

	return s.pusher.PushTaskEvent(ctx, envelope)
}
