package apihttp_test

import (
	"bytes"
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"net"
	"net/http"
	"net/http/httptest"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
	"time"

	appbootstrap "github.com/elebirds/saki/saki-controlplane/internal/app/bootstrap"
	appdb "github.com/elebirds/saki/saki-controlplane/internal/app/db"
	openapi "github.com/elebirds/saki/saki-controlplane/internal/gen/openapi"
	accessapp "github.com/elebirds/saki/saki-controlplane/internal/modules/access/app"
	annotationrepo "github.com/elebirds/saki/saki-controlplane/internal/modules/annotation/repo"
	assetrepo "github.com/elebirds/saki/saki-controlplane/internal/modules/asset/repo"
	datasetapi "github.com/elebirds/saki/saki-controlplane/internal/modules/dataset/apihttp"
	datasetapp "github.com/elebirds/saki/saki-controlplane/internal/modules/dataset/app"
	datasetrepo "github.com/elebirds/saki/saki-controlplane/internal/modules/dataset/repo"
	importrepo "github.com/elebirds/saki/saki-controlplane/internal/modules/importing/repo"
	projectapp "github.com/elebirds/saki/saki-controlplane/internal/modules/project/app"
	projectrepo "github.com/elebirds/saki/saki-controlplane/internal/modules/project/repo"
	runtimecommands "github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/app/commands"
	runtimequeries "github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/app/queries"
	systemapi "github.com/elebirds/saki/saki-controlplane/internal/modules/system/apihttp"
	"github.com/google/uuid"
	_ "github.com/jackc/pgx/v5/stdlib"
	"github.com/pressly/goose/v3"
	"github.com/testcontainers/testcontainers-go"
	"github.com/testcontainers/testcontainers-go/modules/postgres"
	"github.com/testcontainers/testcontainers-go/wait"
)

func TestCreateListGetUpdateDeleteDatasetEndpoints(t *testing.T) {
	handler, err := newTestHTTPHandler()
	if err != nil {
		t.Fatalf("new http handler: %v", err)
	}

	createReq := httptest.NewRequest(http.MethodPost, "/datasets", bytes.NewBufferString(`{"name":" dataset-a ","type":" image "}`))
	createReq.Header.Set("Content-Type", "application/json")
	createRec := httptest.NewRecorder()
	handler.ServeHTTP(createRec, createReq)
	if createRec.Code != http.StatusCreated {
		t.Fatalf("unexpected create status: %d body=%s", createRec.Code, createRec.Body.String())
	}

	var created struct {
		ID   string `json:"id"`
		Name string `json:"name"`
		Type string `json:"type"`
	}
	if err := json.Unmarshal(createRec.Body.Bytes(), &created); err != nil {
		t.Fatalf("decode create response: %v", err)
	}
	if created.ID == "" || created.Name != "dataset-a" || created.Type != "image" {
		t.Fatalf("unexpected created dataset: %+v", created)
	}

	listReq := httptest.NewRequest(http.MethodGet, "/datasets", nil)
	listRec := httptest.NewRecorder()
	handler.ServeHTTP(listRec, listReq)
	if listRec.Code != http.StatusOK {
		t.Fatalf("unexpected list status: %d body=%s", listRec.Code, listRec.Body.String())
	}

	var listed struct {
		Items   []map[string]any `json:"items"`
		Total   int              `json:"total"`
		Offset  int              `json:"offset"`
		Limit   int              `json:"limit"`
		Size    int              `json:"size"`
		HasMore bool             `json:"has_more"`
	}
	if err := json.Unmarshal(listRec.Body.Bytes(), &listed); err != nil {
		t.Fatalf("decode list response: %v", err)
	}
	if listed.Total != 1 || listed.Offset != 0 || listed.Limit != 20 || listed.Size != 1 || listed.HasMore {
		t.Fatalf("unexpected list envelope: %+v", listed)
	}
	if len(listed.Items) != 1 || listed.Items[0]["id"] != created.ID {
		t.Fatalf("unexpected listed datasets: %+v", listed.Items)
	}

	getReq := httptest.NewRequest(http.MethodGet, "/datasets/"+created.ID, nil)
	getRec := httptest.NewRecorder()
	handler.ServeHTTP(getRec, getReq)
	if getRec.Code != http.StatusOK {
		t.Fatalf("unexpected get status: %d body=%s", getRec.Code, getRec.Body.String())
	}

	var loaded map[string]any
	if err := json.Unmarshal(getRec.Body.Bytes(), &loaded); err != nil {
		t.Fatalf("decode get response: %v", err)
	}
	if loaded["id"] != created.ID || loaded["name"] != "dataset-a" || loaded["type"] != "image" {
		t.Fatalf("unexpected loaded dataset: %+v", loaded)
	}

	updateReq := httptest.NewRequest(http.MethodPut, "/datasets/"+created.ID, bytes.NewBufferString(`{"name":" dataset-b ","type":" lidar "}`))
	updateReq.Header.Set("Content-Type", "application/json")
	updateRec := httptest.NewRecorder()
	handler.ServeHTTP(updateRec, updateReq)
	if updateRec.Code != http.StatusOK {
		t.Fatalf("unexpected update status: %d body=%s", updateRec.Code, updateRec.Body.String())
	}

	var updated map[string]any
	if err := json.Unmarshal(updateRec.Body.Bytes(), &updated); err != nil {
		t.Fatalf("decode update response: %v", err)
	}
	if updated["id"] != created.ID || updated["name"] != "dataset-b" || updated["type"] != "lidar" {
		t.Fatalf("unexpected updated dataset: %+v", updated)
	}

	deleteReq := httptest.NewRequest(http.MethodDelete, "/datasets/"+created.ID, nil)
	deleteRec := httptest.NewRecorder()
	handler.ServeHTTP(deleteRec, deleteReq)
	if deleteRec.Code != http.StatusNoContent {
		t.Fatalf("unexpected delete status: %d body=%s", deleteRec.Code, deleteRec.Body.String())
	}

	deleteAgainReq := httptest.NewRequest(http.MethodDelete, "/datasets/"+created.ID, nil)
	deleteAgainRec := httptest.NewRecorder()
	handler.ServeHTTP(deleteAgainRec, deleteAgainReq)
	if deleteAgainRec.Code != http.StatusNotFound {
		t.Fatalf("expected second delete to return 404, got status=%d body=%s", deleteAgainRec.Code, deleteAgainRec.Body.String())
	}

	getDeletedReq := httptest.NewRequest(http.MethodGet, "/datasets/"+created.ID, nil)
	getDeletedRec := httptest.NewRecorder()
	handler.ServeHTTP(getDeletedRec, getDeletedReq)
	if getDeletedRec.Code != http.StatusNotFound {
		t.Fatalf("expected deleted dataset to return 404, got status=%d body=%s", getDeletedRec.Code, getDeletedRec.Body.String())
	}
}

func TestListDatasetsSupportsPageLimitAndQuery(t *testing.T) {
	handler, err := newTestHTTPHandler()
	if err != nil {
		t.Fatalf("new http handler: %v", err)
	}

	for _, body := range []string{
		`{"name":"alpha","type":"image"}`,
		`{"name":"beta","type":"image"}`,
		`{"name":"alpine","type":"image"}`,
	} {
		req := httptest.NewRequest(http.MethodPost, "/datasets", bytes.NewBufferString(body))
		req.Header.Set("Content-Type", "application/json")
		rec := httptest.NewRecorder()
		handler.ServeHTTP(rec, req)
		if rec.Code != http.StatusCreated {
			t.Fatalf("seed dataset failed: status=%d body=%s", rec.Code, rec.Body.String())
		}
	}

	listReq := httptest.NewRequest(http.MethodGet, "/datasets?page=2&limit=1&q=%20alp%20", nil)
	listRec := httptest.NewRecorder()
	handler.ServeHTTP(listRec, listReq)
	if listRec.Code != http.StatusOK {
		t.Fatalf("unexpected list status: %d body=%s", listRec.Code, listRec.Body.String())
	}

	var listed struct {
		Items   []map[string]any `json:"items"`
		Total   int              `json:"total"`
		Offset  int              `json:"offset"`
		Limit   int              `json:"limit"`
		Size    int              `json:"size"`
		HasMore bool             `json:"has_more"`
	}
	if err := json.Unmarshal(listRec.Body.Bytes(), &listed); err != nil {
		t.Fatalf("decode list response: %v", err)
	}
	if listed.Total != 2 || listed.Offset != 1 || listed.Limit != 1 || listed.Size != 1 || listed.HasMore {
		t.Fatalf("unexpected list envelope: %+v", listed)
	}
	if len(listed.Items) != 1 || listed.Items[0]["name"] != "alpine" {
		t.Fatalf("unexpected filtered datasets: %+v", listed.Items)
	}
}

func TestDatasetPersistsAcrossPublicAPIInstances(t *testing.T) {
	t.Setenv("TESTCONTAINERS_RYUK_DISABLED", "true")

	ctx := context.Background()
	container, dsn := startPostgres(t, ctx)
	defer func() {
		_ = testcontainers.TerminateContainer(container)
	}()

	sqlDB, err := sql.Open("pgx", dsn)
	if err != nil {
		t.Fatalf("open sql db: %v", err)
	}
	defer sqlDB.Close()

	goose.SetDialect("postgres")
	if err := goose.Up(sqlDB, migrationsDir(t)); err != nil {
		t.Fatalf("run migrations: %v", err)
	}

	t.Setenv("DATABASE_DSN", dsn)
	t.Setenv("AUTH_TOKEN_SECRET", "test-secret")
	t.Setenv("AUTH_TOKEN_TTL", "1h")
	t.Setenv("PUBLIC_API_BIND", freeAddr(t))

	firstServer, _, err := appbootstrap.NewPublicAPI(ctx)
	if err != nil {
		t.Fatalf("new first public api: %v", err)
	}
	t.Cleanup(func() {
		_ = firstServer.Shutdown(context.Background())
	})

	createReq := httptest.NewRequest(http.MethodPost, "/datasets", bytes.NewBufferString(`{"name":"persisted-dataset","type":"image"}`))
	createReq.Header.Set("Content-Type", "application/json")
	createRec := httptest.NewRecorder()
	firstServer.Handler.ServeHTTP(createRec, createReq)
	if createRec.Code != http.StatusCreated {
		t.Fatalf("unexpected create status: %d body=%s", createRec.Code, createRec.Body.String())
	}

	var created struct {
		ID string `json:"id"`
	}
	if err := json.Unmarshal(createRec.Body.Bytes(), &created); err != nil {
		t.Fatalf("decode create response: %v", err)
	}
	if created.ID == "" {
		t.Fatalf("expected dataset id in create response: body=%s", createRec.Body.String())
	}

	secondServer, _, err := appbootstrap.NewPublicAPI(ctx)
	if err != nil {
		t.Fatalf("new second public api: %v", err)
	}
	t.Cleanup(func() {
		_ = secondServer.Shutdown(context.Background())
	})

	getReq := httptest.NewRequest(http.MethodGet, "/datasets/"+created.ID, nil)
	getRec := httptest.NewRecorder()
	secondServer.Handler.ServeHTTP(getRec, getReq)
	if getRec.Code != http.StatusOK {
		t.Fatalf("expected persisted dataset on second server, got status=%d body=%s", getRec.Code, getRec.Body.String())
	}
}

func TestDeleteDatasetInvalidatesDatasetAndSampleAssetReferences(t *testing.T) {
	t.Setenv("TESTCONTAINERS_RYUK_DISABLED", "true")

	ctx := context.Background()
	container, dsn := startPostgres(t, ctx)
	defer func() {
		_ = testcontainers.TerminateContainer(container)
	}()

	sqlDB, err := sql.Open("pgx", dsn)
	if err != nil {
		t.Fatalf("open sql db: %v", err)
	}
	defer sqlDB.Close()

	goose.SetDialect("postgres")
	if err := goose.Up(sqlDB, migrationsDir(t)); err != nil {
		t.Fatalf("run migrations: %v", err)
	}

	pool, err := appdb.NewPool(ctx, dsn)
	if err != nil {
		t.Fatalf("create pool: %v", err)
	}
	defer pool.Close()

	datasetRepo := datasetrepo.NewDatasetRepo(pool)
	sampleRepo := annotationrepo.NewSampleRepo(pool)
	assetStore := assetrepo.NewAssetRepo(pool)
	referenceRepo := assetrepo.NewAssetReferenceRepo(pool)

	datasetRow, err := datasetRepo.Create(ctx, datasetrepo.CreateDatasetParams{
		Name: "dataset-with-assets",
		Type: "image",
	})
	if err != nil {
		t.Fatalf("create dataset: %v", err)
	}

	sampleRow, err := sampleRepo.Create(ctx, annotationrepo.CreateSampleParams{
		DatasetID: datasetRow.ID,
		Name:      "sample-a",
		Meta:      []byte(`{}`),
	})
	if err != nil {
		t.Fatalf("create sample: %v", err)
	}

	datasetAsset, err := createReadyAssetForDatasetDeleteTest(ctx, assetStore, "assets/dataset-attachment")
	if err != nil {
		t.Fatalf("create dataset asset: %v", err)
	}
	if _, err := referenceRepo.CreateDurable(ctx, assetrepo.CreateAssetReferenceParams{
		AssetID:   datasetAsset.ID,
		OwnerType: "dataset",
		OwnerID:   datasetRow.ID,
		Role:      "attachment",
		Lifecycle: "durable",
		IsPrimary: false,
	}); err != nil {
		t.Fatalf("create dataset reference: %v", err)
	}

	sampleAsset, err := createReadyAssetForDatasetDeleteTest(ctx, assetStore, "assets/sample-attachment")
	if err != nil {
		t.Fatalf("create sample asset: %v", err)
	}
	if _, err := referenceRepo.CreateDurable(ctx, assetrepo.CreateAssetReferenceParams{
		AssetID:   sampleAsset.ID,
		OwnerType: "sample",
		OwnerID:   sampleRow.ID,
		Role:      "attachment",
		Lifecycle: "durable",
		IsPrimary: false,
	}); err != nil {
		t.Fatalf("create sample reference: %v", err)
	}

	t.Setenv("DATABASE_DSN", dsn)
	t.Setenv("AUTH_TOKEN_SECRET", "test-secret")
	t.Setenv("AUTH_TOKEN_TTL", "1h")
	t.Setenv("PUBLIC_API_BIND", freeAddr(t))
	t.Setenv("MINIO_ENDPOINT", "")
	t.Setenv("MINIO_ACCESS_KEY", "")
	t.Setenv("MINIO_SECRET_KEY", "")
	t.Setenv("MINIO_BUCKET_NAME", "")

	server, _, err := appbootstrap.NewPublicAPI(ctx)
	if err != nil {
		t.Fatalf("new public api: %v", err)
	}
	defer func() {
		_ = server.Shutdown(context.Background())
	}()

	deleteReq := httptest.NewRequest(http.MethodDelete, "/datasets/"+datasetRow.ID.String(), nil)
	deleteRec := httptest.NewRecorder()
	server.Handler.ServeHTTP(deleteRec, deleteReq)
	if deleteRec.Code != http.StatusNoContent {
		t.Fatalf("unexpected delete status: %d body=%s", deleteRec.Code, deleteRec.Body.String())
	}

	assertAssetReferenceDeleted(t, sqlDB, "dataset", datasetRow.ID)
	assertAssetReferenceDeleted(t, sqlDB, "sample", sampleRow.ID)
	assertAssetOrphaned(t, assetStore, datasetAsset.ID)
	assertAssetOrphaned(t, assetStore, sampleAsset.ID)
}

func TestDeleteDatasetMissingDatasetDoesNotTouchAssetReferences(t *testing.T) {
	t.Setenv("TESTCONTAINERS_RYUK_DISABLED", "true")

	ctx := context.Background()
	container, dsn := startPostgres(t, ctx)
	defer func() {
		_ = testcontainers.TerminateContainer(container)
	}()

	sqlDB, err := sql.Open("pgx", dsn)
	if err != nil {
		t.Fatalf("open sql db: %v", err)
	}
	defer sqlDB.Close()

	goose.SetDialect("postgres")
	if err := goose.Up(sqlDB, migrationsDir(t)); err != nil {
		t.Fatalf("run migrations: %v", err)
	}

	pool, err := appdb.NewPool(ctx, dsn)
	if err != nil {
		t.Fatalf("create pool: %v", err)
	}
	defer pool.Close()

	assetStore := assetrepo.NewAssetRepo(pool)
	referenceRepo := assetrepo.NewAssetReferenceRepo(pool)

	missingDatasetID := uuid.New()
	asset, err := createReadyAssetForDatasetDeleteTest(ctx, assetStore, "assets/missing-dataset-owner")
	if err != nil {
		t.Fatalf("create ready asset: %v", err)
	}
	if _, err := referenceRepo.CreateDurable(ctx, assetrepo.CreateAssetReferenceParams{
		AssetID:   asset.ID,
		OwnerType: "dataset",
		OwnerID:   missingDatasetID,
		Role:      "attachment",
		Lifecycle: "durable",
		IsPrimary: false,
	}); err != nil {
		t.Fatalf("create durable reference: %v", err)
	}

	t.Setenv("DATABASE_DSN", dsn)
	t.Setenv("AUTH_TOKEN_SECRET", "test-secret")
	t.Setenv("AUTH_TOKEN_TTL", "1h")
	t.Setenv("PUBLIC_API_BIND", freeAddr(t))
	t.Setenv("MINIO_ENDPOINT", "")
	t.Setenv("MINIO_ACCESS_KEY", "")
	t.Setenv("MINIO_SECRET_KEY", "")
	t.Setenv("MINIO_BUCKET_NAME", "")

	server, _, err := appbootstrap.NewPublicAPI(ctx)
	if err != nil {
		t.Fatalf("new public api: %v", err)
	}
	defer func() {
		_ = server.Shutdown(context.Background())
	}()

	deleteReq := httptest.NewRequest(http.MethodDelete, "/datasets/"+missingDatasetID.String(), nil)
	deleteRec := httptest.NewRecorder()
	server.Handler.ServeHTTP(deleteRec, deleteReq)
	if deleteRec.Code != http.StatusNotFound {
		t.Fatalf("expected delete missing dataset to return 404, got status=%d body=%s", deleteRec.Code, deleteRec.Body.String())
	}

	assertAssetReferenceStillActive(t, sqlDB, "dataset", missingDatasetID)
}

func TestDeleteDatasetKeepsAssetLiveWhenOtherOwnerReferencesRemain(t *testing.T) {
	t.Setenv("TESTCONTAINERS_RYUK_DISABLED", "true")

	ctx := context.Background()
	container, dsn := startPostgres(t, ctx)
	defer func() {
		_ = testcontainers.TerminateContainer(container)
	}()

	sqlDB, err := sql.Open("pgx", dsn)
	if err != nil {
		t.Fatalf("open sql db: %v", err)
	}
	defer sqlDB.Close()

	goose.SetDialect("postgres")
	if err := goose.Up(sqlDB, migrationsDir(t)); err != nil {
		t.Fatalf("run migrations: %v", err)
	}

	pool, err := appdb.NewPool(ctx, dsn)
	if err != nil {
		t.Fatalf("create pool: %v", err)
	}
	defer pool.Close()

	datasetRepo := datasetrepo.NewDatasetRepo(pool)
	projectRepo := projectrepo.NewProjectRepo(pool)
	assetStore := assetrepo.NewAssetRepo(pool)
	referenceRepo := assetrepo.NewAssetReferenceRepo(pool)

	datasetRow, err := datasetRepo.Create(ctx, datasetrepo.CreateDatasetParams{
		Name: "dataset-shared-asset",
		Type: "image",
	})
	if err != nil {
		t.Fatalf("create dataset: %v", err)
	}

	projectRow, err := projectRepo.CreateProject(ctx, projectrepo.CreateProjectParams{Name: "project-a"})
	if err != nil {
		t.Fatalf("create project: %v", err)
	}

	asset, err := createReadyAssetForDatasetDeleteTest(ctx, assetStore, "assets/shared")
	if err != nil {
		t.Fatalf("create ready asset: %v", err)
	}
	if _, err := referenceRepo.CreateDurable(ctx, assetrepo.CreateAssetReferenceParams{
		AssetID:   asset.ID,
		OwnerType: "dataset",
		OwnerID:   datasetRow.ID,
		Role:      "attachment",
		Lifecycle: "durable",
		IsPrimary: false,
	}); err != nil {
		t.Fatalf("create dataset reference: %v", err)
	}
	if _, err := referenceRepo.CreateDurable(ctx, assetrepo.CreateAssetReferenceParams{
		AssetID:   asset.ID,
		OwnerType: "project",
		OwnerID:   projectRow.ID,
		Role:      "attachment",
		Lifecycle: "durable",
		IsPrimary: false,
	}); err != nil {
		t.Fatalf("create project reference: %v", err)
	}

	t.Setenv("DATABASE_DSN", dsn)
	t.Setenv("AUTH_TOKEN_SECRET", "test-secret")
	t.Setenv("AUTH_TOKEN_TTL", "1h")
	t.Setenv("PUBLIC_API_BIND", freeAddr(t))
	t.Setenv("MINIO_ENDPOINT", "")
	t.Setenv("MINIO_ACCESS_KEY", "")
	t.Setenv("MINIO_SECRET_KEY", "")
	t.Setenv("MINIO_BUCKET_NAME", "")

	server, _, err := appbootstrap.NewPublicAPI(ctx)
	if err != nil {
		t.Fatalf("new public api: %v", err)
	}
	defer func() {
		_ = server.Shutdown(context.Background())
	}()

	deleteReq := httptest.NewRequest(http.MethodDelete, "/datasets/"+datasetRow.ID.String(), nil)
	deleteRec := httptest.NewRecorder()
	server.Handler.ServeHTTP(deleteRec, deleteReq)
	if deleteRec.Code != http.StatusNoContent {
		t.Fatalf("unexpected delete status: %d body=%s", deleteRec.Code, deleteRec.Body.String())
	}

	assertAssetReferenceDeleted(t, sqlDB, "dataset", datasetRow.ID)
	assertAssetReferenceStillActive(t, sqlDB, "project", projectRow.ID)
	assertAssetNotOrphaned(t, assetStore, asset.ID)
}

func TestDeleteDatasetSampleInvalidatesSampleAssetReferences(t *testing.T) {
	t.Setenv("TESTCONTAINERS_RYUK_DISABLED", "true")

	ctx := context.Background()
	container, dsn := startPostgres(t, ctx)
	defer func() {
		_ = testcontainers.TerminateContainer(container)
	}()

	sqlDB, err := sql.Open("pgx", dsn)
	if err != nil {
		t.Fatalf("open sql db: %v", err)
	}
	defer sqlDB.Close()

	goose.SetDialect("postgres")
	if err := goose.Up(sqlDB, migrationsDir(t)); err != nil {
		t.Fatalf("run migrations: %v", err)
	}

	pool, err := appdb.NewPool(ctx, dsn)
	if err != nil {
		t.Fatalf("create pool: %v", err)
	}
	defer pool.Close()

	datasetRepo := datasetrepo.NewDatasetRepo(pool)
	projectRepo := projectrepo.NewProjectRepo(pool)
	sampleRepo := annotationrepo.NewSampleRepo(pool)
	annotationRepo := annotationrepo.NewAnnotationRepo(pool)
	matchRepo := importrepo.NewSampleMatchRefRepo(pool)
	assetStore := assetrepo.NewAssetRepo(pool)
	referenceRepo := assetrepo.NewAssetReferenceRepo(pool)

	datasetRow, err := datasetRepo.Create(ctx, datasetrepo.CreateDatasetParams{
		Name: "dataset-with-sample-delete",
		Type: "image",
	})
	if err != nil {
		t.Fatalf("create dataset: %v", err)
	}

	projectRow, err := projectRepo.CreateProject(ctx, projectrepo.CreateProjectParams{Name: "project-a"})
	if err != nil {
		t.Fatalf("create project: %v", err)
	}
	if _, err := sqlDB.ExecContext(ctx, `insert into project_dataset (project_id, dataset_id) values ($1, $2)`, projectRow.ID, datasetRow.ID); err != nil {
		t.Fatalf("seed project dataset link: %v", err)
	}

	sampleRow, err := sampleRepo.Create(ctx, annotationrepo.CreateSampleParams{
		DatasetID: datasetRow.ID,
		Name:      "sample-a",
		Meta:      []byte(`{}`),
	})
	if err != nil {
		t.Fatalf("create sample: %v", err)
	}

	if _, err := annotationRepo.Create(ctx, annotationrepo.CreateAnnotationParams{
		ProjectID:      projectRow.ID,
		SampleID:       sampleRow.ID,
		GroupID:        "group-a",
		LabelID:        "car",
		View:           "rgb",
		AnnotationType: "rect",
		Geometry:       []byte(`{"x":1,"y":2,"w":3,"h":4}`),
		Attrs:          []byte(`{}`),
		Source:         "manual",
		IsGenerated:    false,
	}); err != nil {
		t.Fatalf("create annotation: %v", err)
	}
	if _, err := matchRepo.Put(ctx, importrepo.PutSampleMatchRefParams{
		DatasetID: datasetRow.ID,
		SampleID:  sampleRow.ID,
		RefType:   "sample_name",
		RefValue:  sampleRow.Name,
		IsPrimary: true,
	}); err != nil {
		t.Fatalf("put sample match ref: %v", err)
	}

	sampleAsset, err := createReadyAssetForDatasetDeleteTest(ctx, assetStore, "assets/sample-primary")
	if err != nil {
		t.Fatalf("create sample asset: %v", err)
	}
	if _, err := referenceRepo.CreateDurable(ctx, assetrepo.CreateAssetReferenceParams{
		AssetID:   sampleAsset.ID,
		OwnerType: "sample",
		OwnerID:   sampleRow.ID,
		Role:      "primary",
		Lifecycle: "durable",
		IsPrimary: true,
	}); err != nil {
		t.Fatalf("create sample reference: %v", err)
	}

	t.Setenv("DATABASE_DSN", dsn)
	t.Setenv("AUTH_TOKEN_SECRET", "test-secret")
	t.Setenv("AUTH_TOKEN_TTL", "1h")
	t.Setenv("PUBLIC_API_BIND", freeAddr(t))
	t.Setenv("MINIO_ENDPOINT", "")
	t.Setenv("MINIO_ACCESS_KEY", "")
	t.Setenv("MINIO_SECRET_KEY", "")
	t.Setenv("MINIO_BUCKET_NAME", "")

	server, _, err := appbootstrap.NewPublicAPI(ctx)
	if err != nil {
		t.Fatalf("new public api: %v", err)
	}
	defer func() {
		_ = server.Shutdown(context.Background())
	}()

	deleteReq := httptest.NewRequest(http.MethodDelete, "/datasets/"+datasetRow.ID.String()+"/samples/"+sampleRow.ID.String(), nil)
	deleteRec := httptest.NewRecorder()
	server.Handler.ServeHTTP(deleteRec, deleteReq)
	if deleteRec.Code != http.StatusNoContent {
		t.Fatalf("unexpected delete status: %d body=%s", deleteRec.Code, deleteRec.Body.String())
	}

	assertAssetReferenceDeleted(t, sqlDB, "sample", sampleRow.ID)
	assertAssetOrphaned(t, assetStore, sampleAsset.ID)
	assertSampleDeleted(t, sampleRepo, sampleRow.ID)
	assertAnnotationCountForSample(t, sqlDB, sampleRow.ID, 0)
	assertSampleMatchRefCountForSample(t, sqlDB, sampleRow.ID, 0)
}

func TestDeleteDatasetSampleKeepsAssetLiveWhenOtherOwnerReferencesRemain(t *testing.T) {
	t.Setenv("TESTCONTAINERS_RYUK_DISABLED", "true")

	ctx := context.Background()
	container, dsn := startPostgres(t, ctx)
	defer func() {
		_ = testcontainers.TerminateContainer(container)
	}()

	sqlDB, err := sql.Open("pgx", dsn)
	if err != nil {
		t.Fatalf("open sql db: %v", err)
	}
	defer sqlDB.Close()

	goose.SetDialect("postgres")
	if err := goose.Up(sqlDB, migrationsDir(t)); err != nil {
		t.Fatalf("run migrations: %v", err)
	}

	pool, err := appdb.NewPool(ctx, dsn)
	if err != nil {
		t.Fatalf("create pool: %v", err)
	}
	defer pool.Close()

	datasetRepo := datasetrepo.NewDatasetRepo(pool)
	projectRepo := projectrepo.NewProjectRepo(pool)
	sampleRepo := annotationrepo.NewSampleRepo(pool)
	assetStore := assetrepo.NewAssetRepo(pool)
	referenceRepo := assetrepo.NewAssetReferenceRepo(pool)

	datasetRow, err := datasetRepo.Create(ctx, datasetrepo.CreateDatasetParams{
		Name: "dataset-shared-sample-asset",
		Type: "image",
	})
	if err != nil {
		t.Fatalf("create dataset: %v", err)
	}

	sampleRow, err := sampleRepo.Create(ctx, annotationrepo.CreateSampleParams{
		DatasetID: datasetRow.ID,
		Name:      "sample-a",
		Meta:      []byte(`{}`),
	})
	if err != nil {
		t.Fatalf("create sample: %v", err)
	}

	projectRow, err := projectRepo.CreateProject(ctx, projectrepo.CreateProjectParams{Name: "project-a"})
	if err != nil {
		t.Fatalf("create project: %v", err)
	}

	asset, err := createReadyAssetForDatasetDeleteTest(ctx, assetStore, "assets/shared-sample")
	if err != nil {
		t.Fatalf("create ready asset: %v", err)
	}
	if _, err := referenceRepo.CreateDurable(ctx, assetrepo.CreateAssetReferenceParams{
		AssetID:   asset.ID,
		OwnerType: "sample",
		OwnerID:   sampleRow.ID,
		Role:      "attachment",
		Lifecycle: "durable",
		IsPrimary: false,
	}); err != nil {
		t.Fatalf("create sample reference: %v", err)
	}
	if _, err := referenceRepo.CreateDurable(ctx, assetrepo.CreateAssetReferenceParams{
		AssetID:   asset.ID,
		OwnerType: "project",
		OwnerID:   projectRow.ID,
		Role:      "attachment",
		Lifecycle: "durable",
		IsPrimary: false,
	}); err != nil {
		t.Fatalf("create project reference: %v", err)
	}

	t.Setenv("DATABASE_DSN", dsn)
	t.Setenv("AUTH_TOKEN_SECRET", "test-secret")
	t.Setenv("AUTH_TOKEN_TTL", "1h")
	t.Setenv("PUBLIC_API_BIND", freeAddr(t))
	t.Setenv("MINIO_ENDPOINT", "")
	t.Setenv("MINIO_ACCESS_KEY", "")
	t.Setenv("MINIO_SECRET_KEY", "")
	t.Setenv("MINIO_BUCKET_NAME", "")

	server, _, err := appbootstrap.NewPublicAPI(ctx)
	if err != nil {
		t.Fatalf("new public api: %v", err)
	}
	defer func() {
		_ = server.Shutdown(context.Background())
	}()

	deleteReq := httptest.NewRequest(http.MethodDelete, "/datasets/"+datasetRow.ID.String()+"/samples/"+sampleRow.ID.String(), nil)
	deleteRec := httptest.NewRecorder()
	server.Handler.ServeHTTP(deleteRec, deleteReq)
	if deleteRec.Code != http.StatusNoContent {
		t.Fatalf("unexpected delete status: %d body=%s", deleteRec.Code, deleteRec.Body.String())
	}

	assertAssetReferenceDeleted(t, sqlDB, "sample", sampleRow.ID)
	assertAssetReferenceStillActive(t, sqlDB, "project", projectRow.ID)
	assertAssetNotOrphaned(t, assetStore, asset.ID)
	assertSampleDeleted(t, sampleRepo, sampleRow.ID)
}

func TestDeleteDatasetSampleRejectsDatasetSampleMismatch(t *testing.T) {
	t.Setenv("TESTCONTAINERS_RYUK_DISABLED", "true")

	ctx := context.Background()
	container, dsn := startPostgres(t, ctx)
	defer func() {
		_ = testcontainers.TerminateContainer(container)
	}()

	sqlDB, err := sql.Open("pgx", dsn)
	if err != nil {
		t.Fatalf("open sql db: %v", err)
	}
	defer sqlDB.Close()

	goose.SetDialect("postgres")
	if err := goose.Up(sqlDB, migrationsDir(t)); err != nil {
		t.Fatalf("run migrations: %v", err)
	}

	pool, err := appdb.NewPool(ctx, dsn)
	if err != nil {
		t.Fatalf("create pool: %v", err)
	}
	defer pool.Close()

	datasetRepo := datasetrepo.NewDatasetRepo(pool)
	sampleRepo := annotationrepo.NewSampleRepo(pool)
	assetStore := assetrepo.NewAssetRepo(pool)
	referenceRepo := assetrepo.NewAssetReferenceRepo(pool)

	datasetA, err := datasetRepo.Create(ctx, datasetrepo.CreateDatasetParams{Name: "dataset-a", Type: "image"})
	if err != nil {
		t.Fatalf("create dataset a: %v", err)
	}
	datasetB, err := datasetRepo.Create(ctx, datasetrepo.CreateDatasetParams{Name: "dataset-b", Type: "image"})
	if err != nil {
		t.Fatalf("create dataset b: %v", err)
	}

	sampleRow, err := sampleRepo.Create(ctx, annotationrepo.CreateSampleParams{
		DatasetID: datasetA.ID,
		Name:      "sample-a",
		Meta:      []byte(`{}`),
	})
	if err != nil {
		t.Fatalf("create sample: %v", err)
	}

	asset, err := createReadyAssetForDatasetDeleteTest(ctx, assetStore, "assets/mismatch")
	if err != nil {
		t.Fatalf("create ready asset: %v", err)
	}
	if _, err := referenceRepo.CreateDurable(ctx, assetrepo.CreateAssetReferenceParams{
		AssetID:   asset.ID,
		OwnerType: "sample",
		OwnerID:   sampleRow.ID,
		Role:      "attachment",
		Lifecycle: "durable",
		IsPrimary: false,
	}); err != nil {
		t.Fatalf("create sample reference: %v", err)
	}

	t.Setenv("DATABASE_DSN", dsn)
	t.Setenv("AUTH_TOKEN_SECRET", "test-secret")
	t.Setenv("AUTH_TOKEN_TTL", "1h")
	t.Setenv("PUBLIC_API_BIND", freeAddr(t))
	t.Setenv("MINIO_ENDPOINT", "")
	t.Setenv("MINIO_ACCESS_KEY", "")
	t.Setenv("MINIO_SECRET_KEY", "")
	t.Setenv("MINIO_BUCKET_NAME", "")

	server, _, err := appbootstrap.NewPublicAPI(ctx)
	if err != nil {
		t.Fatalf("new public api: %v", err)
	}
	defer func() {
		_ = server.Shutdown(context.Background())
	}()

	deleteReq := httptest.NewRequest(http.MethodDelete, "/datasets/"+datasetB.ID.String()+"/samples/"+sampleRow.ID.String(), nil)
	deleteRec := httptest.NewRecorder()
	server.Handler.ServeHTTP(deleteRec, deleteReq)
	if deleteRec.Code != http.StatusBadRequest {
		t.Fatalf("expected delete mismatch to return 400, got status=%d body=%s", deleteRec.Code, deleteRec.Body.String())
	}

	assertAssetReferenceStillActive(t, sqlDB, "sample", sampleRow.ID)
	assertAssetNotOrphaned(t, assetStore, asset.ID)
}

func TestDeleteDatasetSampleReturnsNotFoundForMissingSample(t *testing.T) {
	t.Setenv("TESTCONTAINERS_RYUK_DISABLED", "true")

	ctx := context.Background()
	container, dsn := startPostgres(t, ctx)
	defer func() {
		_ = testcontainers.TerminateContainer(container)
	}()

	sqlDB, err := sql.Open("pgx", dsn)
	if err != nil {
		t.Fatalf("open sql db: %v", err)
	}
	defer sqlDB.Close()

	goose.SetDialect("postgres")
	if err := goose.Up(sqlDB, migrationsDir(t)); err != nil {
		t.Fatalf("run migrations: %v", err)
	}

	pool, err := appdb.NewPool(ctx, dsn)
	if err != nil {
		t.Fatalf("create pool: %v", err)
	}
	defer pool.Close()

	datasetRepo := datasetrepo.NewDatasetRepo(pool)
	assetStore := assetrepo.NewAssetRepo(pool)
	referenceRepo := assetrepo.NewAssetReferenceRepo(pool)

	datasetRow, err := datasetRepo.Create(ctx, datasetrepo.CreateDatasetParams{Name: "dataset-a", Type: "image"})
	if err != nil {
		t.Fatalf("create dataset: %v", err)
	}

	missingSampleID := uuid.New()
	asset, err := createReadyAssetForDatasetDeleteTest(ctx, assetStore, "assets/missing-sample")
	if err != nil {
		t.Fatalf("create ready asset: %v", err)
	}
	if _, err := referenceRepo.CreateDurable(ctx, assetrepo.CreateAssetReferenceParams{
		AssetID:   asset.ID,
		OwnerType: "sample",
		OwnerID:   missingSampleID,
		Role:      "attachment",
		Lifecycle: "durable",
		IsPrimary: false,
	}); err != nil {
		t.Fatalf("create sample reference: %v", err)
	}

	t.Setenv("DATABASE_DSN", dsn)
	t.Setenv("AUTH_TOKEN_SECRET", "test-secret")
	t.Setenv("AUTH_TOKEN_TTL", "1h")
	t.Setenv("PUBLIC_API_BIND", freeAddr(t))
	t.Setenv("MINIO_ENDPOINT", "")
	t.Setenv("MINIO_ACCESS_KEY", "")
	t.Setenv("MINIO_SECRET_KEY", "")
	t.Setenv("MINIO_BUCKET_NAME", "")

	server, _, err := appbootstrap.NewPublicAPI(ctx)
	if err != nil {
		t.Fatalf("new public api: %v", err)
	}
	defer func() {
		_ = server.Shutdown(context.Background())
	}()

	deleteReq := httptest.NewRequest(http.MethodDelete, "/datasets/"+datasetRow.ID.String()+"/samples/"+missingSampleID.String(), nil)
	deleteRec := httptest.NewRecorder()
	server.Handler.ServeHTTP(deleteRec, deleteReq)
	if deleteRec.Code != http.StatusNotFound {
		t.Fatalf("expected delete missing sample to return 404, got status=%d body=%s", deleteRec.Code, deleteRec.Body.String())
	}

	assertAssetReferenceStillActive(t, sqlDB, "sample", missingSampleID)
	assertAssetNotOrphaned(t, assetStore, asset.ID)
}

func TestGetDatasetRejectsInvalidDatasetID(t *testing.T) {
	handler, err := newTestHTTPHandler()
	if err != nil {
		t.Fatalf("new http handler: %v", err)
	}

	req := httptest.NewRequest(http.MethodGet, "/datasets/not-a-uuid", nil)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)
	if rec.Code != http.StatusBadRequest {
		t.Fatalf("expected invalid dataset_id to return 400, got status=%d body=%s", rec.Code, rec.Body.String())
	}
}

func TestDeleteDatasetRejectsInvalidDatasetID(t *testing.T) {
	handler, err := newTestHTTPHandler()
	if err != nil {
		t.Fatalf("new http handler: %v", err)
	}

	req := httptest.NewRequest(http.MethodDelete, "/datasets/not-a-uuid", nil)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)
	if rec.Code != http.StatusBadRequest {
		t.Fatalf("expected invalid dataset_id to return 400, got status=%d body=%s", rec.Code, rec.Body.String())
	}
}

func TestDeleteDatasetDoesNotRequirePreGet(t *testing.T) {
	handler := datasetapi.NewHandlers(deleteOnlyStore{
		deleteResult: true,
	})

	res, err := handler.DeleteDataset(context.Background(), openapi.DeleteDatasetParams{
		DatasetID: uuid.NewString(),
	})
	if err != nil {
		t.Fatalf("delete dataset: %v", err)
	}
	if _, ok := res.(*openapi.DeleteDatasetNoContent); !ok {
		t.Fatalf("expected no-content delete response, got %T", res)
	}
}

func TestDeleteDatasetReturnsNotFoundWhenDeleteReportsNoRows(t *testing.T) {
	handler := datasetapi.NewHandlers(deleteOnlyStore{
		deleteResult: false,
	})

	res, err := handler.DeleteDataset(context.Background(), openapi.DeleteDatasetParams{
		DatasetID: uuid.NewString(),
	})
	if err != nil {
		t.Fatalf("delete dataset: %v", err)
	}
	if _, ok := res.(*openapi.DeleteDatasetNotFound); !ok {
		t.Fatalf("expected not-found delete response, got %T", res)
	}
}

func newTestHTTPHandler() (http.Handler, error) {
	return systemapi.NewHTTPHandler(systemapi.Dependencies{
		Authenticator:       accessapp.NewAuthenticator("test-secret", time.Hour),
		ClaimsStore:         fakeAccessStore{},
		DatasetStore:        datasetapp.NewMemoryStore(),
		ProjectStore:        projectapp.NewMemoryStore(),
		RuntimeStore:        runtimequeries.NewMemoryAdminStore(),
		RuntimeTaskCanceler: fakeRuntimeTaskCanceler{},
		AnnotationSamples:   fakeAnnotationSampleStore{},
		AnnotationDatasets:  fakeAnnotationDatasetStore{},
		AnnotationStore:     fakeAnnotationStore{},
	})
}

type fakeRuntimeTaskCanceler struct{}

func (fakeRuntimeTaskCanceler) Handle(context.Context, runtimecommands.CancelTaskCommand) (*runtimecommands.TaskRecord, error) {
	return &runtimecommands.TaskRecord{}, nil
}

type fakeAnnotationSampleStore struct{}

func (fakeAnnotationSampleStore) Get(context.Context, uuid.UUID) (*annotationrepo.Sample, error) {
	return nil, nil
}

type fakeAnnotationDatasetStore struct{}

func (fakeAnnotationDatasetStore) Get(context.Context, uuid.UUID) (*datasetrepo.Dataset, error) {
	return nil, nil
}

type fakeAnnotationStore struct{}

func (fakeAnnotationStore) Create(context.Context, annotationrepo.CreateAnnotationParams) (*annotationrepo.Annotation, error) {
	return nil, nil
}

func (fakeAnnotationStore) ListByProjectSample(context.Context, uuid.UUID, uuid.UUID) ([]annotationrepo.Annotation, error) {
	return nil, nil
}

type fakeAccessStore struct{}

func (fakeAccessStore) LoadClaimsByUserID(context.Context, string) (*accessapp.ClaimsSnapshot, error) {
	return nil, nil
}

func (fakeAccessStore) LoadClaimsByPrincipalID(context.Context, uuid.UUID) (*accessapp.ClaimsSnapshot, error) {
	return nil, nil
}

type deleteOnlyStore struct {
	deleteResult bool
}

func (deleteOnlyStore) Create(context.Context, datasetrepo.CreateDatasetParams) (*datasetrepo.Dataset, error) {
	return nil, nil
}

func (deleteOnlyStore) Get(context.Context, uuid.UUID) (*datasetrepo.Dataset, error) {
	return nil, errors.New("Get should not be called")
}

func (deleteOnlyStore) List(context.Context, datasetrepo.ListDatasetsParams) (*datasetrepo.DatasetPage, error) {
	return nil, nil
}

func (deleteOnlyStore) Update(context.Context, datasetrepo.UpdateDatasetParams) (*datasetrepo.Dataset, error) {
	return nil, nil
}

func (s deleteOnlyStore) Delete(context.Context, uuid.UUID) (bool, error) {
	return s.deleteResult, nil
}

func freeAddr(t *testing.T) string {
	t.Helper()

	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("listen free addr: %v", err)
	}
	defer ln.Close()
	return ln.Addr().String()
}

func startPostgres(t *testing.T, ctx context.Context) (*postgres.PostgresContainer, string) {
	t.Helper()

	container, err := postgres.Run(
		ctx,
		postgresImageRef(),
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

func migrationsDir(t *testing.T) string {
	t.Helper()

	_, file, _, ok := runtime.Caller(0)
	if !ok {
		t.Fatal("resolve caller")
	}

	return filepath.Join(filepath.Dir(file), "..", "..", "..", "..", "db", "migrations")
}

func postgresImageRef() string {
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

func createReadyAssetForDatasetDeleteTest(ctx context.Context, repo *assetrepo.AssetRepo, objectKey string) (*assetrepo.Asset, error) {
	asset, err := repo.CreatePending(ctx, assetrepo.CreatePendingParams{
		Kind:           "image",
		StorageBackend: "minio",
		Bucket:         "assets",
		ObjectKey:      objectKey,
		ContentType:    "image/png",
		Metadata:       []byte(`{}`),
	})
	if err != nil {
		return nil, err
	}

	return repo.MarkReady(ctx, assetrepo.MarkReadyParams{
		ID:          asset.ID,
		SizeBytes:   128,
		Sha256Hex:   stringPtr("deadbeef"),
		ContentType: "image/png",
	})
}

func assertAssetReferenceDeleted(t *testing.T, db *sql.DB, ownerType string, ownerID uuid.UUID) {
	t.Helper()

	var deletedAt sql.NullTime
	err := db.QueryRow(`
select deleted_at
from asset_reference
where owner_type = $1
  and owner_id = $2
`, ownerType, ownerID).Scan(&deletedAt)
	if err != nil {
		t.Fatalf("query deleted_at for %s owner %s: %v", ownerType, ownerID, err)
	}
	if !deletedAt.Valid {
		t.Fatalf("expected deleted_at to be populated for %s owner %s", ownerType, ownerID)
	}
}

func assertAssetReferenceStillActive(t *testing.T, db *sql.DB, ownerType string, ownerID uuid.UUID) {
	t.Helper()

	var deletedAt sql.NullTime
	err := db.QueryRow(`
select deleted_at
from asset_reference
where owner_type = $1
  and owner_id = $2
`, ownerType, ownerID).Scan(&deletedAt)
	if err != nil {
		t.Fatalf("query deleted_at for %s owner %s: %v", ownerType, ownerID, err)
	}
	if deletedAt.Valid {
		t.Fatalf("expected reference for %s owner %s to remain active", ownerType, ownerID)
	}
}

func assertAssetOrphaned(t *testing.T, repo *assetrepo.AssetRepo, assetID uuid.UUID) {
	t.Helper()

	asset, err := repo.Get(context.Background(), assetID)
	if err != nil {
		t.Fatalf("get asset %s: %v", assetID, err)
	}
	if asset == nil || asset.OrphanedAt == nil {
		t.Fatalf("expected asset %s to be orphaned, got %+v", assetID, asset)
	}
}

func assertAssetNotOrphaned(t *testing.T, repo *assetrepo.AssetRepo, assetID uuid.UUID) {
	t.Helper()

	asset, err := repo.Get(context.Background(), assetID)
	if err != nil {
		t.Fatalf("get asset %s: %v", assetID, err)
	}
	if asset == nil || asset.OrphanedAt != nil {
		t.Fatalf("expected asset %s to remain non-orphaned, got %+v", assetID, asset)
	}
}

func assertSampleDeleted(t *testing.T, repo *annotationrepo.SampleRepo, sampleID uuid.UUID) {
	t.Helper()

	sample, err := repo.Get(context.Background(), sampleID)
	if err != nil {
		t.Fatalf("get sample %s: %v", sampleID, err)
	}
	if sample != nil {
		t.Fatalf("expected sample %s to be deleted, got %+v", sampleID, sample)
	}
}

func assertAnnotationCountForSample(t *testing.T, db *sql.DB, sampleID uuid.UUID, want int) {
	t.Helper()

	var got int
	if err := db.QueryRowContext(context.Background(), `select count(*) from annotation where sample_id = $1`, sampleID).Scan(&got); err != nil {
		t.Fatalf("count annotations for sample %s: %v", sampleID, err)
	}
	if got != want {
		t.Fatalf("annotation count for sample %s got %d want %d", sampleID, got, want)
	}
}

func assertSampleMatchRefCountForSample(t *testing.T, db *sql.DB, sampleID uuid.UUID, want int) {
	t.Helper()

	var got int
	if err := db.QueryRowContext(context.Background(), `select count(*) from sample_match_ref where sample_id = $1`, sampleID).Scan(&got); err != nil {
		t.Fatalf("count sample_match_ref for sample %s: %v", sampleID, err)
	}
	if got != want {
		t.Fatalf("sample_match_ref count for sample %s got %d want %d", sampleID, got, want)
	}
}

func stringPtr(v string) *string {
	return &v
}
