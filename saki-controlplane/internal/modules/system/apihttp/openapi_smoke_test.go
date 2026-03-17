package apihttp_test

import (
	"archive/zip"
	"bytes"
	"context"
	"database/sql"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os/exec"
	"path/filepath"
	"runtime"
	"slices"
	"strconv"
	"strings"
	"testing"
	"time"

	"github.com/elebirds/saki/saki-controlplane/internal/app/bootstrap"
	appdb "github.com/elebirds/saki/saki-controlplane/internal/app/db"
	annotationrepo "github.com/elebirds/saki/saki-controlplane/internal/modules/annotation/repo"
	datasetrepo "github.com/elebirds/saki/saki-controlplane/internal/modules/dataset/repo"
	importrepo "github.com/elebirds/saki/saki-controlplane/internal/modules/importing/repo"
	projectrepo "github.com/elebirds/saki/saki-controlplane/internal/modules/project/repo"
	runtimecommands "github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/app/commands"
	runtimerepo "github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/repo"
	"github.com/google/uuid"
	_ "github.com/jackc/pgx/v5/stdlib"
	"github.com/pressly/goose/v3"
	"github.com/testcontainers/testcontainers-go"
	"github.com/testcontainers/testcontainers-go/modules/postgres"
	"github.com/testcontainers/testcontainers-go/wait"
)

func TestPublicAPISmoke(t *testing.T) {
	t.Setenv("TESTCONTAINERS_RYUK_DISABLED", "true")

	ctx := context.Background()
	container, dsn := startSmokePostgres(t, ctx)
	defer func() {
		_ = testcontainers.TerminateContainer(container)
	}()

	sqlDB, err := sql.Open("pgx", dsn)
	if err != nil {
		t.Fatalf("open sql db: %v", err)
	}
	defer sqlDB.Close()

	goose.SetDialect("postgres")
	if err := goose.Up(sqlDB, smokeMigrationsDir(t)); err != nil {
		t.Fatalf("run migrations: %v", err)
	}

	pool, err := appdb.NewPool(ctx, dsn)
	if err != nil {
		t.Fatalf("create pgx pool: %v", err)
	}
	defer pool.Close()

	datasetRepo := datasetrepo.NewDatasetRepo(pool)
	sampleRepo := annotationrepo.NewSampleRepo(pool)
	projectRepo := projectrepo.NewProjectRepo(pool)
	matchRefRepo := importrepo.NewSampleMatchRefRepo(pool)
	project, err := projectRepo.CreateProject(ctx, projectrepo.CreateProjectParams{Name: "smoke-project"})
	if err != nil {
		t.Fatalf("create smoke project: %v", err)
	}
	dataset, err := datasetRepo.Create(ctx, datasetrepo.CreateDatasetParams{Name: "smoke-dataset", Type: "single-view"})
	if err != nil {
		t.Fatalf("create smoke dataset: %v", err)
	}
	if _, err := projectRepo.LinkDataset(ctx, project.ID, dataset.ID); err != nil {
		t.Fatalf("link smoke dataset: %v", err)
	}
	sample, err := sampleRepo.Create(ctx, annotationrepo.CreateSampleParams{
		DatasetID: dataset.ID,
		Name:      "sample1",
		Meta:      []byte(`{}`),
	})
	if err != nil {
		t.Fatalf("create smoke sample: %v", err)
	}
	if _, err := matchRefRepo.Put(ctx, importrepo.PutSampleMatchRefParams{
		DatasetID: dataset.ID,
		SampleID:  sample.ID,
		RefType:   "dataset_relpath",
		RefValue:  "images/train/sample1.jpg",
		IsPrimary: true,
	}); err != nil {
		t.Fatalf("create smoke sample match ref: %v", err)
	}

	importUserID := uuid.MustParse("00000000-0000-0000-0000-000000000200")
	setSmokeBootstrapPrincipalEnv(t, dsn, importUserID, "Smoke Import User", []string{
		"projects:read",
		"projects:write",
		"imports:read",
		"imports:write",
	})

	server, _, err := bootstrap.NewPublicAPI(context.Background())
	if err != nil {
		t.Fatalf("bootstrap public api: %v", err)
	}

	httpServer := httptest.NewServer(server.Handler)
	defer httpServer.Close()

	resp, err := http.Get(httpServer.URL + "/healthz")
	if err != nil {
		t.Fatalf("get healthz: %v", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("unexpected healthz status: %d", resp.StatusCode)
	}

	loginResp, err := http.Post(
		httpServer.URL+"/auth/login",
		"application/json",
		bytes.NewBufferString(`{"user_id":"`+importUserID.String()+`"}`),
	)
	if err != nil {
		t.Fatalf("post login: %v", err)
	}
	defer loginResp.Body.Close()
	if loginResp.StatusCode != http.StatusOK {
		t.Fatalf("unexpected login status: %d", loginResp.StatusCode)
	}
	var loginBody map[string]any
	if err := json.NewDecoder(loginResp.Body).Decode(&loginBody); err != nil {
		t.Fatalf("decode login response: %v", err)
	}
	token, _ := loginBody["token"].(string)
	if token == "" {
		t.Fatalf("missing auth token: %+v", loginBody)
	}

	summaryResp, err := http.Get(httpServer.URL + "/runtime/summary")
	if err != nil {
		t.Fatalf("get runtime summary: %v", err)
	}
	defer summaryResp.Body.Close()
	if summaryResp.StatusCode != http.StatusOK {
		t.Fatalf("unexpected runtime summary status: %d", summaryResp.StatusCode)
	}

	var summary map[string]any
	if err := json.NewDecoder(summaryResp.Body).Decode(&summary); err != nil {
		t.Fatalf("decode runtime summary: %v", err)
	}
	if _, ok := summary["pending_tasks"]; !ok {
		t.Fatalf("unexpected runtime summary body: %+v", summary)
	}

	createAnnotationResp, err := http.Post(
		httpServer.URL+"/projects/"+project.ID.String()+"/samples/"+sample.ID.String()+"/annotations",
		"application/json",
		bytes.NewBufferString(`{"group_id":"smoke-group","label_id":"smoke-label","view":"rgb","annotation_type":"rect","geometry":{"x":1,"y":2,"w":3,"h":4},"attrs":{"score":0.5},"source":"manual"}`),
	)
	if err != nil {
		t.Fatalf("post sample annotations: %v", err)
	}
	defer createAnnotationResp.Body.Close()
	if createAnnotationResp.StatusCode != http.StatusCreated {
		t.Fatalf("unexpected create annotation status: %d", createAnnotationResp.StatusCode)
	}

	var created []map[string]any
	if err := json.NewDecoder(createAnnotationResp.Body).Decode(&created); err != nil {
		t.Fatalf("decode create annotation response: %v", err)
	}
	if len(created) != 1 || created[0]["sample_id"] != sample.ID.String() {
		t.Fatalf("unexpected create annotation body: %+v", created)
	}

	listAnnotationResp, err := http.Get(httpServer.URL + "/projects/" + project.ID.String() + "/samples/" + sample.ID.String() + "/annotations")
	if err != nil {
		t.Fatalf("get sample annotations: %v", err)
	}
	defer listAnnotationResp.Body.Close()
	if listAnnotationResp.StatusCode != http.StatusOK {
		t.Fatalf("unexpected list annotation status: %d", listAnnotationResp.StatusCode)
	}

	var listed []map[string]any
	if err := json.NewDecoder(listAnnotationResp.Body).Decode(&listed); err != nil {
		t.Fatalf("decode list annotation response: %v", err)
	}
	if len(listed) != 1 || listed[0]["view"] != "rgb" || listed[0]["annotation_type"] != "rect" {
		t.Fatalf("unexpected list annotation body: %+v", listed)
	}

	importArchive := makeCOCOImportArchive(t)

	initReq, err := http.NewRequest(
		http.MethodPost,
		httpServer.URL+"/imports/uploads:init",
		bytes.NewBufferString(`{"mode":"project_annotations","resource_type":"project","resource_id":"`+project.ID.String()+`","filename":"annotations.zip","size":`+jsonNumber(len(importArchive))+`,"content_type":"application/zip"}`),
	)
	if err != nil {
		t.Fatalf("new upload init request: %v", err)
	}
	initReq.Header.Set("Authorization", "Bearer "+token)
	initReq.Header.Set("Content-Type", "application/json")
	initResp, err := http.DefaultClient.Do(initReq)
	if err != nil {
		t.Fatalf("post upload init: %v", err)
	}
	defer initResp.Body.Close()
	if initResp.StatusCode != http.StatusCreated {
		t.Fatalf("unexpected upload init status: %d", initResp.StatusCode)
	}

	var initBody map[string]any
	if err := json.NewDecoder(initResp.Body).Decode(&initBody); err != nil {
		t.Fatalf("decode upload init response: %v", err)
	}
	sessionID, _ := initBody["session_id"].(string)
	uploadURL, _ := initBody["url"].(string)
	if sessionID == "" || uploadURL == "" {
		t.Fatalf("unexpected upload init body: %+v", initBody)
	}

	uploadReq, err := http.NewRequest(http.MethodPut, httpServer.URL+uploadURL, bytes.NewReader(importArchive))
	if err != nil {
		t.Fatalf("new upload content request: %v", err)
	}
	uploadReq.Header.Set("Content-Type", "application/zip")
	uploadResp, err := http.DefaultClient.Do(uploadReq)
	if err != nil {
		t.Fatalf("put upload content: %v", err)
	}
	defer uploadResp.Body.Close()
	if uploadResp.StatusCode != http.StatusNoContent {
		t.Fatalf("unexpected upload content status: %d", uploadResp.StatusCode)
	}

	completeReq, err := http.NewRequest(
		http.MethodPost,
		httpServer.URL+"/imports/uploads/"+sessionID+":complete",
		bytes.NewBufferString(`{"size":`+jsonNumber(len(importArchive))+`,"parts":[]}`),
	)
	if err != nil {
		t.Fatalf("new upload complete request: %v", err)
	}
	completeReq.Header.Set("Authorization", "Bearer "+token)
	completeReq.Header.Set("Content-Type", "application/json")
	completeResp, err := http.DefaultClient.Do(completeReq)
	if err != nil {
		t.Fatalf("post upload complete: %v", err)
	}
	defer completeResp.Body.Close()
	if completeResp.StatusCode != http.StatusOK {
		t.Fatalf("unexpected upload complete status: %d", completeResp.StatusCode)
	}

	prepareReq, err := http.NewRequest(
		http.MethodPost,
		httpServer.URL+"/projects/"+project.ID.String()+"/datasets/"+dataset.ID.String()+"/imports/annotations:prepare",
		bytes.NewBufferString(`{"upload_session_id":"`+sessionID+`","format_profile":"coco"}`),
	)
	if err != nil {
		t.Fatalf("new prepare request: %v", err)
	}
	prepareReq.Header.Set("Authorization", "Bearer "+token)
	prepareReq.Header.Set("Content-Type", "application/json")
	prepareResp, err := http.DefaultClient.Do(prepareReq)
	if err != nil {
		t.Fatalf("post prepare: %v", err)
	}
	defer prepareResp.Body.Close()
	if prepareResp.StatusCode != http.StatusOK {
		t.Fatalf("unexpected prepare status: %d", prepareResp.StatusCode)
	}

	var prepareBody map[string]any
	if err := json.NewDecoder(prepareResp.Body).Decode(&prepareBody); err != nil {
		t.Fatalf("decode prepare response: %v", err)
	}
	previewToken, _ := prepareBody["preview_token"].(string)
	if previewToken == "" {
		t.Fatalf("missing preview token: %+v", prepareBody)
	}

	executeReq, err := http.NewRequest(
		http.MethodPost,
		httpServer.URL+"/projects/"+project.ID.String()+"/datasets/"+dataset.ID.String()+"/imports/annotations:execute",
		bytes.NewBufferString(`{"preview_token":"`+previewToken+`"}`),
	)
	if err != nil {
		t.Fatalf("new execute request: %v", err)
	}
	executeReq.Header.Set("Authorization", "Bearer "+token)
	executeReq.Header.Set("Content-Type", "application/json")
	executeResp, err := http.DefaultClient.Do(executeReq)
	if err != nil {
		t.Fatalf("post execute: %v", err)
	}
	defer executeResp.Body.Close()
	if executeResp.StatusCode != http.StatusAccepted {
		t.Fatalf("unexpected execute status: %d", executeResp.StatusCode)
	}

	var executeBody map[string]any
	if err := json.NewDecoder(executeResp.Body).Decode(&executeBody); err != nil {
		t.Fatalf("decode execute response: %v", err)
	}
	taskID, _ := executeBody["task_id"].(string)
	if taskID == "" {
		t.Fatalf("missing task id: %+v", executeBody)
	}

	taskReq, err := http.NewRequest(http.MethodGet, httpServer.URL+"/imports/tasks/"+taskID, nil)
	if err != nil {
		t.Fatalf("new task status request: %v", err)
	}
	taskReq.Header.Set("Authorization", "Bearer "+token)
	taskResp, err := http.DefaultClient.Do(taskReq)
	if err != nil {
		t.Fatalf("get import task: %v", err)
	}
	defer taskResp.Body.Close()
	if taskResp.StatusCode != http.StatusOK {
		t.Fatalf("unexpected import task status: %d", taskResp.StatusCode)
	}

	resultReq, err := http.NewRequest(http.MethodGet, httpServer.URL+"/imports/tasks/"+taskID+"/result", nil)
	if err != nil {
		t.Fatalf("new task result request: %v", err)
	}
	resultReq.Header.Set("Authorization", "Bearer "+token)
	resultResp, err := http.DefaultClient.Do(resultReq)
	if err != nil {
		t.Fatalf("get import task result: %v", err)
	}
	defer resultResp.Body.Close()
	if resultResp.StatusCode != http.StatusOK {
		t.Fatalf("unexpected import task result status: %d", resultResp.StatusCode)
	}
	var resultBody map[string]any
	if err := json.NewDecoder(resultResp.Body).Decode(&resultBody); err != nil {
		t.Fatalf("decode import task result: %v", err)
	}
	if resultBody["status"] != "completed" {
		t.Fatalf("unexpected import task result body: %+v", resultBody)
	}

	eventsReq, err := http.NewRequest(http.MethodGet, httpServer.URL+"/imports/tasks/"+taskID+"/events?after_seq=0", nil)
	if err != nil {
		t.Fatalf("new task events request: %v", err)
	}
	eventsReq.Header.Set("Authorization", "Bearer "+token)
	eventsResp, err := http.DefaultClient.Do(eventsReq)
	if err != nil {
		t.Fatalf("get import task events: %v", err)
	}
	defer eventsResp.Body.Close()
	if eventsResp.StatusCode != http.StatusOK {
		t.Fatalf("unexpected import task events status: %d", eventsResp.StatusCode)
	}
	if ct := eventsResp.Header.Get("Content-Type"); !strings.Contains(ct, "text/event-stream") {
		t.Fatalf("unexpected import task events content-type: %s", ct)
	}
	eventBytes := new(bytes.Buffer)
	if _, err := eventBytes.ReadFrom(eventsResp.Body); err != nil {
		t.Fatalf("read import task events body: %v", err)
	}
	if !strings.Contains(eventBytes.String(), `"event":"complete"`) {
		t.Fatalf("unexpected import task events body: %s", eventBytes.String())
	}

	importedListResp, err := http.Get(httpServer.URL + "/projects/" + project.ID.String() + "/samples/" + sample.ID.String() + "/annotations")
	if err != nil {
		t.Fatalf("get imported sample annotations: %v", err)
	}
	defer importedListResp.Body.Close()
	if importedListResp.StatusCode != http.StatusOK {
		t.Fatalf("unexpected imported annotation list status: %d", importedListResp.StatusCode)
	}
	var importedListed []map[string]any
	if err := json.NewDecoder(importedListResp.Body).Decode(&importedListed); err != nil {
		t.Fatalf("decode imported annotation list response: %v", err)
	}
	if len(importedListed) != 2 {
		t.Fatalf("expected imported annotation to be persisted, got %+v", importedListed)
	}
}

func TestPublicAPISmoke_AccessLoginAndMe(t *testing.T) {
	httpServer, _, userID := newSmokeAccessServer(t, []string{"projects:read", "imports:read"})

	token, permissions := loginSmokeUser(t, httpServer.URL, userID)
	if token == "" {
		t.Fatal("expected login token")
	}
	if !slices.Equal(permissions, []string{"imports:read", "projects:read"}) {
		t.Fatalf("unexpected login permissions: %+v", permissions)
	}

	req, err := http.NewRequest(http.MethodGet, httpServer.URL+"/auth/me", nil)
	if err != nil {
		t.Fatalf("new me request: %v", err)
	}
	req.Header.Set("Authorization", "Bearer "+token)

	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("get auth me: %v", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("unexpected auth me status: %d", resp.StatusCode)
	}

	var body struct {
		UserID      string   `json:"user_id"`
		Permissions []string `json:"permissions"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&body); err != nil {
		t.Fatalf("decode auth me response: %v", err)
	}
	if body.UserID != userID {
		t.Fatalf("unexpected auth me user: %+v", body)
	}
	if !slices.Equal(body.Permissions, []string{"imports:read", "projects:read"}) {
		t.Fatalf("unexpected auth me permissions: %+v", body)
	}
}

func TestPublicAPISmoke_AccessPermissionDenied(t *testing.T) {
	httpServer, sqlDB, userID := newSmokeAccessServer(t, []string{"projects:read"})

	token, permissions := loginSmokeUser(t, httpServer.URL, userID)
	if !slices.Equal(permissions, []string{"projects:read"}) {
		t.Fatalf("unexpected login permissions: %+v", permissions)
	}

	req, err := http.NewRequest(http.MethodGet, httpServer.URL+"/auth/permissions/imports:write", nil)
	if err != nil {
		t.Fatalf("new permission request: %v", err)
	}
	req.Header.Set("Authorization", "Bearer "+token)

	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("get permission check: %v", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusForbidden {
		t.Fatalf("unexpected permission status: %d", resp.StatusCode)
	}

	if _, err := sqlDB.Exec(`update access_principal set status = 'disabled' where subject_type = 'user' and subject_key = $1`, userID); err != nil {
		t.Fatalf("disable bootstrap principal: %v", err)
	}

	req, err = http.NewRequest(http.MethodGet, httpServer.URL+"/auth/me", nil)
	if err != nil {
		t.Fatalf("new auth me request: %v", err)
	}
	req.Header.Set("Authorization", "Bearer "+token)

	resp, err = http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("get auth me after disable: %v", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusUnauthorized {
		t.Fatalf("unexpected auth me status after disable: %d", resp.StatusCode)
	}
}

func TestPublicAPICancelTaskWritesStopOutbox(t *testing.T) {
	t.Setenv("TESTCONTAINERS_RYUK_DISABLED", "true")

	ctx := context.Background()
	container, dsn := startSmokePostgres(t, ctx)
	defer func() {
		_ = testcontainers.TerminateContainer(container)
	}()

	sqlDB, err := sql.Open("pgx", dsn)
	if err != nil {
		t.Fatalf("open sql db: %v", err)
	}
	defer sqlDB.Close()

	goose.SetDialect("postgres")
	if err := goose.Up(sqlDB, smokeMigrationsDir(t)); err != nil {
		t.Fatalf("run migrations: %v", err)
	}

	pool, err := appdb.NewPool(ctx, dsn)
	if err != nil {
		t.Fatalf("create pgx pool: %v", err)
	}
	defer pool.Close()

	leaseRepo := runtimerepo.NewLeaseRepo(pool)
	lease, err := leaseRepo.AcquireOrRenew(ctx, runtimerepo.AcquireLeaseParams{
		Name:       "runtime-scheduler",
		Holder:     "runtime-1",
		LeaseUntil: time.Now().Add(time.Minute),
	})
	if err != nil {
		t.Fatalf("acquire runtime lease: %v", err)
	}

	taskRepo := runtimerepo.NewTaskRepo(pool)
	taskID := uuid.New()
	if err := taskRepo.CreateTask(ctx, runtimerepo.CreateTaskParams{
		ID:       taskID,
		TaskType: "predict",
	}); err != nil {
		t.Fatalf("create runtime task: %v", err)
	}

	assigned, err := taskRepo.AssignPendingTask(ctx, runtimerepo.AssignTaskParams{
		AssignedAgentID: "agent-public-api-1",
		LeaderEpoch:     lease.Epoch,
	})
	if err != nil {
		t.Fatalf("assign runtime task: %v", err)
	}
	if assigned == nil {
		t.Fatal("expected assigned runtime task")
	}

	t.Setenv("DATABASE_DSN", dsn)
	t.Setenv("AUTH_TOKEN_SECRET", "smoke-secret")
	t.Setenv("AUTH_TOKEN_TTL", "1h")
	t.Setenv("PUBLIC_API_BIND", "127.0.0.1:0")

	server, _, err := bootstrap.NewPublicAPI(context.Background())
	if err != nil {
		t.Fatalf("bootstrap public api: %v", err)
	}

	httpServer := httptest.NewServer(server.Handler)
	defer httpServer.Close()

	req, err := http.NewRequest(http.MethodPost, httpServer.URL+"/runtime/tasks/"+taskID.String()+"/cancel", nil)
	if err != nil {
		t.Fatalf("new cancel request: %v", err)
	}
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("post cancel runtime task: %v", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusAccepted {
		t.Fatalf("unexpected cancel status: %d", resp.StatusCode)
	}

	var body map[string]any
	if err := json.NewDecoder(resp.Body).Decode(&body); err != nil {
		t.Fatalf("decode cancel response: %v", err)
	}
	if accepted, _ := body["accepted"].(bool); !accepted {
		t.Fatalf("unexpected cancel response body: %+v", body)
	}

	task, err := taskRepo.GetTask(ctx, taskID)
	if err != nil {
		t.Fatalf("load runtime task: %v", err)
	}
	if task == nil || task.Status != "cancel_requested" {
		t.Fatalf("unexpected runtime task after cancel: %+v", task)
	}

	var stopOutboxCount int
	if err := pool.QueryRow(ctx, `
select count(*)
from runtime_outbox
where aggregate_id = $1
  and topic = $2
`, taskID.String(), runtimecommands.StopTaskOutboxTopic).Scan(&stopOutboxCount); err != nil {
		t.Fatalf("count stop outbox: %v", err)
	}
	if stopOutboxCount != 1 {
		t.Fatalf("expected exactly one stop outbox, got %d", stopOutboxCount)
	}

	var payloadBytes []byte
	if err := pool.QueryRow(ctx, `
select payload
from runtime_outbox
where aggregate_id = $1
  and topic = $2
`, taskID.String(), runtimecommands.StopTaskOutboxTopic).Scan(&payloadBytes); err != nil {
		t.Fatalf("load stop outbox payload: %v", err)
	}

	var payload runtimecommands.StopTaskOutboxPayload
	if err := json.Unmarshal(payloadBytes, &payload); err != nil {
		t.Fatalf("unmarshal stop payload: %v", err)
	}
	if payload.TaskID != taskID {
		t.Fatalf("unexpected stop payload task id: %+v", payload)
	}
	if payload.ExecutionID != assigned.CurrentExecutionID {
		t.Fatalf("unexpected stop payload execution id: %+v", payload)
	}
	if payload.AgentID != "agent-public-api-1" {
		t.Fatalf("unexpected stop payload agent id: %+v", payload)
	}
	if payload.Reason != "cancel_requested" {
		t.Fatalf("unexpected stop payload reason: %+v", payload)
	}
	if payload.LeaderEpoch != lease.Epoch {
		t.Fatalf("unexpected stop payload leader epoch: %+v", payload)
	}
}

func makeCOCOImportArchive(t *testing.T) []byte {
	t.Helper()

	var buf bytes.Buffer
	archive := zip.NewWriter(&buf)
	writer, err := archive.Create("annotations.json")
	if err != nil {
		t.Fatalf("create annotations entry: %v", err)
	}
	if _, err := writer.Write([]byte(`{"images":[{"id":1,"file_name":"images/train/sample1.jpg","width":128,"height":96}],"categories":[{"id":1,"name":"car"}],"annotations":[{"id":1,"image_id":1,"category_id":1,"bbox":[10,20,30,40]}]}`)); err != nil {
		t.Fatalf("write annotations entry: %v", err)
	}
	if err := archive.Close(); err != nil {
		t.Fatalf("close archive: %v", err)
	}
	return buf.Bytes()
}

func jsonNumber(value int) string {
	return strconv.Itoa(value)
}

func newSmokeAccessServer(t *testing.T, permissions []string) (*httptest.Server, *sql.DB, string) {
	t.Helper()

	t.Setenv("TESTCONTAINERS_RYUK_DISABLED", "true")

	ctx := context.Background()
	container, dsn := startSmokePostgres(t, ctx)
	t.Cleanup(func() {
		_ = testcontainers.TerminateContainer(container)
	})

	sqlDB, err := sql.Open("pgx", dsn)
	if err != nil {
		t.Fatalf("open sql db: %v", err)
	}
	t.Cleanup(func() { _ = sqlDB.Close() })

	goose.SetDialect("postgres")
	if err := goose.Up(sqlDB, smokeMigrationsDir(t)); err != nil {
		t.Fatalf("run migrations: %v", err)
	}

	userID := uuid.New()
	setSmokeBootstrapPrincipalEnv(t, dsn, userID, "Smoke Access User", permissions)

	server, _, err := bootstrap.NewPublicAPI(ctx)
	if err != nil {
		t.Fatalf("bootstrap public api: %v", err)
	}
	t.Cleanup(func() {
		_ = server.Shutdown(context.Background())
	})

	httpServer := httptest.NewServer(server.Handler)
	t.Cleanup(httpServer.Close)

	return httpServer, sqlDB, userID.String()
}

func setSmokeBootstrapPrincipalEnv(t *testing.T, dsn string, userID uuid.UUID, displayName string, permissions []string) {
	t.Helper()

	t.Setenv("DATABASE_DSN", dsn)
	t.Setenv("AUTH_TOKEN_SECRET", "smoke-secret")
	t.Setenv("AUTH_TOKEN_TTL", "1h")
	t.Setenv("PUBLIC_API_BIND", "127.0.0.1:0")

	raw, err := json.Marshal([]map[string]any{
		{
			"user_id":      userID.String(),
			"display_name": displayName,
			"permissions":  permissions,
		},
	})
	if err != nil {
		t.Fatalf("marshal bootstrap principal env: %v", err)
	}
	t.Setenv("AUTH_BOOTSTRAP_PRINCIPALS", string(raw))
}

func loginSmokeUser(t *testing.T, baseURL string, userID string) (string, []string) {
	t.Helper()

	resp, err := http.Post(
		baseURL+"/auth/login",
		"application/json",
		bytes.NewBufferString(`{"user_id":"`+userID+`"}`),
	)
	if err != nil {
		t.Fatalf("post login: %v", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("unexpected login status: %d", resp.StatusCode)
	}

	var body struct {
		Token       string   `json:"token"`
		Permissions []string `json:"permissions"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&body); err != nil {
		t.Fatalf("decode login response: %v", err)
	}
	return body.Token, body.Permissions
}

func startSmokePostgres(t *testing.T, ctx context.Context) (*postgres.PostgresContainer, string) {
	t.Helper()

	container, err := postgres.Run(
		ctx,
		smokePostgresImageRef(),
		postgres.WithDatabase("saki"),
		postgres.WithUsername("postgres"),
		postgres.WithPassword("postgres"),
		testcontainers.WithWaitStrategy(
			wait.ForLog("database system is ready to accept connections").WithOccurrence(2),
		),
	)
	if err != nil {
		t.Fatalf("start postgres container: %v", err)
	}

	dsn, err := container.ConnectionString(ctx, "sslmode=disable")
	if err != nil {
		t.Fatalf("build postgres dsn: %v", err)
	}

	return container, dsn
}

func smokeMigrationsDir(t *testing.T) string {
	t.Helper()

	_, file, _, ok := runtime.Caller(0)
	if !ok {
		t.Fatal("resolve caller")
	}

	return filepath.Join(filepath.Dir(file), "..", "..", "..", "..", "db", "migrations")
}

func smokePostgresImageRef() string {
	cmd := exec.Command("docker", "image", "inspect", "postgres:16-alpine", "--format", "{{.Id}}")
	output, err := cmd.Output()
	if err != nil {
		return "postgres:16-alpine"
	}

	imageID := strings.TrimSpace(string(output))
	if imageID == "" {
		return "postgres:16-alpine"
	}
	return imageID
}
