package repo

import (
	"context"
	"errors"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	sqlcdb "github.com/elebirds/saki/saki-controlplane/internal/gen/sqlc"
)

type Project struct {
	ID        uuid.UUID
	Name      string
	CreatedAt time.Time
	UpdatedAt time.Time
}

type CreateProjectParams struct {
	Name string
}

type ProjectDatasetLink struct {
	ProjectID uuid.UUID
	DatasetID uuid.UUID
	CreatedAt time.Time
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
		ID:        row.ID,
		Name:      row.Name,
		CreatedAt: row.CreatedAt.Time,
		UpdatedAt: row.UpdatedAt.Time,
	}, nil
}

func (r *ProjectRepo) ListProjects(ctx context.Context) ([]Project, error) {
	rows, err := r.q.ListProjects(ctx)
	if err != nil {
		return nil, err
	}

	projects := make([]Project, 0, len(rows))
	for _, row := range rows {
		projects = append(projects, Project{
			ID:        row.ID,
			Name:      row.Name,
			CreatedAt: row.CreatedAt.Time,
			UpdatedAt: row.UpdatedAt.Time,
		})
	}

	return projects, nil
}

func (r *ProjectRepo) GetProject(ctx context.Context, id uuid.UUID) (*Project, error) {
	row, err := r.q.GetProject(ctx, id)
	if err != nil {
		return nil, err
	}

	return &Project{
		ID:        row.ID,
		Name:      row.Name,
		CreatedAt: row.CreatedAt.Time,
		UpdatedAt: row.UpdatedAt.Time,
	}, nil
}

func (r *ProjectRepo) LinkDataset(ctx context.Context, projectID, datasetID uuid.UUID) (*ProjectDatasetLink, error) {
	row, err := r.q.LinkProjectDataset(ctx, sqlcdb.LinkProjectDatasetParams{
		ProjectID: projectID,
		DatasetID: datasetID,
	})
	if err != nil {
		return nil, err
	}

	return &ProjectDatasetLink{
		ProjectID: row.ProjectID,
		DatasetID: row.DatasetID,
		CreatedAt: row.CreatedAt.Time,
	}, nil
}

func (r *ProjectRepo) ListProjectDatasetIDs(ctx context.Context, projectID uuid.UUID) ([]uuid.UUID, error) {
	return r.q.ListProjectDatasetIDs(ctx, projectID)
}

func (r *ProjectRepo) UnlinkDataset(ctx context.Context, projectID, datasetID uuid.UUID) (bool, error) {
	link, err := r.GetProjectDatasetLink(ctx, projectID, datasetID)
	if err != nil {
		return false, err
	}
	if link == nil {
		return false, nil
	}

	err = r.q.UnlinkProjectDataset(ctx, sqlcdb.UnlinkProjectDatasetParams{
		ProjectID: projectID,
		DatasetID: datasetID,
	})
	if err != nil {
		return false, err
	}
	return true, nil
}

func (r *ProjectRepo) GetProjectDatasetLink(ctx context.Context, projectID, datasetID uuid.UUID) (*ProjectDatasetLink, error) {
	row, err := r.q.GetProjectDatasetLink(ctx, sqlcdb.GetProjectDatasetLinkParams{
		ProjectID: projectID,
		DatasetID: datasetID,
	})
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return nil, nil
		}
		return nil, err
	}

	return &ProjectDatasetLink{
		ProjectID: row.ProjectID,
		DatasetID: row.DatasetID,
		CreatedAt: row.CreatedAt.Time,
	}, nil
}
