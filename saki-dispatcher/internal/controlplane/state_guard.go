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
		// 关键语义：
		// READY 阶段尚未真正下发到 executor，但已经完成依赖检查。
		// 若在 dispatcher 侧预派发（如模型交接票据创建）失败，步骤应可直接失败，
		// 否则会出现“预派发失败后状态更新冲突”，并长期卡在 READY。
		return to == db.StepstatusDISPATCHING ||
			to == db.StepstatusSYNCINGENV ||
			to == db.StepstatusPROBINGRUNTIME ||
			to == db.StepstatusBINDINGDEVICE ||
			to == db.StepstatusRUNNING ||
			to == db.StepstatusFAILED ||
			to == db.StepstatusCANCELLED
	case db.StepstatusDISPATCHING:
		return to == db.StepstatusSYNCINGENV ||
			to == db.StepstatusPROBINGRUNTIME ||
			to == db.StepstatusBINDINGDEVICE ||
			to == db.StepstatusRUNNING ||
			to == db.StepstatusREADY ||
			to == db.StepstatusRETRYING ||
			isTerminalStepStatusDB(to)
	case db.StepstatusSYNCINGENV:
		return to == db.StepstatusPROBINGRUNTIME ||
			to == db.StepstatusBINDINGDEVICE ||
			to == db.StepstatusRUNNING ||
			to == db.StepstatusREADY ||
			to == db.StepstatusRETRYING ||
			isTerminalStepStatusDB(to)
	case db.StepstatusPROBINGRUNTIME:
		return to == db.StepstatusBINDINGDEVICE ||
			to == db.StepstatusRUNNING ||
			to == db.StepstatusREADY ||
			to == db.StepstatusRETRYING ||
			isTerminalStepStatusDB(to)
	case db.StepstatusBINDINGDEVICE:
		return to == db.StepstatusRUNNING ||
			to == db.StepstatusREADY ||
			to == db.StepstatusRETRYING ||
			isTerminalStepStatusDB(to)
	case db.StepstatusRUNNING:
		return to == db.StepstatusRETRYING || to == db.StepstatusREADY || isTerminalStepStatusDB(to)
	case db.StepstatusRETRYING:
		return to == db.StepstatusSYNCINGENV ||
			to == db.StepstatusPROBINGRUNTIME ||
			to == db.StepstatusBINDINGDEVICE ||
			to == db.StepstatusRUNNING ||
			to == db.StepstatusREADY ||
			isTerminalStepStatusDB(to)
	case db.StepstatusFAILED:
		return to == db.StepstatusREADY
	default:
		return false
	}
}

func stepFromCandidatesForTarget(target db.Stepstatus) []db.Stepstatus {
	switch target {
	case db.StepstatusSYNCINGENV:
		return []db.Stepstatus{db.StepstatusDISPATCHING, db.StepstatusREADY}
	case db.StepstatusPROBINGRUNTIME:
		return []db.Stepstatus{db.StepstatusSYNCINGENV, db.StepstatusDISPATCHING, db.StepstatusREADY}
	case db.StepstatusBINDINGDEVICE:
		return []db.Stepstatus{db.StepstatusPROBINGRUNTIME, db.StepstatusSYNCINGENV, db.StepstatusDISPATCHING, db.StepstatusREADY}
	case db.StepstatusRUNNING:
		return []db.Stepstatus{
			db.StepstatusBINDINGDEVICE,
			db.StepstatusPROBINGRUNTIME,
			db.StepstatusSYNCINGENV,
			db.StepstatusDISPATCHING,
			db.StepstatusREADY,
			db.StepstatusRETRYING,
		}
	case db.StepstatusSUCCEEDED, db.StepstatusFAILED, db.StepstatusCANCELLED, db.StepstatusSKIPPED:
		return []db.Stepstatus{
			db.StepstatusRUNNING,
			db.StepstatusBINDINGDEVICE,
			db.StepstatusPROBINGRUNTIME,
			db.StepstatusSYNCINGENV,
			db.StepstatusRETRYING,
			db.StepstatusDISPATCHING,
			db.StepstatusREADY,
		}
	case db.StepstatusRETRYING:
		return []db.Stepstatus{
			db.StepstatusRUNNING,
			db.StepstatusBINDINGDEVICE,
			db.StepstatusPROBINGRUNTIME,
			db.StepstatusSYNCINGENV,
			db.StepstatusDISPATCHING,
		}
	case db.StepstatusREADY:
		return []db.Stepstatus{
			db.StepstatusPENDING,
			db.StepstatusFAILED,
			db.StepstatusRETRYING,
			db.StepstatusBINDINGDEVICE,
			db.StepstatusPROBINGRUNTIME,
			db.StepstatusSYNCINGENV,
			db.StepstatusDISPATCHING,
		}
	case db.StepstatusDISPATCHING:
		return []db.Stepstatus{db.StepstatusREADY}
	default:
		return []db.Stepstatus{}
	}
}

func stepFromCandidatesForResultTarget(target db.Stepstatus) []db.Stepstatus {
	base := stepFromCandidatesForTarget(target)
	seen := make(map[db.Stepstatus]struct{}, len(base)+1)
	result := make([]db.Stepstatus, 0, len(base)+1)
	for _, item := range base {
		if item == "" {
			continue
		}
		if _, ok := seen[item]; ok {
			continue
		}
		seen[item] = struct{}{}
		result = append(result, item)
	}
	if target != "" {
		if _, ok := seen[target]; !ok {
			result = append(result, target)
		}
	}
	return result
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
