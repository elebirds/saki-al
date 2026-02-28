package controlplane

import db "github.com/elebirds/saki/saki-dispatcher/internal/gen/sqlc"

func isTerminalStepStatusDB(state db.Stepstatus) bool {
	switch state {
	case db.StepstatusSUCCEEDED, db.StepstatusFAILED, db.StepstatusCANCELLED, db.StepstatusSKIPPED:
		return true
	default:
		return false
	}
}

func canStepTransition(from db.Stepstatus, to db.Stepstatus) bool {
	if from == to {
		return true
	}
	switch from {
	case db.StepstatusPENDING:
		return to == db.StepstatusREADY || to == db.StepstatusCANCELLED
	case db.StepstatusREADY:
		return to == db.StepstatusDISPATCHING || to == db.StepstatusRUNNING || to == db.StepstatusCANCELLED
	case db.StepstatusDISPATCHING:
		return to == db.StepstatusRUNNING || to == db.StepstatusREADY || to == db.StepstatusRETRYING || isTerminalStepStatusDB(to)
	case db.StepstatusRUNNING:
		return to == db.StepstatusRETRYING || to == db.StepstatusREADY || isTerminalStepStatusDB(to)
	case db.StepstatusRETRYING:
		return to == db.StepstatusRUNNING || to == db.StepstatusREADY || isTerminalStepStatusDB(to)
	case db.StepstatusFAILED:
		return to == db.StepstatusREADY
	default:
		return false
	}
}

func stepFromCandidatesForTarget(target db.Stepstatus) []db.Stepstatus {
	switch target {
	case db.StepstatusRUNNING:
		return []db.Stepstatus{db.StepstatusDISPATCHING, db.StepstatusREADY, db.StepstatusRETRYING}
	case db.StepstatusSUCCEEDED, db.StepstatusFAILED, db.StepstatusCANCELLED, db.StepstatusSKIPPED:
		return []db.Stepstatus{db.StepstatusRUNNING, db.StepstatusRETRYING, db.StepstatusDISPATCHING, db.StepstatusREADY}
	case db.StepstatusRETRYING:
		return []db.Stepstatus{db.StepstatusRUNNING, db.StepstatusDISPATCHING}
	case db.StepstatusREADY:
		return []db.Stepstatus{db.StepstatusPENDING, db.StepstatusFAILED, db.StepstatusRETRYING, db.StepstatusDISPATCHING}
	case db.StepstatusDISPATCHING:
		return []db.Stepstatus{db.StepstatusREADY}
	default:
		return []db.Stepstatus{}
	}
}

func shouldApplyRuntimeStatus(target db.Stepstatus) bool {
	switch target {
	case "", db.StepstatusPENDING:
		return false
	default:
		return true
	}
}

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
	case db.LooplifecycleSTOPPING:
		return to == db.LooplifecycleSTOPPED || to == db.LooplifecycleFAILED
	case db.LooplifecycleSTOPPED:
		return false
	default:
		return false
	}
}
