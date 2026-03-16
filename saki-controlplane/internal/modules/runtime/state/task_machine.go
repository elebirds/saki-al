package state

import "errors"

var ErrInvalidTransition = errors.New("invalid transition")

type TaskStatus string

const (
	TaskStatusPending   TaskStatus = "pending"
	TaskStatusRunning   TaskStatus = "running"
	TaskStatusSucceeded TaskStatus = "succeeded"
	TaskStatusFailed    TaskStatus = "failed"
	TaskStatusCanceled  TaskStatus = "canceled"
)

type TaskSnapshot struct {
	Status TaskStatus
}

type TaskCommand interface{ isTaskCommand() }

type StartTask struct{}
type FinishTask struct{}
type FailTask struct{}
type CancelTask struct{}

func (StartTask) isTaskCommand()  {}
func (FinishTask) isTaskCommand() {}
func (FailTask) isTaskCommand()   {}
func (CancelTask) isTaskCommand() {}

type TaskEvent interface{ isTaskEvent() }

type TaskStarted struct{}
type TaskFinished struct{}
type TaskFailed struct{}
type TaskCanceled struct{}

func (TaskStarted) isTaskEvent()  {}
func (TaskFinished) isTaskEvent() {}
func (TaskFailed) isTaskEvent()   {}
func (TaskCanceled) isTaskEvent() {}

func DecideTask(snapshot TaskSnapshot, cmd TaskCommand) ([]TaskEvent, error) {
	switch cmd.(type) {
	case StartTask:
		if snapshot.Status != TaskStatusPending {
			return nil, ErrInvalidTransition
		}
		return []TaskEvent{TaskStarted{}}, nil
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
	case CancelTask:
		if snapshot.Status != TaskStatusPending && snapshot.Status != TaskStatusRunning {
			return nil, ErrInvalidTransition
		}
		return []TaskEvent{TaskCanceled{}}, nil
	default:
		return nil, ErrInvalidTransition
	}
}

func EvolveTask(snapshot TaskSnapshot, evt TaskEvent) TaskSnapshot {
	switch evt.(type) {
	case TaskStarted:
		snapshot.Status = TaskStatusRunning
	case TaskFinished:
		snapshot.Status = TaskStatusSucceeded
	case TaskFailed:
		snapshot.Status = TaskStatusFailed
	case TaskCanceled:
		snapshot.Status = TaskStatusCanceled
	}

	return snapshot
}
