package controlplane

import db "github.com/elebirds/saki/saki-dispatcher/internal/gen/sqlc"

func canLoopLifecycleTransition(from db.Looplifecycle, to db.Looplifecycle) bool {
	if from == to {
		return true
	}
	switch from {
	case db.LooplifecycleDRAFT:
		return to == db.LooplifecycleRUNNING
	case db.LooplifecycleRUNNING:
		return to == db.LooplifecyclePAUSING || to == db.LooplifecyclePAUSED || to == db.LooplifecycleSTOPPING || to == db.LooplifecycleCOMPLETED || to == db.LooplifecycleFAILED
	case db.LooplifecyclePAUSING:
		return to == db.LooplifecyclePAUSED || to == db.LooplifecycleSTOPPING || to == db.LooplifecycleFAILED
	case db.LooplifecyclePAUSED:
		return to == db.LooplifecycleRUNNING || to == db.LooplifecycleSTOPPING
	case db.LooplifecycleFAILED:
		return to == db.LooplifecycleRUNNING
	case db.LooplifecycleSTOPPING:
		return to == db.LooplifecycleSTOPPED || to == db.LooplifecycleFAILED
	case db.LooplifecycleSTOPPED:
		return false
	default:
		return false
	}
}

func isTerminalTaskLifecycle(status db.Runtimetaskstatus) bool {
	switch status {
	case taskSucceeded, taskFailed, taskCancelled, taskSkipped:
		return true
	default:
		return false
	}
}

func taskStatusRank(status db.Runtimetaskstatus) int {
	switch status {
	case taskPending:
		return 0
	case taskReady:
		return 1
	case taskDispatching:
		return 2
	case taskSyncingEnv:
		return 3
	case taskProbingRt:
		return 4
	case taskBindingDev:
		return 5
	case taskRunning:
		return 6
	case taskRetrying:
		return 7
	case taskSucceeded, taskFailed, taskCancelled, taskSkipped:
		return 100
	default:
		return -1
	}
}

func canApplyTaskStatusTransition(from db.Runtimetaskstatus, to db.Runtimetaskstatus) bool {
	if to == "" {
		return false
	}
	if from == "" {
		return true
	}
	if isTerminalTaskLifecycle(from) {
		return false
	}
	if from == to {
		return true
	}
	if isTerminalTaskLifecycle(to) {
		return true
	}
	return taskStatusRank(to) >= taskStatusRank(from)
}

func canHydrateTaskResult(from db.Runtimetaskstatus, to db.Runtimetaskstatus) (allowed bool, conflict bool) {
	if to == "" {
		return false, false
	}
	if from == "" {
		return true, false
	}
	if !isTerminalTaskLifecycle(to) {
		return false, false
	}
	if !isTerminalTaskLifecycle(from) {
		return true, false
	}
	if from == to {
		return true, false
	}
	return false, true
}
