package launcher

import (
	"bytes"
	"context"
	"errors"
	"io"
	"os/exec"
	"time"

	"github.com/elebirds/saki/saki-agent/internal/app/reporting"
	workerv1 "github.com/elebirds/saki/saki-agent/internal/gen/worker/v1"
	"google.golang.org/protobuf/proto"
)

type LauncherConfig struct {
	Command []string
	Env     []string
	Timeout time.Duration
}

type Launcher struct {
	cfg LauncherConfig
}

func NewLauncher(cfg LauncherConfig) *Launcher {
	return &Launcher{cfg: cfg}
}

func (l *Launcher) Execute(
	ctx context.Context,
	req *workerv1.ExecuteRequest,
	sink reporting.EventSink,
) (*workerv1.ExecuteResult, error) {
	if len(l.cfg.Command) == 0 {
		return nil, errors.New("launcher command is required")
	}

	if l.cfg.Timeout > 0 {
		var cancel context.CancelFunc
		ctx, cancel = context.WithTimeout(ctx, l.cfg.Timeout)
		defer cancel()
	}

	cmd := exec.CommandContext(ctx, l.cfg.Command[0], l.cfg.Command[1:]...)
	if len(l.cfg.Env) > 0 {
		cmd.Env = l.cfg.Env
	}

	stdin, err := cmd.StdinPipe()
	if err != nil {
		return nil, err
	}
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		return nil, err
	}
	var stderr bytes.Buffer
	cmd.Stderr = &stderr

	if err := cmd.Start(); err != nil {
		return nil, err
	}

	if err := WriteExecuteRequest(stdin, req); err != nil {
		_ = stdin.Close()
		_ = cmd.Wait()
		return nil, err
	}
	_ = stdin.Close()

	var result *workerv1.ExecuteResult
	for {
		kind, payload, err := ReadEnvelope(stdout)
		if err != nil {
			if errors.Is(err, io.EOF) || errors.Is(err, io.ErrUnexpectedEOF) {
				break
			}
			_ = cmd.Wait()
			return nil, err
		}

		switch kind {
		case frameKindWorkerEvent:
			var event workerv1.WorkerEvent
			if err := proto.Unmarshal(payload, &event); err != nil {
				_ = cmd.Wait()
				return nil, err
			}
			if sink != nil {
				if err := sink.ReportWorkerEvent(ctx, &event); err != nil {
					_ = cmd.Wait()
					return nil, err
				}
			}
		case frameKindExecuteResult:
			var decoded workerv1.ExecuteResult
			if err := proto.Unmarshal(payload, &decoded); err != nil {
				_ = cmd.Wait()
				return nil, err
			}
			result = &decoded
		default:
			_ = cmd.Wait()
			return nil, errors.New("unknown frame kind")
		}

		if result != nil {
			break
		}
	}

	if err := cmd.Wait(); err != nil {
		if stderr.Len() > 0 {
			return nil, errors.New(stderr.String())
		}
		return nil, err
	}
	if result == nil {
		if stderr.Len() > 0 {
			return nil, errors.New(stderr.String())
		}
		return nil, errors.New("worker exited without result")
	}

	return result, nil
}
