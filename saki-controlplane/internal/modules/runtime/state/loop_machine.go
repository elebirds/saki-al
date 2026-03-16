package state

type LoopStatus string

const (
	LoopStatusDraft     LoopStatus = "draft"
	LoopStatusActive    LoopStatus = "active"
	LoopStatusPaused    LoopStatus = "paused"
	LoopStatusCompleted LoopStatus = "completed"
)

type LoopSnapshot struct {
	Status LoopStatus
}

type LoopCommand interface{ isLoopCommand() }

type StartLoop struct{}
type PauseLoop struct{}
type CompleteLoop struct{}

func (StartLoop) isLoopCommand()    {}
func (PauseLoop) isLoopCommand()    {}
func (CompleteLoop) isLoopCommand() {}

type LoopEvent interface{ isLoopEvent() }

type LoopStarted struct{}
type LoopPaused struct{}
type LoopCompleted struct{}

func (LoopStarted) isLoopEvent()   {}
func (LoopPaused) isLoopEvent()    {}
func (LoopCompleted) isLoopEvent() {}

func DecideLoop(snapshot LoopSnapshot, cmd LoopCommand) ([]LoopEvent, error) {
	switch cmd.(type) {
	case StartLoop:
		if snapshot.Status != LoopStatusDraft && snapshot.Status != LoopStatusPaused {
			return nil, ErrInvalidTransition
		}
		return []LoopEvent{LoopStarted{}}, nil
	case PauseLoop:
		if snapshot.Status != LoopStatusActive {
			return nil, ErrInvalidTransition
		}
		return []LoopEvent{LoopPaused{}}, nil
	case CompleteLoop:
		if snapshot.Status != LoopStatusActive {
			return nil, ErrInvalidTransition
		}
		return []LoopEvent{LoopCompleted{}}, nil
	default:
		return nil, ErrInvalidTransition
	}
}

func EvolveLoop(snapshot LoopSnapshot, evt LoopEvent) LoopSnapshot {
	switch evt.(type) {
	case LoopStarted:
		snapshot.Status = LoopStatusActive
	case LoopPaused:
		snapshot.Status = LoopStatusPaused
	case LoopCompleted:
		snapshot.Status = LoopStatusCompleted
	}

	return snapshot
}
