package repo

import (
	"context"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"

	sqlcdb "github.com/elebirds/saki/saki-controlplane/internal/gen/sqlc"
)

type Project struct {
	ID   uuid.UUID
	Name string
}

type CreateProjectParams struct {
	Name string
}

type ProjectRepo struct {
	q *sqlcdb.Queries
}

func NewProjectRepo(pool *pgxpool.Pool) *ProjectRepo {
	return &ProjectRepo{q: sqlcdb.New(pool)}
}

func (r *ProjectRepo) CreateProject(ctx context.Context, params CreateProjectParams) (*Project, error) {
	row, err := r.q.CreateProject(ctx, params.Name)
	if err != nil {
		return nil, err
	}

	return &Project{
		ID:   row.ID,
		Name: row.Name,
	}, nil
}
