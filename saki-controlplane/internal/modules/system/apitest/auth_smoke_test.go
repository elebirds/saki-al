package apitest

import (
	"database/sql"
	"net/http"
	"net/http/httptest"
	"slices"
	"testing"

	"github.com/elebirds/saki/saki-controlplane/internal/app/bootstrap"
	_ "github.com/jackc/pgx/v5/stdlib"
	"github.com/pressly/goose/v3"
	"github.com/testcontainers/testcontainers-go"
)

func TestHumanControlPlaneAuthSmoke(t *testing.T) {
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

	setupBody := decodeJSONResponse(t, doJSONRequest(
		t,
		httpServer.Client(),
		http.MethodPost,
		httpServer.URL+"/system/setup",
		`{"email":"admin@example.com","password":"secret-pass","full_name":"Initial Admin"}`,
		"",
	))
	adminAccessToken, _ := setupBody["access_token"].(string)
	adminRefreshToken, _ := setupBody["refresh_token"].(string)
	if adminAccessToken == "" || adminRefreshToken == "" {
		t.Fatalf("expected setup to return initial session, got %+v", setupBody)
	}

	loginResp := doJSONRequest(
		t,
		httpServer.Client(),
		http.MethodPost,
		httpServer.URL+"/auth/login",
		`{"identifier":"admin@example.com","password":"secret-pass"}`,
		"",
	)
	if loginResp.StatusCode != http.StatusOK {
		t.Fatalf("unexpected login status: %d body=%s", loginResp.StatusCode, readBodyString(t, loginResp))
	}
	loginBody := decodeJSONResponse(t, loginResp)
	loginAccessToken, _ := loginBody["access_token"].(string)
	loginRefreshToken, _ := loginBody["refresh_token"].(string)
	if loginAccessToken == "" || loginRefreshToken == "" {
		t.Fatalf("expected login to return auth session, got %+v", loginBody)
	}
	if loginBody["expires_in"] != float64(600) {
		t.Fatalf("expected login access ttl=600, got %+v", loginBody)
	}
	loginUser, ok := loginBody["user"].(map[string]any)
	if !ok || loginUser["email"] != "admin@example.com" {
		t.Fatalf("unexpected login user payload: %+v", loginBody)
	}
	loginPermissions, ok := loginBody["permissions"].([]any)
	if !ok || !slices.Contains(loginPermissions, any("system:write")) {
		t.Fatalf("expected login to expose permission snapshot, got %+v", loginBody)
	}

	meBody := decodeJSONResponse(t, doJSONRequest(
		t,
		httpServer.Client(),
		http.MethodGet,
		httpServer.URL+"/auth/me",
		"",
		loginAccessToken,
	))
	meUser, ok := meBody["user"].(map[string]any)
	if !ok || meUser["email"] != "admin@example.com" {
		t.Fatalf("unexpected me user payload: %+v", meBody)
	}
	meRoles, ok := meBody["system_roles"].([]any)
	if !ok || !slices.Contains(meRoles, any("super_admin")) {
		t.Fatalf("expected me to expose super_admin binding, got %+v", meBody)
	}
	mePermissions, ok := meBody["permissions"].([]any)
	if !ok || !slices.Contains(mePermissions, any("system:write")) {
		t.Fatalf("expected me to expose permission snapshot, got %+v", meBody)
	}

	refreshResp := doJSONRequest(
		t,
		httpServer.Client(),
		http.MethodPost,
		httpServer.URL+"/auth/refresh",
		`{"refresh_token":"`+loginRefreshToken+`"}`,
		"",
	)
	if refreshResp.StatusCode != http.StatusOK {
		t.Fatalf("unexpected refresh status: %d body=%s", refreshResp.StatusCode, readBodyString(t, refreshResp))
	}
	refreshBody := decodeJSONResponse(t, refreshResp)
	rotatedRefreshToken, _ := refreshBody["refresh_token"].(string)
	if rotatedRefreshToken == "" || rotatedRefreshToken == loginRefreshToken {
		t.Fatalf("expected refresh to rotate refresh token, got %+v", refreshBody)
	}
	refreshPermissions, ok := refreshBody["permissions"].([]any)
	if !ok || !slices.Contains(refreshPermissions, any("system:write")) {
		t.Fatalf("expected refresh to preserve permission snapshot, got %+v", refreshBody)
	}

	var rotatedChildCount int
	if err := sqlDB.QueryRow(`select count(*) from iam_refresh_session where rotated_from is not null`).Scan(&rotatedChildCount); err != nil {
		t.Fatalf("count rotated child sessions: %v", err)
	}
	if rotatedChildCount != 1 {
		t.Fatalf("expected exactly one rotated child session after refresh, got %d", rotatedChildCount)
	}

	replayResp := doJSONRequest(
		t,
		httpServer.Client(),
		http.MethodPost,
		httpServer.URL+"/auth/refresh",
		`{"refresh_token":"`+loginRefreshToken+`"}`,
		"",
	)
	if replayResp.StatusCode != http.StatusUnauthorized {
		t.Fatalf("expected replayed refresh token to be rejected, got %d body=%s", replayResp.StatusCode, readBodyString(t, replayResp))
	}

	var replayDetectedCount int
	if err := sqlDB.QueryRow(`select count(*) from iam_refresh_session where replay_detected_at is not null`).Scan(&replayDetectedCount); err != nil {
		t.Fatalf("count replay-detected sessions: %v", err)
	}
	if replayDetectedCount < 2 {
		t.Fatalf("expected replay to mark old and current family sessions, got %d rows", replayDetectedCount)
	}

	familyRevokedResp := doJSONRequest(
		t,
		httpServer.Client(),
		http.MethodPost,
		httpServer.URL+"/auth/refresh",
		`{"refresh_token":"`+rotatedRefreshToken+`"}`,
		"",
	)
	if familyRevokedResp.StatusCode != http.StatusUnauthorized {
		t.Fatalf("expected replay to revoke rotated token family, got %d body=%s", familyRevokedResp.StatusCode, readBodyString(t, familyRevokedResp))
	}

	adminLoginResp := doJSONRequest(
		t,
		httpServer.Client(),
		http.MethodPost,
		httpServer.URL+"/auth/login",
		`{"identifier":"admin@example.com","password":"secret-pass"}`,
		"",
	)
	if adminLoginResp.StatusCode != http.StatusOK {
		t.Fatalf("unexpected re-login status: %d body=%s", adminLoginResp.StatusCode, readBodyString(t, adminLoginResp))
	}
	adminLoginBody := decodeJSONResponse(t, adminLoginResp)
	adminAccessToken, _ = adminLoginBody["access_token"].(string)

	settingsResp := doJSONRequest(
		t,
		httpServer.Client(),
		http.MethodPatch,
		httpServer.URL+"/system/settings",
		`{"values":{"auth.allow_self_register":{"kind":"boolean","bool_value":true}}}`,
		adminAccessToken,
	)
	if settingsResp.StatusCode != http.StatusOK {
		t.Fatalf("unexpected settings patch status: %d body=%s", settingsResp.StatusCode, readBodyString(t, settingsResp))
	}
	_ = decodeJSONResponse(t, settingsResp)

	registerResp := doJSONRequest(
		t,
		httpServer.Client(),
		http.MethodPost,
		httpServer.URL+"/auth/register",
		`{"email":"user@example.com","password":"user-pass","full_name":"Normal User"}`,
		"",
	)
	if registerResp.StatusCode != http.StatusOK {
		t.Fatalf("unexpected register status: %d body=%s", registerResp.StatusCode, readBodyString(t, registerResp))
	}
	registerBody := decodeJSONResponse(t, registerResp)
	userAccessToken, _ := registerBody["access_token"].(string)
	userRefreshToken, _ := registerBody["refresh_token"].(string)
	registerUser, ok := registerBody["user"].(map[string]any)
	if !ok || registerUser["email"] != "user@example.com" {
		t.Fatalf("unexpected register response: %+v", registerBody)
	}
	if _, ok := registerBody["permissions"].([]any); !ok {
		t.Fatalf("expected register to expose permissions field, got %+v", registerBody)
	}

	changePasswordResp := doJSONRequest(
		t,
		httpServer.Client(),
		http.MethodPost,
		httpServer.URL+"/auth/change-password",
		`{"old_password":"user-pass","new_password":"user-pass-2"}`,
		userAccessToken,
	)
	if changePasswordResp.StatusCode != http.StatusOK {
		t.Fatalf("unexpected change-password status: %d body=%s", changePasswordResp.StatusCode, readBodyString(t, changePasswordResp))
	}
	changePasswordBody := decodeJSONResponse(t, changePasswordResp)
	changedRefreshToken, _ := changePasswordBody["refresh_token"].(string)
	if changedRefreshToken == "" || changedRefreshToken == userRefreshToken {
		t.Fatalf("expected change-password to issue a new refresh token, got %+v", changePasswordBody)
	}
	if _, ok := changePasswordBody["permissions"].([]any); !ok {
		t.Fatalf("expected change-password to expose permissions field, got %+v", changePasswordBody)
	}

	oldRefreshResp := doJSONRequest(
		t,
		httpServer.Client(),
		http.MethodPost,
		httpServer.URL+"/auth/refresh",
		`{"refresh_token":"`+userRefreshToken+`"}`,
		"",
	)
	if oldRefreshResp.StatusCode != http.StatusUnauthorized {
		t.Fatalf("expected pre-change refresh token revoked, got %d body=%s", oldRefreshResp.StatusCode, readBodyString(t, oldRefreshResp))
	}

	oldPasswordLoginResp := doJSONRequest(
		t,
		httpServer.Client(),
		http.MethodPost,
		httpServer.URL+"/auth/login",
		`{"identifier":"user@example.com","password":"user-pass"}`,
		"",
	)
	if oldPasswordLoginResp.StatusCode != http.StatusUnauthorized {
		t.Fatalf("expected old password login rejected, got %d body=%s", oldPasswordLoginResp.StatusCode, readBodyString(t, oldPasswordLoginResp))
	}

	newPasswordLoginResp := doJSONRequest(
		t,
		httpServer.Client(),
		http.MethodPost,
		httpServer.URL+"/auth/login",
		`{"identifier":"user@example.com","password":"user-pass-2"}`,
		"",
	)
	if newPasswordLoginResp.StatusCode != http.StatusOK {
		t.Fatalf("expected new password login success, got %d body=%s", newPasswordLoginResp.StatusCode, readBodyString(t, newPasswordLoginResp))
	}
	newPasswordLoginBody := decodeJSONResponse(t, newPasswordLoginResp)
	logoutRefreshToken, _ := newPasswordLoginBody["refresh_token"].(string)

	logoutResp := doJSONRequest(
		t,
		httpServer.Client(),
		http.MethodPost,
		httpServer.URL+"/auth/logout",
		`{"refresh_token":"`+logoutRefreshToken+`"}`,
		"",
	)
	if logoutResp.StatusCode != http.StatusNoContent {
		t.Fatalf("expected logout to revoke current refresh session, got %d body=%s", logoutResp.StatusCode, readBodyString(t, logoutResp))
	}

	logoutRefreshResp := doJSONRequest(
		t,
		httpServer.Client(),
		http.MethodPost,
		httpServer.URL+"/auth/refresh",
		`{"refresh_token":"`+logoutRefreshToken+`"}`,
		"",
	)
	if logoutRefreshResp.StatusCode != http.StatusUnauthorized {
		t.Fatalf("expected logged out refresh token rejected, got %d body=%s", logoutRefreshResp.StatusCode, readBodyString(t, logoutRefreshResp))
	}
}
