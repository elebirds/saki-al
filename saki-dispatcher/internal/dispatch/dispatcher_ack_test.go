package dispatch

import (
	"testing"

	runtimecontrolv1 "github.com/elebirds/saki/saki-dispatcher/internal/gen/runtimecontrolv1"
)

func TestHandleAckAssignRejectedReturnsContextAndClearsBusy(t *testing.T) {
	dispatcher := NewDispatcher()
	_, err := dispatcher.RegisterExecutor(&runtimecontrolv1.Register{
		ExecutorId: "executor-a",
		Version:    "v1",
	})
	if err != nil {
		t.Fatalf("register executor failed: %v", err)
	}
	if ok := dispatcher.DispatchTask("executor-a", "req-1", &runtimecontrolv1.TaskPayload{TaskId: "task-1"}); !ok {
		t.Fatal("dispatch task should succeed")
	}

	ackContext := dispatcher.HandleAck(&runtimecontrolv1.Ack{
		AckFor: "req-1",
		Status: runtimecontrolv1.AckStatus_ERROR,
		Type:   runtimecontrolv1.AckType_ACK_TYPE_ASSIGN_TASK,
		Reason: runtimecontrolv1.AckReason_ACK_REASON_REJECTED,
		Detail: "invalid payload",
	})
	if ackContext == nil {
		t.Fatal("ack context should not be nil")
	}
	if ackContext.TaskID != "task-1" {
		t.Fatalf("unexpected task id: %s", ackContext.TaskID)
	}
	if ackContext.ExecutorID != "executor-a" {
		t.Fatalf("unexpected executor id: %s", ackContext.ExecutorID)
	}
	if len(dispatcher.pendingAssign) != 0 {
		t.Fatalf("pending assign should be empty, got=%d", len(dispatcher.pendingAssign))
	}
	session := dispatcher.sessions["executor-a"]
	if session == nil {
		t.Fatal("session should exist")
	}
	if session.Busy {
		t.Fatal("executor should be marked idle after rejected ack")
	}
	if session.CurrentTaskID != "" {
		t.Fatalf("current task id should be empty, got=%s", session.CurrentTaskID)
	}
}

func TestHandleAckAssignOKKeepsSessionBusyUntilHeartbeat(t *testing.T) {
	dispatcher := NewDispatcher()
	_, err := dispatcher.RegisterExecutor(&runtimecontrolv1.Register{
		ExecutorId: "executor-a",
		Version:    "v1",
	})
	if err != nil {
		t.Fatalf("register executor failed: %v", err)
	}
	if ok := dispatcher.DispatchTask("executor-a", "req-1", &runtimecontrolv1.TaskPayload{TaskId: "task-1"}); !ok {
		t.Fatal("dispatch task should succeed")
	}

	ackContext := dispatcher.HandleAck(&runtimecontrolv1.Ack{
		AckFor: "req-1",
		Status: runtimecontrolv1.AckStatus_OK,
		Type:   runtimecontrolv1.AckType_ACK_TYPE_ASSIGN_TASK,
		Reason: runtimecontrolv1.AckReason_ACK_REASON_ACCEPTED,
	})
	if ackContext == nil {
		t.Fatal("ack context should not be nil")
	}
	session := dispatcher.sessions["executor-a"]
	if session == nil {
		t.Fatal("session should exist")
	}
	if !session.Busy {
		t.Fatal("executor should stay busy before heartbeat update")
	}
	if session.CurrentTaskID != "task-1" {
		t.Fatalf("current task id mismatch: %s", session.CurrentTaskID)
	}
}

func TestHandleAckUnknownRequestReturnsNil(t *testing.T) {
	dispatcher := NewDispatcher()
	ackContext := dispatcher.HandleAck(&runtimecontrolv1.Ack{
		AckFor: "unknown",
		Status: runtimecontrolv1.AckStatus_ERROR,
		Type:   runtimecontrolv1.AckType_ACK_TYPE_ASSIGN_TASK,
		Reason: runtimecontrolv1.AckReason_ACK_REASON_REJECTED,
	})
	if ackContext != nil {
		t.Fatal("unknown ack should not return context")
	}
}
