package repo

import "github.com/jackc/pgx/v5/pgxpool"

type RoundRepo struct{}

func NewRoundRepo(_ *pgxpool.Pool) *RoundRepo {
	return &RoundRepo{}
}
