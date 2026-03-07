package controlplane

import (
	"context"
	"strings"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	db "github.com/elebirds/saki/saki-dispatcher/internal/gen/sqlc"
)

func (s *Service) withCommand(
	ctx context.Context,
	commandID string,
	action func(tx pgx.Tx, normalizedCommandID string) (status string, detail string, err error),
) (CommandResult, error) {
	commandID = strings.TrimSpace(commandID)
	if commandID == "" {
		commandID = uuid.NewString()
	}
	if !s.dbEnabled() {
		return CommandResult{
			CommandID: commandID,
			Status:    "failed",
			Message:   "数据库未配置",
			RequestID: uuid.NewString(),
		}, nil
	}

	tx, err := s.beginTx(ctx)
	if err != nil {
		return CommandResult{}, err
	}
	defer tx.Rollback(ctx)

	entry, found, err := s.getCommandLogTx(ctx, tx, commandID)
	if err != nil {
		return CommandResult{}, err
	}
	if found {
		return CommandResult{
			CommandID: commandID,
			Status:    entry.Status,
			Message:   entry.Detail,
			RequestID: entry.ID.String(),
		}, nil
	}

	requestID := uuid.New()
	inserted, err := s.insertCommandLogTx(ctx, tx, requestID, commandID)
	if err != nil {
		return CommandResult{}, err
	}
	if !inserted {
		entry, found, err := s.getCommandLogTx(ctx, tx, commandID)
		if err != nil {
			return CommandResult{}, err
		}
		if found {
			return CommandResult{
				CommandID: commandID,
				Status:    entry.Status,
				Message:   entry.Detail,
				RequestID: entry.ID.String(),
			}, nil
		}
	}

	status, detail, err := action(tx, commandID)
	if err != nil {
		s.persistCommandFailure(ctx, commandID, err)
		return CommandResult{}, err
	}
	if status == "" {
		status = "applied"
	}
	if detail == "" {
		detail = status
	}

	if err := s.qtx(tx).UpdateCommandLogStatusDetail(ctx, db.UpdateCommandLogStatusDetailParams{
		CommandID: commandID,
		Status:    status,
		Detail:    detail,
	}); err != nil {
		return CommandResult{}, err
	}

	if err := tx.Commit(ctx); err != nil {
		return CommandResult{}, err
	}
	return CommandResult{
		CommandID: commandID,
		Status:    status,
		Message:   detail,
		RequestID: requestID.String(),
	}, nil
}

func (s *Service) persistCommandFailure(
	ctx context.Context,
	commandID string,
	actionErr error,
) {
	if !s.dbEnabled() {
		return
	}
	tx, err := s.beginTx(ctx)
	if err != nil {
		return
	}
	defer tx.Rollback(ctx)

	requestID := uuid.New()
	if _, err := s.insertCommandLogTx(ctx, tx, requestID, commandID); err != nil {
		return
	}
	detail := strings.TrimSpace(actionErr.Error())
	if detail == "" {
		detail = "命令执行失败"
	}
	if err := s.qtx(tx).UpdateCommandLogStatusDetail(ctx, db.UpdateCommandLogStatusDetailParams{
		CommandID: commandID,
		Status:    "failed",
		Detail:    detail,
	}); err != nil {
		return
	}
	_ = tx.Commit(ctx)
}

func (s *Service) getCommandLogTx(ctx context.Context, tx pgx.Tx, commandID string) (commandLogEntry, bool, error) {
	record, err := s.qtx(tx).GetCommandLogByCommandID(ctx, commandID)
	if err != nil {
		if err == pgx.ErrNoRows {
			return commandLogEntry{}, false, nil
		}
		return commandLogEntry{}, false, err
	}
	row := commandLogEntry{
		ID:     record.ID,
		Status: record.Status,
		Detail: record.Detail,
	}
	return row, true, nil
}

func (s *Service) insertCommandLogTx(
	ctx context.Context,
	tx pgx.Tx,
	requestID uuid.UUID,
	commandID string,
) (bool, error) {
	affected, err := s.qtx(tx).InsertCommandLog(ctx, db.InsertCommandLogParams{
		RequestID: requestID,
		CommandID: commandID,
	})
	if err != nil {
		return false, err
	}
	return affected > 0, nil
}
