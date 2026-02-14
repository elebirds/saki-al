package repo

import (
	"context"
	"fmt"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

type RuntimeRepo struct {
	pool *pgxpool.Pool
}

func NewRuntimeRepo(ctx context.Context, databaseURL string) (*RuntimeRepo, error) {
	if strings.TrimSpace(databaseURL) == "" {
		return nil, nil
	}
	cfg, err := pgxpool.ParseConfig(databaseURL)
	if err != nil {
		return nil, fmt.Errorf("parse database url: %w", err)
	}
	cfg.MaxConns = 20
	cfg.MinConns = 2
	cfg.HealthCheckPeriod = 30 * time.Second

	pool, err := pgxpool.NewWithConfig(ctx, cfg)
	if err != nil {
		return nil, fmt.Errorf("create pool: %w", err)
	}
	if err := pool.Ping(ctx); err != nil {
		pool.Close()
		return nil, fmt.Errorf("ping database: %w", err)
	}
	return &RuntimeRepo{pool: pool}, nil
}

func (r *RuntimeRepo) Close() {
	if r == nil || r.pool == nil {
		return
	}
	r.pool.Close()
}

func (r *RuntimeRepo) Enabled() bool {
	return r != nil && r.pool != nil
}

func (r *RuntimeRepo) Pool() *pgxpool.Pool {
	if r == nil {
		return nil
	}
	return r.pool
}

func (r *RuntimeRepo) Begin(ctx context.Context) (pgx.Tx, error) {
	if !r.Enabled() {
		return nil, fmt.Errorf("runtime repo is not enabled")
	}
	return r.pool.Begin(ctx)
}
