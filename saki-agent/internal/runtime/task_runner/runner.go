package task_runner

import (
	"context"

	"github.com/elebirds/saki/saki-agent/internal/app/reporting"
	workerv1 "github.com/elebirds/saki/saki-agent/internal/gen/worker/v1"
)

type WorkerLauncher interface {
	Execute(ctx context.Context, req *workerv1.ExecuteRequest, sink reporting.EventSink) (*workerv1.ExecuteResult, error)
}

type Runner struct {
	launcher WorkerLauncher
	sink     reporting.EventSink
}

func NewRunner(launcher WorkerLauncher, sink reporting.EventSink) *Runner {
	return &Runner{
		launcher: launcher,
		sink:     sink,
	}
}

func (r *Runner) Run(ctx context.Context, req *workerv1.ExecuteRequest) (*workerv1.ExecuteResult, error) {
	return r.launcher.Execute(ctx, req, r.sink)
}
