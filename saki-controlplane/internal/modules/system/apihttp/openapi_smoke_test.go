package apihttp_test

import (
	"archive/zip"
	"bytes"
	"context"
	"database/sql"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"os/exec"
	"path/filepath"
	"runtime"
	"slices"
	"strconv"
	"strings"
	"sync"
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
		"assets:read",
		"assets:write",
		"datasets:write",
		"projects:read",
		"projects:write",
		"imports:read",
		"imports:write",
	})
	objectServer := newSmokeObjectServer(t)
	defer objectServer.Close()
	setSmokeObjectStorageEnv(t, objectServer)

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

	assetInitReq, err := http.NewRequest(
		http.MethodPost,
		httpServer.URL+"/assets/uploads:init",
		bytes.NewBufferString(`{"owner_type":"dataset","owner_id":"`+dataset.ID.String()+`","role":"attachment","is_primary":false,"idempotency_key":"asset-smoke-1","kind":"image","content_type":"image/png","metadata":{"source":"smoke"}}`),
	)
	if err != nil {
		t.Fatalf("new asset init request: %v", err)
	}
	assetInitReq.Header.Set("Authorization", "Bearer "+token)
	assetInitReq.Header.Set("Content-Type", "application/json")
	assetInitResp, err := http.DefaultClient.Do(assetInitReq)
	if err != nil {
		t.Fatalf("post asset init: %v", err)
	}
	defer assetInitResp.Body.Close()
	if assetInitResp.StatusCode != http.StatusCreated {
		t.Fatalf("unexpected asset init status: %d", assetInitResp.StatusCode)
	}

	var assetInitBody struct {
		Asset struct {
			ID     string `json:"id"`
			Status string `json:"status"`
		} `json:"asset"`
		IntentState string  `json:"intent_state"`
		UploadURL   *string `json:"upload_url"`
	}
	if err := json.NewDecoder(assetInitResp.Body).Decode(&assetInitBody); err != nil {
		t.Fatalf("decode asset init response: %v", err)
	}
	if assetInitBody.Asset.ID == "" ||
		assetInitBody.Asset.Status != "pending_upload" ||
		assetInitBody.IntentState != "initiated" ||
		assetInitBody.UploadURL == nil ||
		*assetInitBody.UploadURL == "" {
		t.Fatalf("unexpected asset init body: %+v", assetInitBody)
	}

	assetUploadReq, err := http.NewRequest(http.MethodPut, *assetInitBody.UploadURL, bytes.NewBufferString("asset-smoke-content"))
	if err != nil {
		t.Fatalf("new asset upload request: %v", err)
	}
	assetUploadReq.Header.Set("Content-Type", "image/png")
	assetUploadResp, err := http.DefaultClient.Do(assetUploadReq)
	if err != nil {
		t.Fatalf("put asset content: %v", err)
	}
	defer assetUploadResp.Body.Close()
	if assetUploadResp.StatusCode != http.StatusNoContent && assetUploadResp.StatusCode != http.StatusOK {
		t.Fatalf("unexpected asset upload status: %d", assetUploadResp.StatusCode)
	}

	assetCompleteReq, err := http.NewRequest(
		http.MethodPost,
		httpServer.URL+"/assets/"+assetInitBody.Asset.ID+":complete",
		bytes.NewBufferString(`{"size_bytes":19,"sha256_hex":"abc123"}`),
	)
	if err != nil {
		t.Fatalf("new asset complete request: %v", err)
	}
	assetCompleteReq.Header.Set("Authorization", "Bearer "+token)
	assetCompleteReq.Header.Set("Content-Type", "application/json")
	assetCompleteResp, err := http.DefaultClient.Do(assetCompleteReq)
	if err != nil {
		t.Fatalf("post asset complete: %v", err)
	}
	defer assetCompleteResp.Body.Close()
	if assetCompleteResp.StatusCode != http.StatusOK {
		t.Fatalf("unexpected asset complete status: %d", assetCompleteResp.StatusCode)
	}

	var assetCompleteBody map[string]any
	if err := json.NewDecoder(assetCompleteResp.Body).Decode(&assetCompleteBody); err != nil {
		t.Fatalf("decode asset complete response: %v", err)
	}
	if assetCompleteBody["id"] != assetInitBody.Asset.ID || assetCompleteBody["status"] != "ready" {
		t.Fatalf("unexpected asset complete body: %+v", assetCompleteBody)
	}

	assetCompleteReplayReq, err := http.NewRequest(
		http.MethodPost,
		httpServer.URL+"/assets/"+assetInitBody.Asset.ID+":complete",
		bytes.NewBufferString(`{"size_bytes":19,"sha256_hex":"abc123"}`),
	)
	if err != nil {
		t.Fatalf("new asset complete replay request: %v", err)
	}
	assetCompleteReplayReq.Header.Set("Authorization", "Bearer "+token)
	assetCompleteReplayReq.Header.Set("Content-Type", "application/json")
	assetCompleteReplayResp, err := http.DefaultClient.Do(assetCompleteReplayReq)
	if err != nil {
		t.Fatalf("post asset complete replay: %v", err)
	}
	defer assetCompleteReplayResp.Body.Close()
	if assetCompleteReplayResp.StatusCode != http.StatusOK {
		t.Fatalf("unexpected asset complete replay status: %d", assetCompleteReplayResp.StatusCode)
	}

	var assetCompleteReplayBody map[string]any
	if err := json.NewDecoder(assetCompleteReplayResp.Body).Decode(&assetCompleteReplayBody); err != nil {
		t.Fatalf("decode asset complete replay response: %v", err)
	}
	if assetCompleteReplayBody["id"] != assetInitBody.Asset.ID || assetCompleteReplayBody["status"] != "ready" {
		t.Fatalf("unexpected asset complete replay body: %+v", assetCompleteReplayBody)
	}

	assetGetReq, err := http.NewRequest(http.MethodGet, httpServer.URL+"/assets/"+assetInitBody.Asset.ID, nil)
	if err != nil {
		t.Fatalf("new asset get request: %v", err)
	}
	assetGetReq.Header.Set("Authorization", "Bearer "+token)
	assetGetResp, err := http.DefaultClient.Do(assetGetReq)
	if err != nil {
		t.Fatalf("get asset: %v", err)
	}
	defer assetGetResp.Body.Close()
	if assetGetResp.StatusCode != http.StatusOK {
		t.Fatalf("unexpected asset get status: %d", assetGetResp.StatusCode)
	}

	var assetGetBody map[string]any
	if err := json.NewDecoder(assetGetResp.Body).Decode(&assetGetBody); err != nil {
		t.Fatalf("decode asset get response: %v", err)
	}
	if assetGetBody["id"] != assetInitBody.Asset.ID || assetGetBody["status"] != "ready" {
		t.Fatalf("unexpected asset get body: %+v", assetGetBody)
	}

	assetSignReq, err := http.NewRequest(http.MethodPost, httpServer.URL+"/assets/"+assetInitBody.Asset.ID+":sign-download", bytes.NewBufferString(`{}`))
	if err != nil {
		t.Fatalf("new asset sign request: %v", err)
	}
	assetSignReq.Header.Set("Authorization", "Bearer "+token)
	assetSignReq.Header.Set("Content-Type", "application/json")
	assetSignResp, err := http.DefaultClient.Do(assetSignReq)
	if err != nil {
		t.Fatalf("post asset sign-download: %v", err)
	}
	defer assetSignResp.Body.Close()
	if assetSignResp.StatusCode != http.StatusOK {
		t.Fatalf("unexpected asset sign-download status: %d", assetSignResp.StatusCode)
	}

	var assetSignBody map[string]any
	if err := json.NewDecoder(assetSignResp.Body).Decode(&assetSignBody); err != nil {
		t.Fatalf("decode asset sign-download response: %v", err)
	}
	if assetSignBody["asset_id"] != assetInitBody.Asset.ID {
		t.Fatalf("unexpected asset sign-download body: %+v", assetSignBody)
	}
	if downloadURL, _ := assetSignBody["download_url"].(string); downloadURL == "" {
		t.Fatalf("unexpected asset sign-download body: %+v", assetSignBody)
	}

	cancelInitReq, err := http.NewRequest(
		http.MethodPost,
		httpServer.URL+"/assets/uploads:init",
		bytes.NewBufferString(`{"owner_type":"dataset","owner_id":"`+dataset.ID.String()+`","role":"attachment","is_primary":false,"idempotency_key":"asset-smoke-cancel-1","kind":"image","content_type":"image/png","metadata":{"source":"smoke-cancel"}}`),
	)
	if err != nil {
		t.Fatalf("new cancel asset init request: %v", err)
	}
	cancelInitReq.Header.Set("Authorization", "Bearer "+token)
	cancelInitReq.Header.Set("Content-Type", "application/json")
	cancelInitResp, err := http.DefaultClient.Do(cancelInitReq)
	if err != nil {
		t.Fatalf("post cancel asset init: %v", err)
	}
	defer cancelInitResp.Body.Close()
	if cancelInitResp.StatusCode != http.StatusCreated {
		t.Fatalf("unexpected cancel asset init status: %d", cancelInitResp.StatusCode)
	}

	var cancelInitBody struct {
		Asset struct {
			ID string `json:"id"`
		} `json:"asset"`
		IntentState string `json:"intent_state"`
	}
	if err := json.NewDecoder(cancelInitResp.Body).Decode(&cancelInitBody); err != nil {
		t.Fatalf("decode cancel asset init response: %v", err)
	}
	if cancelInitBody.Asset.ID == "" || cancelInitBody.IntentState != "initiated" {
		t.Fatalf("unexpected cancel asset init body: %+v", cancelInitBody)
	}

	cancelReq, err := http.NewRequest(http.MethodPost, httpServer.URL+"/assets/"+cancelInitBody.Asset.ID+":cancel", nil)
	if err != nil {
		t.Fatalf("new asset cancel request: %v", err)
	}
	cancelReq.Header.Set("Authorization", "Bearer "+token)
	cancelResp, err := http.DefaultClient.Do(cancelReq)
	if err != nil {
		t.Fatalf("post asset cancel: %v", err)
	}
	defer cancelResp.Body.Close()
	if cancelResp.StatusCode != http.StatusOK {
		t.Fatalf("unexpected asset cancel status: %d", cancelResp.StatusCode)
	}

	var cancelBody map[string]any
	if err := json.NewDecoder(cancelResp.Body).Decode(&cancelBody); err != nil {
		t.Fatalf("decode asset cancel response: %v", err)
	}
	if cancelBody["asset_id"] != cancelInitBody.Asset.ID || cancelBody["intent_state"] != "canceled" {
		t.Fatalf("unexpected asset cancel body: %+v", cancelBody)
	}

	cancelCompleteReq, err := http.NewRequest(
		http.MethodPost,
		httpServer.URL+"/assets/"+cancelInitBody.Asset.ID+":complete",
		bytes.NewBufferString(`{"size_bytes":19}`),
	)
	if err != nil {
		t.Fatalf("new canceled asset complete request: %v", err)
	}
	cancelCompleteReq.Header.Set("Authorization", "Bearer "+token)
	cancelCompleteReq.Header.Set("Content-Type", "application/json")
	cancelCompleteResp, err := http.DefaultClient.Do(cancelCompleteReq)
	if err != nil {
		t.Fatalf("post canceled asset complete: %v", err)
	}
	defer cancelCompleteResp.Body.Close()
	if cancelCompleteResp.StatusCode != http.StatusConflict {
		t.Fatalf("unexpected canceled asset complete status: %d", cancelCompleteResp.StatusCode)
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
	if strings.HasPrefix(uploadURL, "/imports/uploads/") {
		t.Fatalf("expected signed object storage url, got local upload route: %s", uploadURL)
	}

	uploadReq, err := http.NewRequest(http.MethodPut, uploadURL, bytes.NewReader(importArchive))
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

	deleteSampleReq, err := http.NewRequest(http.MethodDelete, httpServer.URL+"/datasets/"+dataset.ID.String()+"/samples/"+sample.ID.String(), nil)
	if err != nil {
		t.Fatalf("new delete sample request: %v", err)
	}
	deleteSampleResp, err := http.DefaultClient.Do(deleteSampleReq)
	if err != nil {
		t.Fatalf("delete smoke sample: %v", err)
	}
	defer deleteSampleResp.Body.Close()
	if deleteSampleResp.StatusCode != http.StatusNoContent {
		t.Fatalf("unexpected delete smoke sample status: %d", deleteSampleResp.StatusCode)
	}

	deletedSample, err := sampleRepo.Get(ctx, sample.ID)
	if err != nil {
		t.Fatalf("get deleted smoke sample: %v", err)
	}
	if deletedSample != nil {
		t.Fatalf("expected smoke sample to be deleted, got %+v", deletedSample)
	}

	var annotationCount int
	if err := sqlDB.QueryRowContext(ctx, `select count(*) from annotation where sample_id = $1`, sample.ID).Scan(&annotationCount); err != nil {
		t.Fatalf("count smoke sample annotations: %v", err)
	}
	if annotationCount != 0 {
		t.Fatalf("expected smoke sample annotations to be deleted, got %d", annotationCount)
	}

	var matchRefCount int
	if err := sqlDB.QueryRowContext(ctx, `select count(*) from sample_match_ref where sample_id = $1`, sample.ID).Scan(&matchRefCount); err != nil {
		t.Fatalf("count smoke sample match refs: %v", err)
	}
	if matchRefCount != 0 {
		t.Fatalf("expected smoke sample match refs to be deleted, got %d", matchRefCount)
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
	t.Setenv("MINIO_ENDPOINT", "127.0.0.1:9000")
	t.Setenv("MINIO_ACCESS_KEY", "test-access")
	t.Setenv("MINIO_SECRET_KEY", "test-secret")
	t.Setenv("MINIO_BUCKET_NAME", "assets")
	t.Setenv("MINIO_SECURE", "false")

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
	t.Setenv("MINIO_ENDPOINT", "127.0.0.1:9000")
	t.Setenv("MINIO_ACCESS_KEY", "test-access")
	t.Setenv("MINIO_SECRET_KEY", "test-secret")
	t.Setenv("MINIO_BUCKET_NAME", "assets")
	t.Setenv("MINIO_SECURE", "false")

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

func setSmokeObjectStorageEnv(t *testing.T, s *smokeObjectServer) {
	t.Helper()

	t.Setenv("MINIO_ENDPOINT", strings.TrimPrefix(s.server.URL, "http://"))
	t.Setenv("MINIO_ACCESS_KEY", "test-access")
	t.Setenv("MINIO_SECRET_KEY", "test-secret")
	t.Setenv("MINIO_BUCKET_NAME", "assets")
	t.Setenv("MINIO_SECURE", "false")
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

type smokeObjectServer struct {
	server  *httptest.Server
	mu      sync.RWMutex
	objects map[string]smokeStoredObject
}

type smokeStoredObject struct {
	body        []byte
	contentType string
}

func newSmokeObjectServer(t *testing.T) *smokeObjectServer {
	t.Helper()

	s := &smokeObjectServer{
		objects: make(map[string]smokeStoredObject),
	}
	s.server = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		key := strings.TrimPrefix(r.URL.Path, "/assets/")
		if key == r.URL.Path || key == "" {
			http.NotFound(w, r)
			return
		}

		switch r.Method {
		case http.MethodPut:
			body, err := io.ReadAll(r.Body)
			if err != nil {
				http.Error(w, err.Error(), http.StatusBadRequest)
				return
			}
			s.mu.Lock()
			s.objects[key] = smokeStoredObject{
				body:        body,
				contentType: r.Header.Get("Content-Type"),
			}
			s.mu.Unlock()
			w.WriteHeader(http.StatusNoContent)
		case http.MethodHead:
			s.mu.RLock()
			obj, ok := s.objects[key]
			s.mu.RUnlock()
			if !ok {
				http.NotFound(w, r)
				return
			}
			w.Header().Set("ETag", "\"smoke-etag\"")
			w.Header().Set("Last-Modified", "Mon, 02 Jan 2006 15:04:05 GMT")
			w.Header().Set("Content-Length", strconv.Itoa(len(obj.body)))
			w.Header().Set("Content-Type", obj.contentType)
			w.WriteHeader(http.StatusOK)
		case http.MethodGet:
			s.mu.RLock()
			obj, ok := s.objects[key]
			s.mu.RUnlock()
			if !ok {
				http.NotFound(w, r)
				return
			}
			w.Header().Set("ETag", "\"smoke-etag\"")
			w.Header().Set("Last-Modified", "Mon, 02 Jan 2006 15:04:05 GMT")
			w.Header().Set("Content-Length", strconv.Itoa(len(obj.body)))
			w.Header().Set("Content-Type", obj.contentType)
			w.WriteHeader(http.StatusOK)
			_, _ = w.Write(obj.body)
		default:
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		}
	}))
	return s
}

func (s *smokeObjectServer) Close() {
	s.server.Close()
}
