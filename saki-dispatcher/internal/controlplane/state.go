package controlplane

import db "github.com/elebirds/saki/saki-dispatcher/internal/gen/sqlc"

const (
	lifecycleDraft     db.Looplifecycle = db.LooplifecycleDRAFT
	lifecycleRunning   db.Looplifecycle = db.LooplifecycleRUNNING
	lifecyclePausing   db.Looplifecycle = db.LooplifecyclePAUSING
	lifecyclePaused    db.Looplifecycle = db.LooplifecyclePAUSED
	lifecycleStopping  db.Looplifecycle = db.LooplifecycleSTOPPING
	lifecycleStopped   db.Looplifecycle = db.LooplifecycleSTOPPED
	lifecycleCompleted db.Looplifecycle = db.LooplifecycleCOMPLETED
	lifecycleFailed    db.Looplifecycle = db.LooplifecycleFAILED

	phaseALTrain          db.Loopphase = db.LoopphaseALTRAIN
	phaseALEval           db.Loopphase = db.LoopphaseALEVAL
	phaseALScore          db.Loopphase = db.LoopphaseALSCORE
	phaseALSelect         db.Loopphase = db.LoopphaseALSELECT
	phaseALWaitAnnotation db.Loopphase = db.LoopphaseALWAITUSER
	phaseALFinalize       db.Loopphase = db.LoopphaseALFINALIZE
	phaseSimTrain         db.Loopphase = db.LoopphaseSIMTRAIN
	phaseSimEval          db.Loopphase = db.LoopphaseSIMEVAL
	phaseSimScore         db.Loopphase = db.LoopphaseSIMSCORE
	phaseSimSelect        db.Loopphase = db.LoopphaseSIMSELECT
	phaseSimFinalize      db.Loopphase = db.LoopphaseSIMFINALIZE
	phaseManualTrain      db.Loopphase = db.LoopphaseMANUALTRAIN
	phaseManualEval       db.Loopphase = db.LoopphaseMANUALEVAL
	phaseManualFinalize   db.Loopphase = db.LoopphaseMANUALFINALIZE

	modeAL     db.Loopmode = db.LoopmodeACTIVELEARNING
	modeSIM    db.Loopmode = db.LoopmodeSIMULATION
	modeManual db.Loopmode = db.LoopmodeMANUAL

	roundPending   db.Roundstatus = db.RoundstatusPENDING
	roundRunning   db.Roundstatus = db.RoundstatusRUNNING
	roundCompleted db.Roundstatus = db.RoundstatusCOMPLETED
	roundFailed    db.Roundstatus = db.RoundstatusFAILED
	roundCancelled db.Roundstatus = db.RoundstatusCANCELLED

	taskPending     db.Runtimetaskstatus = db.RuntimetaskstatusPENDING
	taskReady       db.Runtimetaskstatus = db.RuntimetaskstatusREADY
	taskDispatching db.Runtimetaskstatus = db.RuntimetaskstatusDISPATCHING
	taskSyncingEnv  db.Runtimetaskstatus = db.RuntimetaskstatusSYNCINGENV
	taskProbingRt   db.Runtimetaskstatus = db.RuntimetaskstatusPROBINGRUNTIME
	taskBindingDev  db.Runtimetaskstatus = db.RuntimetaskstatusBINDINGDEVICE
	taskRunning     db.Runtimetaskstatus = db.RuntimetaskstatusRUNNING
	taskRetrying    db.Runtimetaskstatus = db.RuntimetaskstatusRETRYING
	taskSucceeded   db.Runtimetaskstatus = db.RuntimetaskstatusSUCCEEDED
	taskFailed      db.Runtimetaskstatus = db.RuntimetaskstatusFAILED
	taskCancelled   db.Runtimetaskstatus = db.RuntimetaskstatusCANCELLED
	taskSkipped     db.Runtimetaskstatus = db.RuntimetaskstatusSKIPPED

	stepPending     db.Stepstatus = db.StepstatusPENDING
	stepReady       db.Stepstatus = db.StepstatusREADY
	stepDispatching db.Stepstatus = db.StepstatusDISPATCHING
	stepSyncingEnv  db.Stepstatus = db.StepstatusSYNCINGENV
	stepProbingRt   db.Stepstatus = db.StepstatusPROBINGRUNTIME
	stepBindingDev  db.Stepstatus = db.StepstatusBINDINGDEVICE
	stepRunning     db.Stepstatus = db.StepstatusRUNNING
	stepRetrying    db.Stepstatus = db.StepstatusRETRYING
	stepSucceeded   db.Stepstatus = db.StepstatusSUCCEEDED
	stepFailed      db.Stepstatus = db.StepstatusFAILED
	stepCancelled   db.Stepstatus = db.StepstatusCANCELLED
	stepSkipped     db.Stepstatus = db.StepstatusSKIPPED

	terminalReasonSuccess                   = "SUCCESS"
	terminalReasonSystemError               = "SYSTEM_ERROR"
	terminalReasonTaskResultNotMaterialized = "TASK_RESULT_NOT_MATERIALIZED"
	terminalReasonUserStop                  = "USER_STOP"

	pauseReasonUser        db.Looppausereason = db.LooppausereasonUSER
	pauseReasonMaintenance db.Looppausereason = db.LooppausereasonMAINTENANCE

	maintenanceModeNormal   = "normal"
	maintenanceModeDrain    = "drain"
	maintenanceModePauseNow = "pause_now"
)

var terminalRoundStatuses = map[db.Roundstatus]struct{}{
	roundCompleted: {},
	roundFailed:    {},
	roundCancelled: {},
}
