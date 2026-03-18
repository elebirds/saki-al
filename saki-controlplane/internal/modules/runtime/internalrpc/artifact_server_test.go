package internalrpc

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"testing"

	"connectrpc.com/connect"
	"github.com/google/uuid"

	runtimev1 "github.com/elebirds/saki/saki-controlplane/internal/gen/proto/runtime/v1"
	"github.com/elebirds/saki/saki-controlplane/internal/gen/proto/runtime/v1/runtimev1connect"
	assetapp "github.com/elebirds/saki/saki-controlplane/internal/modules/asset/app"
)

func TestArtifactServerCreateUploadTicketForPendingAsset(t *testing.T) {
	assetID := uuid.New()
	uploads := &fakeIssueUploadTicketHandler{
		result: &assetapp.Ticket{
			AssetID: assetID,
			URL:     "https://upload.example.test",
		},
	}
	server := NewArtifactServer(uploads, &fakeIssueDownloadTicketHandler{})

	mux := http.NewServeMux()
	path, handler := runtimev1connect.NewArtifactServiceHandler(server)
	mux.Handle(path, handler)
	httpServer := httptest.NewServer(mux)
	defer httpServer.Close()

	client := runtimev1connect.NewArtifactServiceClient(http.DefaultClient, httpServer.URL)
	resp, err := client.CreateUploadTicket(context.Background(), connect.NewRequest(&runtimev1.CreateUploadTicketRequest{
		ArtifactId: assetID.String(),
	}))
	if err != nil {
		t.Fatalf("create upload ticket: %v", err)
	}
	if uploads.lastAssetID != assetID {
		t.Fatalf("unexpected upload ticket asset id: got=%s want=%s", uploads.lastAssetID, assetID)
	}
	if got, want := resp.Msg.GetUrl(), "https://upload.example.test"; got != want {
		t.Fatalf("unexpected upload ticket url: got=%q want=%q", got, want)
	}
}

func TestArtifactServerRejectsUploadTicketForReadyAsset(t *testing.T) {
	server := NewArtifactServer(
		&fakeIssueUploadTicketHandler{err: assetapp.ErrAssetNotPendingUpload},
		&fakeIssueDownloadTicketHandler{},
	)

	mux := http.NewServeMux()
	path, handler := runtimev1connect.NewArtifactServiceHandler(server)
	mux.Handle(path, handler)
	httpServer := httptest.NewServer(mux)
	defer httpServer.Close()

	client := runtimev1connect.NewArtifactServiceClient(http.DefaultClient, httpServer.URL)
	_, err := client.CreateUploadTicket(context.Background(), connect.NewRequest(&runtimev1.CreateUploadTicketRequest{
		ArtifactId: uuid.NewString(),
	}))
	if err == nil {
		t.Fatal("expected upload ticket request to fail for ready asset")
	}

	connectErr := new(connect.Error)
	if !errors.As(err, &connectErr) {
		t.Fatalf("expected connect error, got %T", err)
	}
	if got, want := connectErr.Code(), connect.CodeFailedPrecondition; got != want {
		t.Fatalf("unexpected connect code: got=%s want=%s", got, want)
	}
}

func TestArtifactServerCreateDownloadTicketForReadyAsset(t *testing.T) {
	assetID := uuid.New()
	downloads := &fakeIssueDownloadTicketHandler{
		result: &assetapp.Ticket{
			AssetID: assetID,
			URL:     "https://download.example.test",
		},
	}
	server := NewArtifactServer(&fakeIssueUploadTicketHandler{}, downloads)

	mux := http.NewServeMux()
	path, handler := runtimev1connect.NewArtifactServiceHandler(server)
	mux.Handle(path, handler)
	httpServer := httptest.NewServer(mux)
	defer httpServer.Close()

	client := runtimev1connect.NewArtifactServiceClient(http.DefaultClient, httpServer.URL)
	resp, err := client.CreateDownloadTicket(context.Background(), connect.NewRequest(&runtimev1.CreateDownloadTicketRequest{
		ArtifactId: assetID.String(),
	}))
	if err != nil {
		t.Fatalf("create download ticket: %v", err)
	}
	if downloads.lastAssetID != assetID {
		t.Fatalf("unexpected download ticket asset id: got=%s want=%s", downloads.lastAssetID, assetID)
	}
	if got, want := resp.Msg.GetUrl(), "https://download.example.test"; got != want {
		t.Fatalf("unexpected download ticket url: got=%q want=%q", got, want)
	}
}

func TestArtifactServerMapsCanceledError(t *testing.T) {
	server := NewArtifactServer(
		&fakeIssueUploadTicketHandler{err: context.Canceled},
		&fakeIssueDownloadTicketHandler{},
	)

	mux := http.NewServeMux()
	path, handler := runtimev1connect.NewArtifactServiceHandler(server)
	mux.Handle(path, handler)
	httpServer := httptest.NewServer(mux)
	defer httpServer.Close()

	client := runtimev1connect.NewArtifactServiceClient(http.DefaultClient, httpServer.URL)
	_, err := client.CreateUploadTicket(context.Background(), connect.NewRequest(&runtimev1.CreateUploadTicketRequest{
		ArtifactId: uuid.NewString(),
	}))
	if err == nil {
		t.Fatal("expected create upload ticket to fail")
	}

	connectErr := new(connect.Error)
	if !errors.As(err, &connectErr) {
		t.Fatalf("expected connect error, got %T", err)
	}
	if got, want := connectErr.Code(), connect.CodeCanceled; got != want {
		t.Fatalf("unexpected connect code: got=%s want=%s", got, want)
	}
}

func TestArtifactServerMapsDeadlineExceededError(t *testing.T) {
	server := NewArtifactServer(
		&fakeIssueUploadTicketHandler{},
		&fakeIssueDownloadTicketHandler{err: context.DeadlineExceeded},
	)

	mux := http.NewServeMux()
	path, handler := runtimev1connect.NewArtifactServiceHandler(server)
	mux.Handle(path, handler)
	httpServer := httptest.NewServer(mux)
	defer httpServer.Close()

	client := runtimev1connect.NewArtifactServiceClient(http.DefaultClient, httpServer.URL)
	_, err := client.CreateDownloadTicket(context.Background(), connect.NewRequest(&runtimev1.CreateDownloadTicketRequest{
		ArtifactId: uuid.NewString(),
	}))
	if err == nil {
		t.Fatal("expected create download ticket to fail")
	}

	connectErr := new(connect.Error)
	if !errors.As(err, &connectErr) {
		t.Fatalf("expected connect error, got %T", err)
	}
	if got, want := connectErr.Code(), connect.CodeDeadlineExceeded; got != want {
		t.Fatalf("unexpected connect code: got=%s want=%s", got, want)
	}
}

type fakeIssueUploadTicketHandler struct {
	lastAssetID uuid.UUID
	result      *assetapp.Ticket
	err         error
}

func (f *fakeIssueUploadTicketHandler) Execute(_ context.Context, assetID uuid.UUID) (*assetapp.Ticket, error) {
	f.lastAssetID = assetID
	return f.result, f.err
}

type fakeIssueDownloadTicketHandler struct {
	lastAssetID uuid.UUID
	result      *assetapp.Ticket
	err         error
}

func (f *fakeIssueDownloadTicketHandler) Execute(_ context.Context, assetID uuid.UUID) (*assetapp.Ticket, error) {
	f.lastAssetID = assetID
	return f.result, f.err
}
