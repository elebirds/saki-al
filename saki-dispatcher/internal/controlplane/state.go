package controlplane

import db "github.com/elebirds/saki/saki-dispatcher/internal/gen/sqlc"

const (
	statusDraft     db.Loopstatus = db.LoopstatusDRAFT
	statusRunning   db.Loopstatus = db.LoopstatusRUNNING
	statusPaused    db.Loopstatus = db.LoopstatusPAUSED
	statusStopping  db.Loopstatus = db.LoopstatusSTOPPING
	statusStopped   db.Loopstatus = db.LoopstatusSTOPPED
	statusCompleted db.Loopstatus = db.LoopstatusCOMPLETED
	statusFailed    db.Loopstatus = db.LoopstatusFAILED

	phaseALTrain          db.Loopphase = db.LoopphaseALTRAIN
	phaseALScore          db.Loopphase = db.LoopphaseALSCORE
	phaseALSelect         db.Loopphase = db.LoopphaseALSELECT
	phaseALWaitAnnotation db.Loopphase = db.LoopphaseALWAITUSER
	phaseALEval           db.Loopphase = db.LoopphaseALEVAL
	phaseALFinalize       db.Loopphase = db.LoopphaseALFINALIZE
	phaseSimTrain         db.Loopphase = db.LoopphaseSIMTRAIN
	phaseSimScore         db.Loopphase = db.LoopphaseSIMSCORE
	phaseSimSelect        db.Loopphase = db.LoopphaseSIMSELECT
	phaseSimActivate      db.Loopphase = db.LoopphaseSIMACTIVATE
	phaseSimEval          db.Loopphase = db.LoopphaseSIMEVAL
	phaseSimFinalize      db.Loopphase = db.LoopphaseSIMFINALIZE
	phaseManualTrain      db.Loopphase = db.LoopphaseMANUALTRAIN
	phaseManualEval       db.Loopphase = db.LoopphaseMANUALEVAL
	phaseManualExport     db.Loopphase = db.LoopphaseMANUALEXPORT
	phaseManualFinalize   db.Loopphase = db.LoopphaseMANUALFINALIZE

	modeAL     db.Loopmode = db.LoopmodeACTIVELEARNING
	modeSIM    db.Loopmode = db.LoopmodeSIMULATION
	modeManual db.Loopmode = db.LoopmodeMANUAL

	roundPending   db.Roundstatus = db.RoundstatusPENDING
	roundRunning   db.Roundstatus = db.RoundstatusRUNNING
	roundWaitUser  db.Roundstatus = db.RoundstatusWAITUSER
	roundCompleted db.Roundstatus = db.RoundstatusCOMPLETED
	roundFailed    db.Roundstatus = db.RoundstatusFAILED
	roundCancelled db.Roundstatus = db.RoundstatusCANCELLED

	stepPending     db.Stepstatus = db.StepstatusPENDING
	stepReady       db.Stepstatus = db.StepstatusREADY
	stepDispatching db.Stepstatus = db.StepstatusDISPATCHING
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
