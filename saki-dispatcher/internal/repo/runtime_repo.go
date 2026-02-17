package repo

import (
	"context"
	"fmt"
	"strings"
	"time"

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
		return nil, fmt.Errorf("解析数据库地址失败: %w", err)
	}
	cfg.MaxConns = 20
	cfg.MinConns = 2
	cfg.HealthCheckPeriod = 30 * time.Second

	pool, err := pgxpool.NewWithConfig(ctx, cfg)
	if err != nil {
		return nil, fmt.Errorf("创建数据库连接池失败: %w", err)
	}
	if err := pool.Ping(ctx); err != nil {
		pool.Close()
		return nil, fmt.Errorf("数据库连通性检查失败: %w", err)
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
