package controlplane

import (
	"strings"
	"testing"
	"time"

	"github.com/google/uuid"

	runtimecontrolv1 "github.com/elebirds/saki/saki-dispatcher/internal/gen/runtimecontrolv1"
	db "github.com/elebirds/saki/saki-dispatcher/internal/gen/sqlc"
)

func TestAssignAckActionForReason(t *testing.T) {
	cases := []struct {
		reason runtimecontrolv1.AckReason
		want   assignAckAction
	}{
		{reason: runtimecontrolv1.AckReason_ACK_REASON_EXECUTOR_BUSY, want: assignAckActionToReady},
		{reason: runtimecontrolv1.AckReason_ACK_REASON_STOPPING, want: assignAckActionToReady},
		{reason: runtimecontrolv1.AckReason_ACK_REASON_REJECTED, want: assignAckActionToFailed},
		{reason: runtimecontrolv1.AckReason_ACK_REASON_TASK_NOT_RUNNING, want: assignAckActionRetryOrFail},
		{reason: runtimecontrolv1.AckReason_ACK_REASON_UNSPECIFIED, want: assignAckActionNoop},
	}
	for _, tc := range cases {
		got := assignAckActionForReason(tc.reason)
		if got != tc.want {
			t.Fatalf("ack reason mapping mismatch reason=%s got=%v want=%v", tc.reason, got, tc.want)
		}
	}
}

func TestShouldRecoverInFlightCandidate(t *testing.T) {
	now := time.Now().UTC()
	taskID := uuid.New()
	service := &Service{
		heartbeatTimeout:       30 * time.Second,
		inFlightPreRunTimeout:  120 * time.Second,
		inFlightRunningTimeout: 120 * time.Second,
	}

	cases := []struct {
		name  string
		item  inFlightRecoveryCandidate
		want  bool
		match string
	}{
		{
			name: "running offline timeout recovers",
			item: inFlightRecoveryCandidate{
				TaskID:             taskID,
				TaskStatus:         db.RuntimetaskstatusRUNNING,
				TaskUpdatedAt:      now.Add(-3 * time.Minute),
				AssignedExecutorID: "executor-a",
				ExecutorOnline:     false,
			},
			want:  true,
			match: "offline",
		},
		{
			name: "running heartbeat stale recovers",
			item: inFlightRecoveryCandidate{
				TaskID:                taskID,
				TaskStatus:            db.RuntimetaskstatusRUNNING,
				TaskUpdatedAt:         now.Add(-3 * time.Minute),
				AssignedExecutorID:    "executor-a",
				ExecutorOnline:        true,
				ExecutorLastSeenAt:    ptrTime(now.Add(-2 * time.Minute)),
				ExecutorCurrentTaskID: taskID.String(),
			},
			want:  true,
			match: "heartbeat timeout",
		},
		{
			name: "running current task mismatch recovers",
			item: inFlightRecoveryCandidate{
				TaskID:                taskID,
				TaskStatus:            db.RuntimetaskstatusRUNNING,
				TaskUpdatedAt:         now.Add(-3 * time.Minute),
				AssignedExecutorID:    "executor-a",
				ExecutorOnline:        true,
				ExecutorLastSeenAt:    ptrTime(now),
				ExecutorCurrentTaskID: "other-task",
			},
			want:  true,
			match: "mismatch",
		},
		{
			name: "running healthy does not recover",
			item: inFlightRecoveryCandidate{
				TaskID:                taskID,
				TaskStatus:            db.RuntimetaskstatusRUNNING,
				TaskUpdatedAt:         now.Add(-3 * time.Minute),
				AssignedExecutorID:    "executor-a",
				ExecutorOnline:        true,
				ExecutorLastSeenAt:    ptrTime(now.Add(-5 * time.Second)),
				ExecutorCurrentTaskID: taskID.String(),
			},
			want: false,
		},
		{
			name: "pre-run within timeout does not recover",
			item: inFlightRecoveryCandidate{
				TaskID:                taskID,
				TaskStatus:            db.RuntimetaskstatusDISPATCHING,
				TaskUpdatedAt:         now.Add(-30 * time.Second),
				AssignedExecutorID:    "executor-a",
				ExecutorOnline:        false,
				ExecutorCurrentTaskID: taskID.String(),
			},
			want: false,
		},
	}

	for _, tc := range cases {
		got, reason := service.shouldRecoverInFlightCandidate(now, tc.item)
		if got != tc.want {
			t.Fatalf("%s: recover decision mismatch got=%v want=%v reason=%s", tc.name, got, tc.want, reason)
		}
		if tc.want && tc.match != "" && reason != "" && !strings.Contains(reason, tc.match) {
			t.Fatalf("%s: reason mismatch reason=%q match=%q", tc.name, reason, tc.match)
		}
	}
}

func TestBuildAssignAckFailureReason(t *testing.T) {
	got := buildAssignAckFailureReason(runtimecontrolv1.AckReason_ACK_REASON_REJECTED, "round_index invalid")
	if !strings.Contains(got, "reason=rejected") {
		t.Fatalf("reason text should include rejected, got=%s", got)
	}
	if !strings.Contains(got, "round_index invalid") {
		t.Fatalf("reason text should include detail, got=%s", got)
	}
}

func ptrTime(value time.Time) *time.Time {
	v := value
	return &v
}
