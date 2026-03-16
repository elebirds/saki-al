package repo

import "github.com/jackc/pgx/v5/pgxpool"

type LoopRepo struct{}

func NewLoopRepo(_ *pgxpool.Pool) *LoopRepo {
	return &LoopRepo{}
}
