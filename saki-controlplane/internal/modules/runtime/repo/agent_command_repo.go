package repo

import (
	"context"
	"errors"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgtype"
	"github.com/jackc/pgx/v5/pgxpool"

	sqlcdb "github.com/elebirds/saki/saki-controlplane/internal/gen/sqlc"
)

var ErrAgentCommandClaimExpired = errors.New("agent command claim expired")

type AgentCommand struct {
	CommandID     uuid.UUID
	AgentID       string
	TaskID        uuid.UUID
	AssignmentID  int64
	CommandType   string
	TransportMode string
	Status        string
	Payload       []byte
	AvailableAt   time.Time
	ExpireAt      time.Time
	AttemptCount  int32
	ClaimToken    *uuid.UUID
	ClaimUntil    *time.Time
	AckedAt       *time.Time
	FinishedAt    *time.Time
	LastError     *string
	CreatedAt     time.Time
	UpdatedAt     time.Time
}

type AppendAssignCommandParams struct {
	CommandID     uuid.UUID
	AgentID       string
	TaskID        uuid.UUID
	AssignmentID  int64
	TransportMode string
	Payload       []byte
	AvailableAt   time.Time
	ExpireAt      time.Time
}

type AppendCancelCommandParams = AppendAssignCommandParams

// AgentCommandRepo 把命令生命周期落在 DB，delivery 只是在不同 transport 上搬运这些命令。
type AgentCommandRepo struct {
	q *sqlcdb.Queries
}

func NewAgentCommandRepo(pool *pgxpool.Pool) *AgentCommandRepo {
	return newAgentCommandRepo(sqlcdb.New(pool))
}

func newAgentCommandRepo(q *sqlcdb.Queries) *AgentCommandRepo {
	return &AgentCommandRepo{q: q}
}

func (r *AgentCommandRepo) AppendAssign(ctx context.Context, params AppendAssignCommandParams) (*AgentCommand, error) {
	return r.append(ctx, sqlcdb.AgentCommandTypeAssign, params)
}

func (r *AgentCommandRepo) AppendCancel(ctx context.Context, params AppendCancelCommandParams) (*AgentCommand, error) {
	return r.append(ctx, sqlcdb.AgentCommandTypeCancel, params)
}

func (r *AgentCommandRepo) append(ctx context.Context, commandType sqlcdb.AgentCommandType, params AppendAssignCommandParams) (*AgentCommand, error) {
	row, err := r.q.AppendAgentCommand(ctx, sqlcdb.AppendAgentCommandParams{
		CommandID:     params.CommandID,
		AgentID:       params.AgentID,
		TaskID:        params.TaskID,
		AssignmentID:  params.AssignmentID,
		CommandType:   commandType,
		TransportMode: sqlcdb.AgentTransportMode(params.TransportMode),
		Payload:       params.Payload,
		AvailableAt:   pgtype.Timestamptz{Time: params.AvailableAt, Valid: true},
		ExpireAt:      pgtype.Timestamptz{Time: params.ExpireAt, Valid: true},
	})
	if err != nil {
		return nil, err
	}
	return agentCommandFromModel(row), nil
}

func (r *AgentCommandRepo) ClaimForPush(ctx context.Context, limit int32, claimUntil time.Time) ([]AgentCommand, error) {
	rows, err := r.q.ClaimPushAgentCommands(ctx, sqlcdb.ClaimPushAgentCommandsParams{
		LimitCount: limit,
		ClaimUntil: pgtype.Timestamptz{Time: claimUntil, Valid: true},
	})
	if err != nil {
		return nil, err
	}
	return agentCommandsFromModels(rows), nil
}

func (r *AgentCommandRepo) ClaimForPull(ctx context.Context, agentID string, limit int32, claimUntil time.Time) ([]AgentCommand, error) {
	rows, err := r.q.ClaimPullAgentCommands(ctx, sqlcdb.ClaimPullAgentCommandsParams{
		ClaimUntil:    pgtype.Timestamptz{Time: claimUntil, Valid: true},
		TargetAgentID: agentID,
		LimitCount:    limit,
	})
	if err != nil {
		return nil, err
	}
	return agentCommandsFromModels(rows), nil
}

func (r *AgentCommandRepo) Ack(ctx context.Context, commandID, claimToken uuid.UUID, ackAt time.Time) error {
	rows, err := r.q.AckAgentCommand(ctx, sqlcdb.AckAgentCommandParams{
		CommandID: commandID,
		ClaimToken: pgtype.UUID{
			Bytes: claimToken,
			Valid: true,
		},
		AckedAt: pgtype.Timestamptz{Time: ackAt, Valid: true},
	})
	if err != nil {
		return err
	}
	if rows == 0 {
		return ErrAgentCommandClaimExpired
	}
	return nil
}

func (r *AgentCommandRepo) MarkFinished(ctx context.Context, commandID, claimToken uuid.UUID, finishedAt time.Time) error {
	rows, err := r.q.FinishAgentCommand(ctx, sqlcdb.FinishAgentCommandParams{
		CommandID: commandID,
		ClaimToken: pgtype.UUID{
			Bytes: claimToken,
			Valid: true,
		},
		FinishedAt: pgtype.Timestamptz{Time: finishedAt, Valid: true},
	})
	if err != nil {
		return err
	}
	if rows == 0 {
		return ErrAgentCommandClaimExpired
	}
	return nil
}

func (r *AgentCommandRepo) MarkRetry(ctx context.Context, commandID, claimToken uuid.UUID, nextAvailableAt time.Time, lastError string) error {
	rows, err := r.q.RetryAgentCommand(ctx, sqlcdb.RetryAgentCommandParams{
		CommandID: commandID,
		ClaimToken: pgtype.UUID{
			Bytes: claimToken,
			Valid: true,
		},
		NextAvailableAt: pgtype.Timestamptz{Time: nextAvailableAt, Valid: true},
		LastError:       pgtype.Text{String: lastError, Valid: lastError != ""},
	})
	if err != nil {
		return err
	}
	if rows == 0 {
		return ErrAgentCommandClaimExpired
	}
	return nil
}

func (r *AgentCommandRepo) ExpireDue(ctx context.Context, cutoff time.Time) (int64, error) {
	return r.q.ExpireDueAgentCommands(ctx, pgtype.Timestamptz{Time: cutoff, Valid: true})
}

func (r *AgentCommandRepo) GetByCommandID(ctx context.Context, commandID uuid.UUID) (*AgentCommand, error) {
	row, err := r.q.GetAgentCommandByID(ctx, commandID)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return nil, nil
		}
		return nil, err
	}
	return agentCommandFromModel(row), nil
}

func agentCommandsFromModels(rows []sqlcdb.AgentCommand) []AgentCommand {
	items := make([]AgentCommand, 0, len(rows))
	for _, row := range rows {
		items = append(items, *agentCommandFromModel(row))
	}
	return items
}

func agentCommandFromModel(row sqlcdb.AgentCommand) *AgentCommand {
	return &AgentCommand{
		CommandID:     row.CommandID,
		AgentID:       row.AgentID,
		TaskID:        row.TaskID,
		AssignmentID:  row.AssignmentID,
		CommandType:   string(row.CommandType),
		TransportMode: string(row.TransportMode),
		Status:        string(row.Status),
		Payload:       append([]byte(nil), row.Payload...),
		AvailableAt:   row.AvailableAt.Time,
		ExpireAt:      row.ExpireAt.Time,
		AttemptCount:  row.AttemptCount,
		ClaimToken:    optionalUUID(row.ClaimToken),
		ClaimUntil:    optionalTime(row.ClaimUntil),
		AckedAt:       optionalTime(row.AckedAt),
		FinishedAt:    optionalTime(row.FinishedAt),
		LastError:     optionalLastError(row.LastError),
		CreatedAt:     row.CreatedAt.Time,
		UpdatedAt:     row.UpdatedAt.Time,
	}
}

func optionalUUID(value pgtype.UUID) *uuid.UUID {
	if !value.Valid {
		return nil
	}
	id := uuid.UUID(value.Bytes)
	return &id
}

func optionalTime(value pgtype.Timestamptz) *time.Time {
	if !value.Valid {
		return nil
	}
	ts := value.Time
	return &ts
}

func optionalLastError(value pgtype.Text) *string {
	if !value.Valid {
		return nil
	}
	text := value.String
	return &text
}
