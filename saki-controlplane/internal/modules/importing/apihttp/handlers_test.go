package apihttp

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	authctx "github.com/elebirds/saki/saki-controlplane/internal/app/auth"
	"github.com/elebirds/saki/saki-controlplane/internal/app/storage"
	openapi "github.com/elebirds/saki/saki-controlplane/internal/gen/openapi"
	accessapp "github.com/elebirds/saki/saki-controlplane/internal/modules/access/app"
	importapp "github.com/elebirds/saki/saki-controlplane/internal/modules/importing/app"
	importrepo "github.com/elebirds/saki/saki-controlplane/internal/modules/importing/repo"
	"github.com/google/uuid"
)

func TestInitImportUploadSessionReturnsSinglePutResponse(t *testing.T) {
	userID := uuid.New()
	uploadStore := &fakeUploadStore{
		initSession: &importrepo.UploadSession{
			ID:          uuid.New(),
			UserID:      userID,
			Mode:        "project_annotations",
			FileName:    "annotations.zip",
			ObjectKey:   "/tmp/imports/annotations.zip",
			ContentType: "application/zip",
			Status:      "initiated",
		},
	}
	provider := &fakeObjectProvider{
		putURL: "http://object.test/imports/signed-upload",
	}
	handler := NewHandlers(Dependencies{
		Uploads:  uploadStore,
		Tasks:    &fakeTaskStore{},
		Prepare:  fakePrepareUseCase{},
		Execute:  fakeExecuteUseCase{},
		Provider: provider,
	})

	resp, err := handler.InitImportUploadSession(
		contextWithUser(userID),
		&openapi.ImportUploadInitRequest{
			Mode:         "project_annotations",
			ResourceType: "project",
			ResourceID:   uuid.NewString(),
			Filename:     "annotations.zip",
			Size:         128,
			ContentType:  "application/zip",
		},
	)
	if err != nil {
		t.Fatalf("init import upload session: %v", err)
	}

	if got, want := uploadStore.lastInit.UserID, userID; got != want {
		t.Fatalf("init user id got %s want %s", got, want)
	}
	if got, want := resp.Strategy, "single_put"; got != want {
		t.Fatalf("strategy got %q want %q", got, want)
	}
	if got, want := resp.URL, provider.putURL; got != want {
		t.Fatalf("url got %q want %q", got, want)
	}
	if got, want := provider.lastSignPutObjectKey, uploadStore.initSession.ObjectKey; got != want {
		t.Fatalf("sign put object key got %q want %q", got, want)
	}
}

func TestCompleteImportUploadSessionValidatesRemoteObjectWithProviderStat(t *testing.T) {
	userID := uuid.New()
	sessionID := uuid.New()
	session := &importrepo.UploadSession{
		ID:        sessionID,
		UserID:    userID,
		Mode:      "project_annotations",
		FileName:  "annotations.zip",
		ObjectKey: "imports/u/annotations.zip",
		Status:    "initiated",
	}
	uploadStore := &fakeUploadStore{
		getSession: session,
		completeSession: &importrepo.UploadSession{
			ID:        sessionID,
			UserID:    userID,
			Mode:      "project_annotations",
			FileName:  "annotations.zip",
			ObjectKey: "imports/u/annotations.zip",
			Status:    "completed",
		},
	}
	provider := &fakeObjectProvider{
		stat: &storage.ObjectStat{
			Size: 128,
		},
	}
	handler := NewHandlers(Dependencies{
		Uploads:  uploadStore,
		Tasks:    &fakeTaskStore{},
		Prepare:  fakePrepareUseCase{},
		Execute:  fakeExecuteUseCase{},
		Provider: provider,
	})

	resp, err := handler.CompleteImportUploadSession(
		contextWithUser(userID),
		&openapi.ImportUploadCompleteRequest{Size: 128},
		openapi.CompleteImportUploadSessionParams{SessionID: sessionID.String()},
	)
	if err != nil {
		t.Fatalf("complete import upload session: %v", err)
	}
	if got, want := provider.lastStatObjectKey, session.ObjectKey; got != want {
		t.Fatalf("stat object key got %q want %q", got, want)
	}
	if got, want := uploadStore.lastMarkCompletedID, sessionID; got != want {
		t.Fatalf("mark completed id got %s want %s", got, want)
	}
	if got, want := resp.Status, "completed"; got != want {
		t.Fatalf("status got %q want %q", got, want)
	}
}

func TestGetImportUploadSessionReturnsSignedPutURL(t *testing.T) {
	userID := uuid.New()
	session := &importrepo.UploadSession{
		ID:        uuid.New(),
		UserID:    userID,
		Mode:      "project_annotations",
		FileName:  "annotations.zip",
		ObjectKey: "imports/u/annotations.zip",
		Status:    "initiated",
	}
	provider := &fakeObjectProvider{
		putURL: "http://object.test/imports/signed-upload-get",
	}
	handler := NewHandlers(Dependencies{
		Uploads:  &fakeUploadStore{getSession: session},
		Tasks:    &fakeTaskStore{},
		Prepare:  fakePrepareUseCase{},
		Execute:  fakeExecuteUseCase{},
		Provider: provider,
	})

	resp, err := handler.GetImportUploadSession(contextWithUser(userID), openapi.GetImportUploadSessionParams{
		SessionID: session.ID.String(),
	})
	if err != nil {
		t.Fatalf("get import upload session: %v", err)
	}
	if got, want := resp.URL, provider.putURL; got != want {
		t.Fatalf("url got %q want %q", got, want)
	}
	if got, want := provider.lastSignPutObjectKey, session.ObjectKey; got != want {
		t.Fatalf("sign put object key got %q want %q", got, want)
	}
}

func TestTryServeHTTPStreamsTaskEvents(t *testing.T) {
	userID := uuid.New()
	taskID := uuid.New()
	handler := NewHandlers(Dependencies{
		Uploads: &fakeUploadStore{},
		Tasks: &fakeTaskStore{
			task: &importrepo.ImportTask{
				ID:           taskID,
				UserID:       userID,
				Mode:         "project_annotations",
				ResourceType: "project",
				ResourceID:   uuid.New(),
				Status:       "completed",
				CreatedAt:    time.Now(),
				UpdatedAt:    time.Now(),
			},
			events: []importrepo.ImportTaskEvent{
				{
					Seq:       1,
					TaskID:    taskID,
					Event:     "complete",
					Phase:     "project_annotations_execute",
					Payload:   []byte(`{"message":"done","created_annotations":1}`),
					CreatedAt: time.Now(),
				},
			},
		},
		Prepare:  fakePrepareUseCase{},
		Execute:  fakeExecuteUseCase{},
		Provider: &fakeObjectProvider{},
	})

	req := httptest.NewRequest(http.MethodGet, "/imports/tasks/"+taskID.String()+"/events?after_seq=0", nil)
	req = req.WithContext(contextWithUser(userID))
	rec := httptest.NewRecorder()

	if !handler.TryServeHTTP(rec, req) {
		t.Fatal("expected task events route to be handled")
	}
	if rec.Code != http.StatusOK {
		t.Fatalf("unexpected status: %d body=%s", rec.Code, rec.Body.String())
	}
	if ct := rec.Header().Get("Content-Type"); !strings.Contains(ct, "text/event-stream") {
		t.Fatalf("unexpected content type: %s", ct)
	}
	if !strings.Contains(rec.Body.String(), `"event":"complete"`) || !strings.Contains(rec.Body.String(), `"message":"done"`) {
		t.Fatalf("unexpected event stream body: %s", rec.Body.String())
	}
}

func contextWithUser(userID uuid.UUID) context.Context {
	return authctx.WithClaims(context.Background(), &accessapp.Claims{
		UserID:      userID.String(),
		Permissions: []string{"imports:read", "imports:write"},
		ExpiresAt:   time.Now().Add(time.Hour),
	})
}

type fakeUploadStore struct {
	initSession         *importrepo.UploadSession
	getSession          *importrepo.UploadSession
	lastInit            importrepo.InitUploadSessionParams
	completeSession     *importrepo.UploadSession
	lastMarkCompletedID uuid.UUID
}

func (s *fakeUploadStore) Init(_ context.Context, params importrepo.InitUploadSessionParams) (*importrepo.UploadSession, error) {
	s.lastInit = params
	if s.initSession != nil {
		return s.initSession, nil
	}
	return &importrepo.UploadSession{
		ID:          uuid.New(),
		UserID:      params.UserID,
		Mode:        params.Mode,
		FileName:    params.FileName,
		ObjectKey:   params.ObjectKey,
		ContentType: params.ContentType,
		Status:      "initiated",
	}, nil
}

func (s *fakeUploadStore) Get(_ context.Context, id uuid.UUID) (*importrepo.UploadSession, error) {
	if s.getSession != nil {
		return s.getSession, nil
	}
	if s.initSession != nil && s.initSession.ID == id {
		return s.initSession, nil
	}
	return nil, nil
}

func (s *fakeUploadStore) MarkCompleted(_ context.Context, id uuid.UUID) (*importrepo.UploadSession, error) {
	s.lastMarkCompletedID = id
	if s.completeSession != nil {
		return s.completeSession, nil
	}
	return s.getSession, nil
}

func (s *fakeUploadStore) Abort(_ context.Context, _ uuid.UUID) (*importrepo.UploadSession, error) {
	return s.getSession, nil
}

type fakeTaskStore struct {
	task   *importrepo.ImportTask
	events []importrepo.ImportTaskEvent
}

func (s *fakeTaskStore) Get(_ context.Context, _ uuid.UUID) (*importrepo.ImportTask, error) {
	return s.task, nil
}

func (s *fakeTaskStore) ListEventsAfter(_ context.Context, _ uuid.UUID, afterSeq int64, _ int32) ([]importrepo.ImportTaskEvent, error) {
	result := make([]importrepo.ImportTaskEvent, 0, len(s.events))
	for _, event := range s.events {
		if event.Seq > afterSeq {
			result = append(result, event)
		}
	}
	return result, nil
}

type fakePrepareUseCase struct{}

func (fakePrepareUseCase) Execute(context.Context, importapp.PrepareProjectAnnotationsInput) (*importapp.PrepareProjectAnnotationsResult, error) {
	return &importapp.PrepareProjectAnnotationsResult{}, nil
}

type fakeExecuteUseCase struct{}

func (fakeExecuteUseCase) Execute(context.Context, importapp.ExecuteProjectAnnotationsInput) (*importrepo.ImportTask, error) {
	return &importrepo.ImportTask{}, nil
}

type fakeObjectProvider struct {
	putURL string
	stat   *storage.ObjectStat

	lastSignPutObjectKey string
	lastStatObjectKey    string
}

func (p *fakeObjectProvider) Bucket() string { return "imports" }

func (p *fakeObjectProvider) SignPutObject(_ context.Context, objectKey string, _ time.Duration, _ string) (string, error) {
	p.lastSignPutObjectKey = objectKey
	if p.putURL == "" {
		return "http://object.test/" + objectKey, nil
	}
	return p.putURL, nil
}

func (p *fakeObjectProvider) SignGetObject(context.Context, string, time.Duration) (string, error) {
	return "", nil
}

func (p *fakeObjectProvider) StatObject(_ context.Context, objectKey string) (*storage.ObjectStat, error) {
	p.lastStatObjectKey = objectKey
	if p.stat == nil {
		return nil, errors.New("missing fake stat")
	}
	return p.stat, nil
}

func (p *fakeObjectProvider) DownloadObject(context.Context, string, string) error {
	return nil
}
