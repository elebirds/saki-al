package controlplane

import db "github.com/elebirds/saki/saki-dispatcher/internal/gen/sqlc"

const (
	lifecycleDraft     db.Looplifecycle = db.LooplifecycleDRAFT
	lifecycleRunning   db.Looplifecycle = db.LooplifecycleRUNNING
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
	phaseSimWaitUser      db.Loopphase = db.LoopphaseSIMWAITUSER
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

	terminalReasonSuccess     = "SUCCESS"
	terminalReasonSystemError = "SYSTEM_ERROR"
	terminalReasonUserStop    = "USER_STOP"
)

var terminalRoundStatuses = map[db.Roundstatus]struct{}{
	roundCompleted: {},
	roundFailed:    {},
	roundCancelled: {},
}
