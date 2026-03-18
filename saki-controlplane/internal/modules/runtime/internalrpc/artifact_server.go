package internalrpc

import (
	"context"
	"errors"

	"connectrpc.com/connect"
	"github.com/google/uuid"

	runtimev1 "github.com/elebirds/saki/saki-controlplane/internal/gen/proto/runtime/v1"
	"github.com/elebirds/saki/saki-controlplane/internal/gen/proto/runtime/v1/runtimev1connect"
	assetapp "github.com/elebirds/saki/saki-controlplane/internal/modules/asset/app"
)

type issueUploadTicketUseCase interface {
	Execute(ctx context.Context, assetID uuid.UUID) (*assetapp.Ticket, error)
}

type issueDownloadTicketUseCase interface {
	Execute(ctx context.Context, assetID uuid.UUID) (*assetapp.Ticket, error)
}

type ArtifactServer struct {
	runtimev1connect.UnimplementedArtifactServiceHandler

	uploads   issueUploadTicketUseCase
	downloads issueDownloadTicketUseCase
}

func NewArtifactServer(
	uploads issueUploadTicketUseCase,
	downloads issueDownloadTicketUseCase,
) *ArtifactServer {
	return &ArtifactServer{
		uploads:   uploads,
		downloads: downloads,
	}
}

func (s *ArtifactServer) CreateUploadTicket(
	ctx context.Context,
	req *connect.Request[runtimev1.CreateUploadTicketRequest],
) (*connect.Response[runtimev1.CreateUploadTicketResponse], error) {
	artifactID, err := parseArtifactID(req.Msg.GetArtifactId())
	if err != nil {
		return nil, err
	}

	ticket, err := s.uploads.Execute(ctx, artifactID)
	if err != nil {
		return nil, mapArtifactTicketError(err)
	}

	return connect.NewResponse(&runtimev1.CreateUploadTicketResponse{Url: ticket.URL}), nil
}

func (s *ArtifactServer) CreateDownloadTicket(
	ctx context.Context,
	req *connect.Request[runtimev1.CreateDownloadTicketRequest],
) (*connect.Response[runtimev1.CreateDownloadTicketResponse], error) {
	artifactID, err := parseArtifactID(req.Msg.GetArtifactId())
	if err != nil {
		return nil, err
	}

	ticket, err := s.downloads.Execute(ctx, artifactID)
	if err != nil {
		return nil, mapArtifactTicketError(err)
	}

	return connect.NewResponse(&runtimev1.CreateDownloadTicketResponse{Url: ticket.URL}), nil
}

func parseArtifactID(raw string) (uuid.UUID, error) {
	artifactID, err := uuid.Parse(raw)
	if err != nil {
		return uuid.Nil, connect.NewError(connect.CodeInvalidArgument, errors.New("invalid artifact_id"))
	}
	return artifactID, nil
}

func mapArtifactTicketError(err error) error {
	switch {
	case errors.Is(err, context.Canceled):
		return connect.NewError(connect.CodeCanceled, err)
	case errors.Is(err, context.DeadlineExceeded):
		return connect.NewError(connect.CodeDeadlineExceeded, err)
	case errors.Is(err, assetapp.ErrAssetNotFound):
		return connect.NewError(connect.CodeNotFound, err)
	case errors.Is(err, assetapp.ErrAssetNotPendingUpload),
		errors.Is(err, assetapp.ErrAssetNotReady),
		errors.Is(err, assetapp.ErrAssetBucketMismatch):
		return connect.NewError(connect.CodeFailedPrecondition, err)
	default:
		return connect.NewError(connect.CodeInternal, err)
	}
}
