package state

import "errors"

var ErrInvalidTransition = errors.New("invalid transition")

type TaskStatus string

const (
	TaskStatusPending         TaskStatus = "pending"
	TaskStatusAssigned        TaskStatus = "assigned"
	TaskStatusRunning         TaskStatus = "running"
	TaskStatusCancelRequested TaskStatus = "cancel_requested"
	TaskStatusSucceeded       TaskStatus = "succeeded"
	TaskStatusFailed          TaskStatus = "failed"
	TaskStatusCanceled        TaskStatus = "canceled"
)

type TaskSnapshot struct {
	Status TaskStatus
}

type TaskCommand interface{ isTaskCommand() }

type AssignTask struct{}
type StartTaskExecution struct{}
type RequestTaskCancel struct{}
type FinishTask struct{}
type FailTask struct{}
type ConfirmTaskCanceled struct{}

func (AssignTask) isTaskCommand()          {}
func (StartTaskExecution) isTaskCommand()  {}
func (RequestTaskCancel) isTaskCommand()   {}
func (FinishTask) isTaskCommand()          {}
func (FailTask) isTaskCommand()            {}
func (ConfirmTaskCanceled) isTaskCommand() {}

type TaskEvent interface{ isTaskEvent() }

type TaskAssigned struct{}
type TaskExecutionStarted struct{}
type TaskCancelRequested struct{}
type TaskFinished struct{}
type TaskFailed struct{}
type TaskCanceled struct{}

func (TaskAssigned) isTaskEvent()         {}
func (TaskExecutionStarted) isTaskEvent() {}
func (TaskCancelRequested) isTaskEvent()  {}
func (TaskFinished) isTaskEvent()         {}
func (TaskFailed) isTaskEvent()           {}
func (TaskCanceled) isTaskEvent()         {}

func DecideTask(snapshot TaskSnapshot, cmd TaskCommand) ([]TaskEvent, error) {
	switch cmd.(type) {
	case AssignTask:
		if snapshot.Status != TaskStatusPending {
			return nil, ErrInvalidTransition
		}
		return []TaskEvent{TaskAssigned{}}, nil
	case StartTaskExecution:
		if snapshot.Status != TaskStatusAssigned {
			return nil, ErrInvalidTransition
		}
		return []TaskEvent{TaskExecutionStarted{}}, nil
	case RequestTaskCancel:
		switch snapshot.Status {
		case TaskStatusPending:
			return []TaskEvent{TaskCanceled{}}, nil
		case TaskStatusRunning:
			return []TaskEvent{TaskCancelRequested{}}, nil
		default:
			return nil, ErrInvalidTransition
		}
	case FinishTask:
		if snapshot.Status != TaskStatusRunning {
			return nil, ErrInvalidTransition
		}
		return []TaskEvent{TaskFinished{}}, nil
	case FailTask:
		if snapshot.Status != TaskStatusRunning {
			return nil, ErrInvalidTransition
		}
		return []TaskEvent{TaskFailed{}}, nil
	case ConfirmTaskCanceled:
		if snapshot.Status != TaskStatusCancelRequested {
			return nil, ErrInvalidTransition
		}
		return []TaskEvent{TaskCanceled{}}, nil
	default:
		return nil, ErrInvalidTransition
	}
}

func EvolveTask(snapshot TaskSnapshot, evt TaskEvent) TaskSnapshot {
	switch evt.(type) {
	case TaskAssigned:
		snapshot.Status = TaskStatusAssigned
	case TaskExecutionStarted:
		snapshot.Status = TaskStatusRunning
	case TaskCancelRequested:
		snapshot.Status = TaskStatusCancelRequested
	case TaskFinished:
		snapshot.Status = TaskStatusSucceeded
	case TaskFailed:
		snapshot.Status = TaskStatusFailed
	case TaskCanceled:
		snapshot.Status = TaskStatusCanceled
	}

	return snapshot
}
