package runtime

import (
	"context"
	"errors"
	"net/http"
	"time"

	"golang.org/x/sync/errgroup"
)

type Process struct {
	server     *http.Server
	background []loopRunner
}

func newProcess(server *http.Server, background ...loopRunner) *Process {
	loops := make([]loopRunner, 0, len(background))
	for _, runner := range background {
		if runner == nil {
			continue
		}
		loops = append(loops, runner)
	}

	return &Process{
		server:     server,
		background: loops,
	}
}

func (p *Process) Server() *http.Server {
	if p == nil {
		return nil
	}
	return p.server
}

func (p *Process) Run(ctx context.Context) error {
	if p == nil {
		return nil
	}

	group, runCtx := errgroup.WithContext(ctx)
	for _, runner := range p.background {
		runner := runner
		group.Go(func() error {
			return runner.Run(runCtx)
		})
	}

	if p.server != nil {
		group.Go(func() error {
			err := p.server.ListenAndServe()
			if errors.Is(err, http.ErrServerClosed) {
				return nil
			}
			return err
		})
		group.Go(func() error {
			<-runCtx.Done()
			shutdownCtx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
			defer cancel()
			err := p.server.Shutdown(shutdownCtx)
			if errors.Is(err, http.ErrServerClosed) {
				return nil
			}
			return err
		})
	}

	if p.server == nil && len(p.background) == 0 {
		<-runCtx.Done()
		return nil
	}

	return group.Wait()
}
