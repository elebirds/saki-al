package state

type RoundStatus string

const (
	RoundStatusPending   RoundStatus = "pending"
	RoundStatusActive    RoundStatus = "active"
	RoundStatusCompleted RoundStatus = "completed"
	RoundStatusFailed    RoundStatus = "failed"
)

type RoundSnapshot struct {
	Status RoundStatus
}

type RoundCommand interface{ isRoundCommand() }

type StartRound struct{}
type CompleteRound struct{}
type FailRound struct{}

func (StartRound) isRoundCommand()    {}
func (CompleteRound) isRoundCommand() {}
func (FailRound) isRoundCommand()     {}

type RoundEvent interface{ isRoundEvent() }

type RoundStarted struct{}
type RoundCompleted struct{}
type RoundFailed struct{}

func (RoundStarted) isRoundEvent()   {}
func (RoundCompleted) isRoundEvent() {}
func (RoundFailed) isRoundEvent()    {}

func DecideRound(snapshot RoundSnapshot, cmd RoundCommand) ([]RoundEvent, error) {
	switch cmd.(type) {
	case StartRound:
		if snapshot.Status != RoundStatusPending {
			return nil, ErrInvalidTransition
		}
		return []RoundEvent{RoundStarted{}}, nil
	case CompleteRound:
		if snapshot.Status != RoundStatusActive {
			return nil, ErrInvalidTransition
		}
		return []RoundEvent{RoundCompleted{}}, nil
	case FailRound:
		if snapshot.Status != RoundStatusActive {
			return nil, ErrInvalidTransition
		}
		return []RoundEvent{RoundFailed{}}, nil
	default:
		return nil, ErrInvalidTransition
	}
}

func EvolveRound(snapshot RoundSnapshot, evt RoundEvent) RoundSnapshot {
	switch evt.(type) {
	case RoundStarted:
		snapshot.Status = RoundStatusActive
	case RoundCompleted:
		snapshot.Status = RoundStatusCompleted
	case RoundFailed:
		snapshot.Status = RoundStatusFailed
	}

	return snapshot
}
