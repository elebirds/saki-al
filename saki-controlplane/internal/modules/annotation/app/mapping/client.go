package mapping

import (
	"context"
	"errors"
	"time"

	workerv1 "github.com/elebirds/saki/saki-controlplane/internal/gen/proto/worker/v1"
)

type ClientConfig struct {
	Command []string
	Env     []string
	Timeout time.Duration
}

type Client struct {
	cfg ClientConfig
}

func NewClient(cfg ClientConfig) *Client {
	return &Client{cfg: cfg}
}

func (c *Client) MapFedoOBB(ctx context.Context, req MapFedoOBBRequest) (mapResponse, error) {
	if len(c.cfg.Command) == 0 {
		return mapResponse{}, errors.New("mapping sidecar command is required")
	}
	if req.SourceView == "" || req.TargetView == "" {
		return mapResponse{}, errors.New("mapping source_view and target_view are required")
	}
	if len(req.LookupTable) == 0 {
		return mapResponse{}, errors.New("mapping lookup table is required")
	}

	if c.cfg.Timeout > 0 {
		var cancel context.CancelFunc
		ctx, cancel = context.WithTimeout(ctx, c.cfg.Timeout)
		defer cancel()
	}

	handle, err := startProcess(ctx, c.cfg.Command, c.cfg.Env)
	if err != nil {
		return mapResponse{}, err
	}

	payload, err := encodeMapRequest(req)
	if err != nil {
		return mapResponse{}, err
	}

	if err := writeExecuteRequest(handle.stdin, &workerv1.ExecuteRequest{
		RequestId: "mapping-request",
		TaskId:    "mapping-task",
		Action:    "map_fedo_obb",
		Payload:   payload,
	}); err != nil {
		_ = handle.stdin.Close()
		_ = handle.cmd.Wait()
		return mapResponse{}, err
	}
	_ = handle.stdin.Close()

	result, err := readExecuteResult(handle.stdout)
	if err != nil {
		_ = handle.cmd.Wait()
		return mapResponse{}, err
	}
	if err := handle.cmd.Wait(); err != nil {
		return mapResponse{}, err
	}
	if !result.GetOk() {
		return mapResponse{}, errors.New(result.GetErrorMessage())
	}

	return decodeMapResponse(result.GetPayload())
}
