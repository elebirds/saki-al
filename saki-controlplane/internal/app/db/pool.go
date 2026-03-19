package db

import (
	"context"

	sqlcdb "github.com/elebirds/saki/saki-controlplane/internal/gen/sqlc"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

func NewPool(ctx context.Context, dsn string) (*pgxpool.Pool, error) {
	cfg, err := pgxpool.ParseConfig(dsn)
	if err != nil {
		return nil, err
	}
	cfg.AfterConnect = func(ctx context.Context, conn *pgx.Conn) error {
		return registerSQLCTypes(ctx, conn)
	}
	return pgxpool.NewWithConfig(ctx, cfg)
}

func registerSQLCTypes(ctx context.Context, conn *pgx.Conn) error {
	for _, typeName := range []string{
		"access_principal_status",
		"asset_kind",
		"asset_owner_type",
		"asset_reference_lifecycle",
		"asset_reference_role",
		"asset_status",
		"asset_storage_backend",
		"asset_upload_intent_state",
		"import_task_event_phase",
		"import_task_status",
		"import_upload_session_status",
		"runtime_task_kind",
		"runtime_task_status",
	} {
		typ, err := conn.LoadType(ctx, typeName)
		if err != nil {
			return err
		}
		conn.TypeMap().RegisterType(typ)
	}

	for _, typeName := range []string{
		"_access_principal_status",
		"_asset_kind",
		"_asset_owner_type",
		"_asset_reference_lifecycle",
		"_asset_reference_role",
		"_asset_status",
		"_asset_storage_backend",
		"_asset_upload_intent_state",
		"_import_task_event_phase",
		"_import_task_status",
		"_import_upload_session_status",
		"_runtime_task_kind",
		"_runtime_task_status",
	} {
		typ, err := conn.LoadType(ctx, typeName)
		if err != nil {
			return err
		}
		conn.TypeMap().RegisterType(typ)
	}

	m := conn.TypeMap()
	m.RegisterDefaultPgType(sqlcdb.AccessPrincipalStatus(""), "access_principal_status")
	m.RegisterDefaultPgType([]sqlcdb.AccessPrincipalStatus{}, "_access_principal_status")
	m.RegisterDefaultPgType(sqlcdb.AssetKind(""), "asset_kind")
	m.RegisterDefaultPgType([]sqlcdb.AssetKind{}, "_asset_kind")
	m.RegisterDefaultPgType(sqlcdb.AssetOwnerType(""), "asset_owner_type")
	m.RegisterDefaultPgType([]sqlcdb.AssetOwnerType{}, "_asset_owner_type")
	m.RegisterDefaultPgType(sqlcdb.AssetReferenceLifecycle(""), "asset_reference_lifecycle")
	m.RegisterDefaultPgType([]sqlcdb.AssetReferenceLifecycle{}, "_asset_reference_lifecycle")
	m.RegisterDefaultPgType(sqlcdb.AssetReferenceRole(""), "asset_reference_role")
	m.RegisterDefaultPgType([]sqlcdb.AssetReferenceRole{}, "_asset_reference_role")
	m.RegisterDefaultPgType(sqlcdb.AssetStatus(""), "asset_status")
	m.RegisterDefaultPgType([]sqlcdb.AssetStatus{}, "_asset_status")
	m.RegisterDefaultPgType(sqlcdb.AssetStorageBackend(""), "asset_storage_backend")
	m.RegisterDefaultPgType([]sqlcdb.AssetStorageBackend{}, "_asset_storage_backend")
	m.RegisterDefaultPgType(sqlcdb.AssetUploadIntentState(""), "asset_upload_intent_state")
	m.RegisterDefaultPgType([]sqlcdb.AssetUploadIntentState{}, "_asset_upload_intent_state")
	m.RegisterDefaultPgType(sqlcdb.ImportTaskEventPhase(""), "import_task_event_phase")
	m.RegisterDefaultPgType([]sqlcdb.ImportTaskEventPhase{}, "_import_task_event_phase")
	m.RegisterDefaultPgType(sqlcdb.ImportTaskStatus(""), "import_task_status")
	m.RegisterDefaultPgType([]sqlcdb.ImportTaskStatus{}, "_import_task_status")
	m.RegisterDefaultPgType(sqlcdb.ImportUploadSessionStatus(""), "import_upload_session_status")
	m.RegisterDefaultPgType([]sqlcdb.ImportUploadSessionStatus{}, "_import_upload_session_status")
	m.RegisterDefaultPgType(sqlcdb.RuntimeTaskKind(""), "runtime_task_kind")
	m.RegisterDefaultPgType([]sqlcdb.RuntimeTaskKind{}, "_runtime_task_kind")
	m.RegisterDefaultPgType(sqlcdb.RuntimeTaskStatus(""), "runtime_task_status")
	m.RegisterDefaultPgType([]sqlcdb.RuntimeTaskStatus{}, "_runtime_task_status")

	return nil
}
