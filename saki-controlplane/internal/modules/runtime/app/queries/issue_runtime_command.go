package queries

import (
	"context"

	"github.com/google/uuid"

	"github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/app/commands"
)

type RuntimeTaskCanceler interface {
	Handle(ctx context.Context, cmd commands.CancelTaskCommand) (*commands.TaskRecord, error)
}

type IssueRuntimeCommandUseCase struct {
	canceler RuntimeTaskCanceler
}

func NewIssueRuntimeCommandUseCase(canceler RuntimeTaskCanceler) *IssueRuntimeCommandUseCase {
	return &IssueRuntimeCommandUseCase{canceler: canceler}
}

func (u *IssueRuntimeCommandUseCase) CancelTask(ctx context.Context, taskID string) error {
	id, err := uuid.Parse(taskID)
	if err != nil {
		return err
	}

	_, err = u.canceler.Handle(ctx, commands.CancelTaskCommand{TaskID: id})
	return err
}
