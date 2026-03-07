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
		return to == db.LooplifecyclePAUSED || to == db.LooplifecycleSTOPPING || to == db.LooplifecycleCOMPLETED || to == db.LooplifecycleFAILED
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
