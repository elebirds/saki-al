package repo

import (
	"context"
	"database/sql"
	"path/filepath"
	"runtime"
	"testing"

	_ "github.com/jackc/pgx/v5/stdlib"
	"github.com/pressly/goose/v3"
	"github.com/testcontainers/testcontainers-go"
	"github.com/testcontainers/testcontainers-go/modules/postgres"
	"github.com/testcontainers/testcontainers-go/wait"
)

func TestSystemBaseMigrationUsesInitializationSchema(t *testing.T) {
	t.Setenv("TESTCONTAINERS_RYUK_DISABLED", "true")

	ctx := context.Background()
	container, dsn := startSystemRepoPostgres(t, ctx)
	defer func() {
		_ = testcontainers.TerminateContainer(container)
	}()

	sqlDB, err := sql.Open("pgx", dsn)
	if err != nil {
		t.Fatalf("open sql db: %v", err)
	}
	defer sqlDB.Close()

	goose.SetDialect("postgres")
	if err := goose.Up(sqlDB, systemRepoMigrationsDir(t)); err != nil {
		t.Fatalf("run migrations: %v", err)
	}

	var (
		initializationStateTypeExists bool
		installationStateTypeExists   bool
	)
	if err := sqlDB.QueryRowContext(ctx, `
select exists (
    select 1 from pg_type
    where typnamespace = 'public'::regnamespace
      and typname = 'system_initialization_state'
)
`).Scan(&initializationStateTypeExists); err != nil {
		t.Fatalf("query system_initialization_state existence: %v", err)
	}
	if err := sqlDB.QueryRowContext(ctx, `
select exists (
    select 1 from pg_type
    where typnamespace = 'public'::regnamespace
      and typname = 'system_installation_state'
)
`).Scan(&installationStateTypeExists); err != nil {
		t.Fatalf("query system_installation_state existence: %v", err)
	}
	if !initializationStateTypeExists || installationStateTypeExists {
		t.Fatalf("expected final initialization enum only, got system_initialization_state=%t system_installation_state=%t",
			initializationStateTypeExists, installationStateTypeExists)
	}

	assertColumnExists := func(column string) {
		t.Helper()

		var exists bool
		if err := sqlDB.QueryRowContext(ctx, `
select exists (
    select 1 from information_schema.columns
    where table_schema = 'public'
      and table_name = 'system_installation'
      and column_name = $1
)
`, column).Scan(&exists); err != nil {
			t.Fatalf("query column %s existence: %v", column, err)
		}
		if !exists {
			t.Fatalf("expected system_installation.%s to exist", column)
		}
	}
	assertColumnMissing := func(column string) {
		t.Helper()

		var exists bool
		if err := sqlDB.QueryRowContext(ctx, `
select exists (
    select 1 from information_schema.columns
    where table_schema = 'public'
      and table_name = 'system_installation'
      and column_name = $1
)
`, column).Scan(&exists); err != nil {
			t.Fatalf("query column %s existence: %v", column, err)
		}
		if exists {
			t.Fatalf("expected legacy system_installation.%s to be absent from final schema", column)
		}
	}

	assertColumnExists("initialization_state")
	assertColumnExists("initialized_at")
	assertColumnExists("initialized_by_principal_id")
	assertColumnMissing("install_state")
	assertColumnMissing("setup_at")
	assertColumnMissing("setup_by_principal_id")
}

func startSystemRepoPostgres(t *testing.T, ctx context.Context) (*postgres.PostgresContainer, string) {
	t.Helper()

	container, err := postgres.Run(
		ctx,
		"postgres:16-alpine",
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

func systemRepoMigrationsDir(t *testing.T) string {
	t.Helper()

	_, currentFile, _, ok := runtime.Caller(0)
	if !ok {
		t.Fatal("resolve current file")
	}
	return filepath.Clean(filepath.Join(filepath.Dir(currentFile), "..", "..", "..", "..", "db", "migrations"))
}
