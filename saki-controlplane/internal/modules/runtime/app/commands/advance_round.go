package commands

import (
	"context"
)

type RoundRecord struct {
	ID     string
	Status string
}

type RoundUpdate struct {
	ID     string
	Status string
}

type RoundStore interface {
	GetRound(ctx context.Context, roundID string) (*RoundRecord, error)
	UpdateRound(ctx context.Context, update RoundUpdate) error
}

type AdvanceRoundCommand struct {
	RoundID string
}

type AdvanceRoundHandler struct {
	rounds RoundStore
}

func NewAdvanceRoundHandler(rounds RoundStore) *AdvanceRoundHandler {
	return &AdvanceRoundHandler{
		rounds: rounds,
	}
}

func (h *AdvanceRoundHandler) Handle(ctx context.Context, cmd AdvanceRoundCommand) (*RoundRecord, error) {
	round, err := h.rounds.GetRound(ctx, cmd.RoundID)
	if err != nil || round == nil {
		return round, err
	}

	update := RoundUpdate{
		ID:     round.ID,
		Status: "completed",
	}
	if err := h.rounds.UpdateRound(ctx, update); err != nil {
		return nil, err
	}

	advanced := *round
	advanced.Status = update.Status
	return &advanced, nil
}
