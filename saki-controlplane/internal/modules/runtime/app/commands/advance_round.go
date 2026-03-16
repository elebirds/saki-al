package commands

import (
	"context"
	"encoding/json"
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
	outbox OutboxWriter
}

func NewAdvanceRoundHandler(rounds RoundStore, outbox OutboxWriter) *AdvanceRoundHandler {
	return &AdvanceRoundHandler{
		rounds: rounds,
		outbox: outbox,
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

	payload, err := json.Marshal(struct {
		RoundID string `json:"round_id"`
		Status  string `json:"status"`
	}{
		RoundID: round.ID,
		Status:  update.Status,
	})
	if err != nil {
		return nil, err
	}

	if err := h.outbox.Append(ctx, OutboxEvent{
		Topic:       "runtime.round.advanced",
		AggregateID: round.ID,
		Payload:     payload,
	}); err != nil {
		return nil, err
	}

	advanced := *round
	advanced.Status = update.Status
	return &advanced, nil
}
