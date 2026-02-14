package runtime_domain_client

import (
	"context"
	"fmt"
	"strings"
	"time"

	runtimedomainv1 "github.com/elebirds/saki/saki-dispatcher/internal/gen/runtimedomainv1"
	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/metadata"
	"google.golang.org/grpc/status"
)

type Client struct {
	target     string
	token      string
	timeout    time.Duration
	conn       *grpc.ClientConn
	grpcClient runtimedomainv1.RuntimeDomainClient
}

func New(target, token string, timeoutSec int) *Client {
	if timeoutSec <= 0 {
		timeoutSec = 5
	}
	return &Client{
		target:  strings.TrimSpace(target),
		token:   strings.TrimSpace(token),
		timeout: time.Duration(timeoutSec) * time.Second,
	}
}

func (c *Client) Enabled() bool {
	return c != nil && c.target != ""
}

func (c *Client) Connect(ctx context.Context) error {
	if !c.Enabled() {
		return nil
	}
	if c.conn != nil {
		return nil
	}
	conn, err := grpc.NewClient(c.target, grpc.WithTransportCredentials(insecure.NewCredentials()))
	if err != nil {
		return fmt.Errorf("connect runtime_domain: %w", err)
	}
	c.conn = conn
	c.grpcClient = runtimedomainv1.NewRuntimeDomainClient(conn)
	return nil
}

func (c *Client) Close() error {
	if c == nil || c.conn == nil {
		return nil
	}
	return c.conn.Close()
}

func (c *Client) GetBranchHead(ctx context.Context, branchID string) (*runtimedomainv1.GetBranchHeadResponse, error) {
	if !c.Enabled() || c.grpcClient == nil {
		return nil, fmt.Errorf("runtime_domain client is not connected")
	}
	callCtx, cancel := context.WithTimeout(withToken(ctx, c.token), c.timeout)
	defer cancel()
	return c.grpcClient.GetBranchHead(callCtx, &runtimedomainv1.GetBranchHeadRequest{BranchId: branchID})
}

func (c *Client) CountNewLabelsSinceCommit(
	ctx context.Context,
	projectID string,
	branchID string,
	sinceCommitID string,
) (*runtimedomainv1.CountNewLabelsSinceCommitResponse, error) {
	if !c.Enabled() || c.grpcClient == nil {
		return nil, fmt.Errorf("runtime_domain client is not connected")
	}
	callCtx, cancel := context.WithTimeout(withToken(ctx, c.token), c.timeout)
	defer cancel()
	return c.grpcClient.CountNewLabelsSinceCommit(callCtx, &runtimedomainv1.CountNewLabelsSinceCommitRequest{
		ProjectId:     projectID,
		BranchId:      branchID,
		SinceCommitId: sinceCommitID,
	})
}

func (c *Client) CreateSimulationCommitFromOracle(
	ctx context.Context,
	req *runtimedomainv1.CreateSimulationCommitFromOracleRequest,
) (*runtimedomainv1.CreateSimulationCommitFromOracleResponse, error) {
	if !c.Enabled() || c.grpcClient == nil {
		return nil, fmt.Errorf("runtime_domain client is not connected")
	}
	callCtx, cancel := context.WithTimeout(withToken(ctx, c.token), c.timeout)
	defer cancel()
	return c.grpcClient.CreateSimulationCommitFromOracle(callCtx, req)
}

func (c *Client) ActivateSamples(
	ctx context.Context,
	req *runtimedomainv1.ActivateSamplesRequest,
) (*runtimedomainv1.ActivateSamplesResponse, error) {
	if !c.Enabled() || c.grpcClient == nil {
		return nil, fmt.Errorf("runtime_domain client is not connected")
	}
	callCtx, cancel := context.WithTimeout(withToken(ctx, c.token), c.timeout)
	defer cancel()

	resp, err := c.grpcClient.ActivateSamples(callCtx, req)
	if err == nil {
		return resp, nil
	}
	st, ok := status.FromError(err)
	if !ok || (st.Code() != codes.Unimplemented && st.Code() != codes.Unknown) {
		return nil, err
	}

	legacyResp, legacyErr := c.grpcClient.CreateSimulationCommitFromOracle(callCtx, &runtimedomainv1.CreateSimulationCommitFromOracleRequest{
		CommandId:      req.GetCommandId(),
		ProjectId:      req.GetProjectId(),
		BranchId:       req.GetBranchId(),
		OracleCommitId: req.GetOracleCommitId(),
		SourceCommitId: req.GetSourceCommitId(),
		LoopId:         req.GetLoopId(),
		RoundIndex:     req.GetRoundIndex(),
		QueryStrategy:  req.GetQueryStrategy(),
		Topk:           req.GetTopk(),
	})
	if legacyErr != nil {
		return nil, legacyErr
	}
	return &runtimedomainv1.ActivateSamplesResponse{
		Created:  legacyResp.GetCreated(),
		CommitId: legacyResp.GetCommitId(),
	}, nil
}

func (c *Client) AdvanceBranchHead(
	ctx context.Context,
	commandID string,
	branchID string,
	toCommitID string,
	reason string,
) (*runtimedomainv1.AdvanceBranchHeadResponse, error) {
	if !c.Enabled() || c.grpcClient == nil {
		return nil, fmt.Errorf("runtime_domain client is not connected")
	}
	callCtx, cancel := context.WithTimeout(withToken(ctx, c.token), c.timeout)
	defer cancel()
	return c.grpcClient.AdvanceBranchHead(callCtx, &runtimedomainv1.AdvanceBranchHeadRequest{
		CommandId:  commandID,
		BranchId:   branchID,
		ToCommitId: toCommitID,
		Reason:     reason,
	})
}

func (c *Client) QueryData(
	ctx context.Context,
	req *runtimedomainv1.DataRequest,
) (*runtimedomainv1.DataResponse, error) {
	if !c.Enabled() || c.grpcClient == nil {
		return nil, fmt.Errorf("runtime_domain client is not connected")
	}
	callCtx, cancel := context.WithTimeout(withToken(ctx, c.token), c.timeout)
	defer cancel()
	return c.grpcClient.QueryData(callCtx, req)
}

func (c *Client) CreateUploadTicket(
	ctx context.Context,
	req *runtimedomainv1.UploadTicketRequest,
) (*runtimedomainv1.UploadTicketResponse, error) {
	if !c.Enabled() || c.grpcClient == nil {
		return nil, fmt.Errorf("runtime_domain client is not connected")
	}
	callCtx, cancel := context.WithTimeout(withToken(ctx, c.token), c.timeout)
	defer cancel()
	return c.grpcClient.CreateUploadTicket(callCtx, req)
}

func withToken(ctx context.Context, token string) context.Context {
	if strings.TrimSpace(token) == "" {
		return ctx
	}
	return metadata.AppendToOutgoingContext(ctx, "x-internal-token", token)
}
