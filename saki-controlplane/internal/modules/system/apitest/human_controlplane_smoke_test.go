package apitest

import (
	"bytes"
	"database/sql"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"runtime"
	"slices"
	"sync"
	"testing"

	"github.com/elebirds/saki/saki-controlplane/internal/app/bootstrap"
	_ "github.com/jackc/pgx/v5/stdlib"
	"github.com/pressly/goose/v3"
	"github.com/testcontainers/testcontainers-go"
	"github.com/testcontainers/testcontainers-go/modules/postgres"
	"github.com/testcontainers/testcontainers-go/wait"
)

func TestHumanControlPlaneSystemSmoke(t *testing.T) {
	t.Setenv("TESTCONTAINERS_RYUK_DISABLED", "true")

	container, dsn := startSystemSmokePostgres(t)
	defer func() {
		_ = testcontainers.TerminateContainer(container)
	}()

	sqlDB, err := sql.Open("pgx", dsn)
	if err != nil {
		t.Fatalf("open sql db: %v", err)
	}
	defer sqlDB.Close()

	goose.SetDialect("postgres")
	if err := goose.Up(sqlDB, systemSmokeMigrationsDir(t)); err != nil {
		t.Fatalf("run migrations: %v", err)
	}

	t.Setenv("DATABASE_DSN", dsn)
	t.Setenv("AUTH_TOKEN_SECRET", "smoke-secret")
	t.Setenv("AUTH_TOKEN_TTL", "10m")
	t.Setenv("PUBLIC_API_BIND", "127.0.0.1:0")
	t.Setenv("BUILD_VERSION", "smoke-build")

	server, _, err := bootstrap.NewPublicAPI(t.Context())
	if err != nil {
		t.Fatalf("bootstrap public api: %v", err)
	}
	httpServer := httptest.NewServer(server.Handler)
	defer httpServer.Close()

	statusBody := decodeJSONResponse(t, doJSONRequest(t, httpServer.Client(), http.MethodGet, httpServer.URL+"/system/status", "", ""))
	if statusBody["initialization_state"] != "uninitialized" || statusBody["allow_self_register"] != false || statusBody["version"] != "smoke-build" {
		t.Fatalf("unexpected initial status: %+v", statusBody)
	}
	if _, ok := statusBody["install_state"]; ok {
		t.Fatalf("latest status response should not expose legacy install_state, got %+v", statusBody)
	}

	initResp := doJSONRequest(
		t,
		httpServer.Client(),
		http.MethodPost,
		httpServer.URL+"/system/init",
		`{"email":"admin@example.com","password":"secret-pass","full_name":"Initial Admin"}`,
		"",
	)
	if initResp.StatusCode != http.StatusOK {
		t.Fatalf("unexpected init status: %d body=%s", initResp.StatusCode, readBodyString(t, initResp))
	}
	initBody := decodeJSONResponse(t, initResp)
	accessToken, _ := initBody["access_token"].(string)
	refreshToken, _ := initBody["refresh_token"].(string)
	if accessToken == "" || refreshToken == "" {
		t.Fatalf("expected init to return initial session: %+v", initBody)
	}
	if initBody["expires_in"] != float64(600) {
		t.Fatalf("expected default access ttl to be 600s, got %+v", initBody)
	}

	passwordlessLogin := doJSONRequest(
		t,
		httpServer.Client(),
		http.MethodPost,
		httpServer.URL+"/auth/login",
		`{"identifier":"admin@example.com"}`,
		"",
	)
	if passwordlessLogin.StatusCode != http.StatusBadRequest {
		t.Fatalf("expected passwordless login payload to be rejected, got %d body=%s", passwordlessLogin.StatusCode, readBodyString(t, passwordlessLogin))
	}

	secondInit := doJSONRequest(
		t,
		httpServer.Client(),
		http.MethodPost,
		httpServer.URL+"/system/init",
		`{"email":"admin@example.com","password":"secret-pass","full_name":"Initial Admin"}`,
		"",
	)
	if secondInit.StatusCode != http.StatusConflict {
		t.Fatalf("expected repeated init to conflict, got %d body=%s", secondInit.StatusCode, readBodyString(t, secondInit))
	}

	settingsBody := decodeJSONResponse(t, doJSONRequest(t, httpServer.Client(), http.MethodGet, httpServer.URL+"/system/settings", "", accessToken))
	schema, ok := settingsBody["schema"].([]any)
	if !ok || len(schema) == 0 {
		t.Fatalf("unexpected settings schema: %+v", settingsBody)
	}
	values, ok := settingsBody["values"].(map[string]any)
	if !ok {
		t.Fatalf("unexpected settings values: %+v", settingsBody)
	}
	authSetting, ok := values["auth.allow_self_register"].(map[string]any)
	if !ok || authSetting["kind"] != "boolean" || authSetting["bool_value"] != false {
		t.Fatalf("unexpected allow self register value: %+v", values)
	}

	patchBody := decodeJSONResponse(t, doJSONRequest(
		t,
		httpServer.Client(),
		http.MethodPatch,
		httpServer.URL+"/system/settings",
		`{"values":{"auth.allow_self_register":{"kind":"boolean","bool_value":true}}}`,
		accessToken,
	))
	patchValues, ok := patchBody["values"].(map[string]any)
	if !ok {
		t.Fatalf("unexpected patch body: %+v", patchBody)
	}
	patchedAllow, ok := patchValues["auth.allow_self_register"].(map[string]any)
	if !ok || patchedAllow["bool_value"] != true {
		t.Fatalf("expected patched self register setting, got %+v", patchBody)
	}

	finalStatus := decodeJSONResponse(t, doJSONRequest(t, httpServer.Client(), http.MethodGet, httpServer.URL+"/system/status", "", ""))
	if finalStatus["initialization_state"] != "initialized" || finalStatus["allow_self_register"] != true {
		t.Fatalf("unexpected final status: %+v", finalStatus)
	}
	if _, ok := finalStatus["install_state"]; ok {
		t.Fatalf("latest status response should not expose legacy install_state, got %+v", finalStatus)
	}

	typesBody := decodeJSONResponse(t, doJSONRequest(t, httpServer.Client(), http.MethodGet, httpServer.URL+"/system/types", "", ""))
	taskTypes, ok := typesBody["task_types"].([]any)
	if !ok || len(taskTypes) == 0 {
		t.Fatalf("unexpected task types: %+v", typesBody)
	}
	datasetTypes, ok := typesBody["dataset_types"].([]any)
	if !ok || len(datasetTypes) == 0 {
		t.Fatalf("unexpected dataset types: %+v", typesBody)
	}
}

func TestHumanControlPlaneSetupAllowsSingleWinnerUnderConcurrency(t *testing.T) {
	t.Setenv("TESTCONTAINERS_RYUK_DISABLED", "true")

	container, dsn := startSystemSmokePostgres(t)
	defer func() {
		_ = testcontainers.TerminateContainer(container)
	}()

	sqlDB, err := sql.Open("pgx", dsn)
	if err != nil {
		t.Fatalf("open sql db: %v", err)
	}
	defer sqlDB.Close()

	goose.SetDialect("postgres")
	if err := goose.Up(sqlDB, systemSmokeMigrationsDir(t)); err != nil {
		t.Fatalf("run migrations: %v", err)
	}

	t.Setenv("DATABASE_DSN", dsn)
	t.Setenv("AUTH_TOKEN_SECRET", "smoke-secret")
	t.Setenv("PUBLIC_API_BIND", "127.0.0.1:0")

	server, _, err := bootstrap.NewPublicAPI(t.Context())
	if err != nil {
		t.Fatalf("bootstrap public api: %v", err)
	}
	httpServer := httptest.NewServer(server.Handler)
	defer httpServer.Close()

	type result struct {
		status int
		body   string
		err    error
	}

	payloads := []string{
		`{"email":"admin-1@example.com","password":"secret-pass","full_name":"Initial Admin 1"}`,
		`{"email":"admin-2@example.com","password":"secret-pass","full_name":"Initial Admin 2"}`,
	}
	start := make(chan struct{})
	results := make([]result, len(payloads))
	var wg sync.WaitGroup
	for idx, payload := range payloads {
		wg.Add(1)
		go func(idx int, payload string) {
			defer wg.Done()
			<-start

			resp, err := httpServer.Client().Post(httpServer.URL+"/system/init", "application/json", bytes.NewBufferString(payload))
			if err != nil {
				results[idx].err = err
				return
			}
			defer resp.Body.Close()

			body, err := io.ReadAll(resp.Body)
			if err != nil {
				results[idx].err = err
				return
			}
			results[idx] = result{status: resp.StatusCode, body: string(body)}
		}(idx, payload)
	}
	close(start)
	wg.Wait()

	statuses := make([]int, 0, len(results))
	for _, each := range results {
		if each.err != nil {
			t.Fatalf("concurrent init request failed: %v", each.err)
		}
		statuses = append(statuses, each.status)
	}
	slices.Sort(statuses)
	if !slices.Equal(statuses, []int{http.StatusOK, http.StatusConflict}) {
		t.Fatalf("unexpected concurrent init statuses: %+v results=%+v", statuses, results)
	}

	var userCount int
	if err := sqlDB.QueryRow(`select count(*) from iam_user`).Scan(&userCount); err != nil {
		t.Fatalf("count users: %v", err)
	}
	if userCount != 1 {
		t.Fatalf("expected exactly one initial user, got %d", userCount)
	}

	var sessionCount int
	if err := sqlDB.QueryRow(`select count(*) from iam_refresh_session`).Scan(&sessionCount); err != nil {
		t.Fatalf("count refresh sessions: %v", err)
	}
	if sessionCount != 1 {
		t.Fatalf("expected exactly one initial refresh session, got %d", sessionCount)
	}
}

func startSystemSmokePostgres(t *testing.T) (testcontainers.Container, string) {
	t.Helper()

	ctx := t.Context()
	container, err := postgres.Run(
		ctx,
		"postgres:16-alpine",
		postgres.WithDatabase("saki"),
		postgres.WithUsername("postgres"),
		postgres.WithPassword("postgres"),
		testcontainers.WithWaitStrategy(wait.ForListeningPort("5432/tcp")),
	)
	if err != nil {
		t.Fatalf("start postgres container: %v", err)
	}

	dsn, err := container.ConnectionString(ctx, "sslmode=disable")
	if err != nil {
		t.Fatalf("postgres connection string: %v", err)
	}
	return container, dsn
}

func systemSmokeMigrationsDir(t *testing.T) string {
	t.Helper()

	_, file, _, ok := runtime.Caller(0)
	if !ok {
		t.Fatal("runtime caller failed")
	}
	return filepath.Join(filepath.Dir(file), "..", "..", "..", "..", "db", "migrations")
}

func doJSONRequest(t *testing.T, client *http.Client, method string, url string, body string, bearerToken string) *http.Response {
	t.Helper()

	var reader *bytes.Reader
	if body == "" {
		reader = bytes.NewReader(nil)
	} else {
		reader = bytes.NewReader([]byte(body))
	}

	req, err := http.NewRequest(method, url, reader)
	if err != nil {
		t.Fatalf("new request: %v", err)
	}
	if body != "" {
		req.Header.Set("Content-Type", "application/json")
	}
	if bearerToken != "" {
		req.Header.Set("Authorization", "Bearer "+bearerToken)
	}

	resp, err := client.Do(req)
	if err != nil {
		t.Fatalf("do request: %v", err)
	}
	return resp
}

func decodeJSONResponse(t *testing.T, resp *http.Response) map[string]any {
	t.Helper()
	defer resp.Body.Close()

	var body map[string]any
	if err := json.NewDecoder(resp.Body).Decode(&body); err != nil {
		t.Fatalf("decode response: %v", err)
	}
	if resp.StatusCode >= http.StatusBadRequest {
		t.Fatalf("unexpected error response: status=%d body=%+v", resp.StatusCode, body)
	}
	return body
}

func readBodyString(t *testing.T, resp *http.Response) string {
	t.Helper()
	defer resp.Body.Close()

	var body bytes.Buffer
	if _, err := body.ReadFrom(resp.Body); err != nil {
		t.Fatalf("read response body: %v", err)
	}
	return body.String()
}
