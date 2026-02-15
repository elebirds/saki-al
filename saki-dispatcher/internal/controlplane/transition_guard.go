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

func canLoopTransition(from db.Loopstatus, to db.Loopstatus) bool {
	if from == to {
		return true
	}
	switch from {
	case db.LoopstatusDRAFT:
		return to == db.LoopstatusRUNNING
	case db.LoopstatusRUNNING:
		return to == db.LoopstatusPAUSED || to == db.LoopstatusSTOPPING || to == db.LoopstatusCOMPLETED || to == db.LoopstatusFAILED
	case db.LoopstatusPAUSED:
		return to == db.LoopstatusRUNNING || to == db.LoopstatusSTOPPING
	case db.LoopstatusSTOPPING:
		return to == db.LoopstatusSTOPPED || to == db.LoopstatusFAILED
	case db.LoopstatusSTOPPED:
		return to == db.LoopstatusRUNNING
	default:
		return false
	}
}
