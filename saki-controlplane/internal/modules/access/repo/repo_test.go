package repo

import (
	"context"
	"database/sql"
	"os/exec"
	"path/filepath"
	"runtime"
	"slices"
	"strings"
	"testing"

	appdb "github.com/elebirds/saki/saki-controlplane/internal/app/db"
	"github.com/testcontainers/testcontainers-go"
	"github.com/testcontainers/testcontainers-go/modules/postgres"
	"github.com/testcontainers/testcontainers-go/wait"
	_ "github.com/jackc/pgx/v5/stdlib"
	"github.com/pressly/goose/v3"
)

func TestPrincipalRepoGetByIDAndSubjectKey(t *testing.T) {
	t.Setenv("TESTCONTAINERS_RYUK_DISABLED", "true")

	ctx := context.Background()
	container, dsn := startAccessPostgres(t, ctx)
	defer func() {
		_ = testcontainers.TerminateContainer(container)
	}()

	sqlDB, err := sql.Open("pgx", dsn)
	if err != nil {
		t.Fatalf("open sql db: %v", err)
	}
	defer sqlDB.Close()

	goose.SetDialect("postgres")
	if err := goose.Up(sqlDB, accessMigrationsDir(t)); err != nil {
		t.Fatalf("run migrations: %v", err)
	}

	pool, err := appdb.NewPool(ctx, dsn)
	if err != nil {
		t.Fatalf("create pool: %v", err)
	}
	defer pool.Close()

	repo := NewPrincipalRepo(pool)
	principal, err := repo.UpsertBootstrapPrincipal(ctx, UpsertBootstrapPrincipalParams{
		SubjectType: "user",
		SubjectKey:  "user-1",
		DisplayName: "User One",
		Permissions: []string{"projects:read"},
	})
	if err != nil {
		t.Fatalf("seed principal: %v", err)
	}
	if principal == nil {
		t.Fatal("expected principal")
	}

	byID, err := repo.GetByID(ctx, principal.ID)
	if err != nil {
		t.Fatalf("get principal by id: %v", err)
	}
	if byID == nil {
		t.Fatal("expected principal by id")
	}
	if byID.SubjectType != "user" || byID.SubjectKey != "user-1" {
		t.Fatalf("unexpected principal by id: %+v", byID)
	}

	bySubject, err := repo.GetBySubjectKey(ctx, "user", "user-1")
	if err != nil {
		t.Fatalf("get principal by subject key: %v", err)
	}
	if bySubject == nil {
		t.Fatal("expected principal by subject key")
	}
	if bySubject.ID != principal.ID {
		t.Fatalf("expected same principal id, got byID=%s bySubject=%s", principal.ID, bySubject.ID)
	}
	if bySubject.DisplayName != "User One" || bySubject.Status != "active" {
		t.Fatalf("unexpected principal by subject key: %+v", bySubject)
	}
}

func TestPrincipalRepoListPermissionsReturnsStableOrder(t *testing.T) {
	t.Setenv("TESTCONTAINERS_RYUK_DISABLED", "true")

	ctx := context.Background()
	container, dsn := startAccessPostgres(t, ctx)
	defer func() {
		_ = testcontainers.TerminateContainer(container)
	}()

	sqlDB, err := sql.Open("pgx", dsn)
	if err != nil {
		t.Fatalf("open sql db: %v", err)
	}
	defer sqlDB.Close()

	goose.SetDialect("postgres")
	if err := goose.Up(sqlDB, accessMigrationsDir(t)); err != nil {
		t.Fatalf("run migrations: %v", err)
	}

	pool, err := appdb.NewPool(ctx, dsn)
	if err != nil {
		t.Fatalf("create pool: %v", err)
	}
	defer pool.Close()

	repo := NewPrincipalRepo(pool)
	principal, err := repo.UpsertBootstrapPrincipal(ctx, UpsertBootstrapPrincipalParams{
		SubjectType: "user",
		SubjectKey:  "user-2",
		DisplayName: "User Two",
		Permissions: []string{"projects:write", "projects:read", "imports:read"},
	})
	if err != nil {
		t.Fatalf("seed principal: %v", err)
	}

	permissions, err := repo.ListPermissions(ctx, principal.ID)
	if err != nil {
		t.Fatalf("list permissions: %v", err)
	}

	expected := []string{"imports:read", "projects:read", "projects:write"}
	if !slices.Equal(permissions, expected) {
		t.Fatalf("unexpected permissions: got=%v want=%v", permissions, expected)
	}
}

func TestPrincipalRepoUpsertBootstrapPrincipalReplacesDisplayNameAndPermissions(t *testing.T) {
	t.Setenv("TESTCONTAINERS_RYUK_DISABLED", "true")

	ctx := context.Background()
	container, dsn := startAccessPostgres(t, ctx)
	defer func() {
		_ = testcontainers.TerminateContainer(container)
	}()

	sqlDB, err := sql.Open("pgx", dsn)
	if err != nil {
		t.Fatalf("open sql db: %v", err)
	}
	defer sqlDB.Close()

	goose.SetDialect("postgres")
	if err := goose.Up(sqlDB, accessMigrationsDir(t)); err != nil {
		t.Fatalf("run migrations: %v", err)
	}

	pool, err := appdb.NewPool(ctx, dsn)
	if err != nil {
		t.Fatalf("create pool: %v", err)
	}
	defer pool.Close()

	repo := NewPrincipalRepo(pool)
	first, err := repo.UpsertBootstrapPrincipal(ctx, UpsertBootstrapPrincipalParams{
		SubjectType: "user",
		SubjectKey:  "user-3",
		DisplayName: "Old Name",
		Permissions: []string{"projects:read"},
	})
	if err != nil {
		t.Fatalf("first upsert principal: %v", err)
	}

	second, err := repo.UpsertBootstrapPrincipal(ctx, UpsertBootstrapPrincipalParams{
		SubjectType: "user",
		SubjectKey:  "user-3",
		DisplayName: "New Name",
		Permissions: []string{"imports:read", "projects:write"},
	})
	if err != nil {
		t.Fatalf("second upsert principal: %v", err)
	}

	if second.ID != first.ID {
		t.Fatalf("expected same principal id after upsert, got first=%s second=%s", first.ID, second.ID)
	}
	if second.DisplayName != "New Name" {
		t.Fatalf("expected updated display name, got %+v", second)
	}

	permissions, err := repo.ListPermissions(ctx, second.ID)
	if err != nil {
		t.Fatalf("list permissions after upsert: %v", err)
	}

	expected := []string{"imports:read", "projects:write"}
	if !slices.Equal(permissions, expected) {
		t.Fatalf("unexpected permissions after upsert: got=%v want=%v", permissions, expected)
	}
}

func TestPrincipalRepoUpsertBootstrapPrincipalPreservesDisabledStatus(t *testing.T) {
	t.Setenv("TESTCONTAINERS_RYUK_DISABLED", "true")

	ctx := context.Background()
	container, dsn := startAccessPostgres(t, ctx)
	defer func() {
		_ = testcontainers.TerminateContainer(container)
	}()

	sqlDB, err := sql.Open("pgx", dsn)
	if err != nil {
		t.Fatalf("open sql db: %v", err)
	}
	defer sqlDB.Close()

	goose.SetDialect("postgres")
	if err := goose.Up(sqlDB, accessMigrationsDir(t)); err != nil {
		t.Fatalf("run migrations: %v", err)
	}

	pool, err := appdb.NewPool(ctx, dsn)
	if err != nil {
		t.Fatalf("create pool: %v", err)
	}
	defer pool.Close()

	repo := NewPrincipalRepo(pool)
	principal, err := repo.UpsertBootstrapPrincipal(ctx, UpsertBootstrapPrincipalParams{
		SubjectType: "user",
		SubjectKey:  "user-4",
		DisplayName: "Disabled User",
		Permissions: []string{"projects:read"},
	})
	if err != nil {
		t.Fatalf("seed principal: %v", err)
	}

	if _, err := pool.Exec(ctx, `
update access_principal
set status = 'disabled',
    updated_at = now()
where id = $1
`, principal.ID); err != nil {
		t.Fatalf("disable principal: %v", err)
	}

	upserted, err := repo.UpsertBootstrapPrincipal(ctx, UpsertBootstrapPrincipalParams{
		SubjectType: "user",
		SubjectKey:  "user-4",
		DisplayName: "Disabled User Updated",
		Permissions: []string{"projects:write"},
	})
	if err != nil {
		t.Fatalf("upsert disabled principal: %v", err)
	}

	if upserted.Status != "disabled" {
		t.Fatalf("expected disabled status to be preserved, got %+v", upserted)
	}

	loaded, err := repo.GetByID(ctx, principal.ID)
	if err != nil {
		t.Fatalf("reload principal: %v", err)
	}
	if loaded == nil || loaded.Status != "disabled" {
		t.Fatalf("expected disabled principal after reload, got %+v", loaded)
	}
}

func startAccessPostgres(t *testing.T, ctx context.Context) (*postgres.PostgresContainer, string) {
	t.Helper()

	container, err := postgres.Run(
		ctx,
		accessPostgresImageRef(),
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

func accessMigrationsDir(t *testing.T) string {
	t.Helper()

	_, file, _, ok := runtime.Caller(0)
	if !ok {
		t.Fatal("resolve caller")
	}

	return filepath.Join(filepath.Dir(file), "..", "..", "..", "..", "db", "migrations")
}

func accessPostgresImageRef() string {
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
