package reporting

import (
	"context"
	"sync"

	workerv1 "github.com/elebirds/saki/saki-agent/internal/gen/worker/v1"
)

type EventSink interface {
	ReportWorkerEvent(ctx context.Context, event *workerv1.WorkerEvent) error
}

type MemorySink struct {
	mu     sync.Mutex
	Events []*workerv1.WorkerEvent
}

func (s *MemorySink) ReportWorkerEvent(_ context.Context, event *workerv1.WorkerEvent) error {
	s.mu.Lock()
	defer s.mu.Unlock()

	s.Events = append(s.Events, event)
	return nil
}
