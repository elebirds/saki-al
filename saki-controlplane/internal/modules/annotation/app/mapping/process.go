package mapping

import (
	"bytes"
	"context"
	"io"
	"os/exec"
)

type processHandle struct {
	cmd    *exec.Cmd
	stdin  io.WriteCloser
	stdout io.ReadCloser
	stderr *bytes.Buffer
}

func startProcess(ctx context.Context, command []string, env []string) (*processHandle, error) {
	cmd := exec.CommandContext(ctx, command[0], command[1:]...)
	if len(env) > 0 {
		cmd.Env = env
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

	return &processHandle{
		cmd:    cmd,
		stdin:  stdin,
		stdout: stdout,
		stderr: &stderr,
	}, nil
}
