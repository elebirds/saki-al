package bootstrap

import (
	"context"
	"log/slog"
	"net/http"
	"time"

	"github.com/elebirds/saki/saki-controlplane/internal/app/config"
	appdb "github.com/elebirds/saki/saki-controlplane/internal/app/db"
	"github.com/elebirds/saki/saki-controlplane/internal/app/observe"
	"github.com/elebirds/saki/saki-controlplane/internal/app/storage"
	accessapp "github.com/elebirds/saki/saki-controlplane/internal/modules/access/app"
	accessrepo "github.com/elebirds/saki/saki-controlplane/internal/modules/access/repo"
	annotationmapping "github.com/elebirds/saki/saki-controlplane/internal/modules/annotation/app/mapping"
	annotationrepo "github.com/elebirds/saki/saki-controlplane/internal/modules/annotation/repo"
	assetapi "github.com/elebirds/saki/saki-controlplane/internal/modules/asset/apihttp"
	assetapp "github.com/elebirds/saki/saki-controlplane/internal/modules/asset/app"
	assetrepo "github.com/elebirds/saki/saki-controlplane/internal/modules/asset/repo"
	datasetapp "github.com/elebirds/saki/saki-controlplane/internal/modules/dataset/app"
	datasetrepo "github.com/elebirds/saki/saki-controlplane/internal/modules/dataset/repo"
	importapi "github.com/elebirds/saki/saki-controlplane/internal/modules/importing/apihttp"
	importapp "github.com/elebirds/saki/saki-controlplane/internal/modules/importing/app"
	importrepo "github.com/elebirds/saki/saki-controlplane/internal/modules/importing/repo"
	projectapp "github.com/elebirds/saki/saki-controlplane/internal/modules/project/app"
	projectrepo "github.com/elebirds/saki/saki-controlplane/internal/modules/project/repo"
	runtimecommands "github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/app/commands"
	runtimequeries "github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/app/queries"
	runtimeapp "github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/app/runtime"
	runtimerepo "github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/repo"
	systemapi "github.com/elebirds/saki/saki-controlplane/internal/modules/system/apihttp"
	"github.com/jackc/pgx/v5/pgxpool"
)

var objectProviderFactory = storage.NewMinIOProvider

func NewPublicAPI(ctx context.Context) (*http.Server, *slog.Logger, error) {
	cfg, err := config.Load()
	if err != nil {
		return nil, nil, err
	}

	logger := observe.NewLogger("public-api", observe.ParseLevel(cfg.LogLevel), cfg.LogFormat)
	tokenTTL, err := time.ParseDuration(cfg.AuthTokenTTL)
	if err != nil {
		return nil, nil, err
	}

	pool, err := appdb.NewPool(ctx, cfg.DatabaseDSN)
	if err != nil {
		return nil, nil, err
	}

	taskRepo := runtimerepo.NewTaskRepo(pool)
	accessStore := accessrepo.NewAppStore(accessrepo.NewPrincipalRepo(pool))
	bootstrapPrincipals := make([]accessapp.BootstrapPrincipalSpec, 0, len(cfg.AuthBootstrapPrincipals))
	for _, principal := range cfg.AuthBootstrapPrincipals {
		bootstrapPrincipals = append(bootstrapPrincipals, accessapp.BootstrapPrincipalSpec{
			UserID:      principal.UserID,
			DisplayName: principal.DisplayName,
			Permissions: append([]string(nil), principal.Permissions...),
		})
	}
	if err := accessapp.NewBootstrapSeedUseCase(accessStore).Execute(ctx, bootstrapPrincipals); err != nil {
		pool.Close()
		return nil, nil, err
	}
	objectProvider, err := objectProviderFactory(storage.Config{
		Endpoint:  cfg.MinIOEndpoint,
		AccessKey: cfg.MinIOAccessKey,
		SecretKey: cfg.MinIOSecretKey,
		Bucket:    cfg.MinIOBucketName,
		Secure:    cfg.MinIOSecure,
	})
	if err != nil {
		pool.Close()
		return nil, nil, err
	}

	sampleRepo := annotationrepo.NewSampleRepo(pool)
	annotationRepo := annotationrepo.NewAnnotationRepo(pool)
	assetStore := assetrepo.NewAssetRepo(pool)
	datasetRepo := datasetrepo.NewDatasetRepo(pool)
	datasetStore := datasetapp.NewRepoStore(datasetRepo)
	projectRepo := projectrepo.NewProjectRepo(pool)
	projectStore := projectapp.NewRepoStore(projectRepo)
	importUploadRepo := importrepo.NewUploadRepo(pool)
	importPreviewRepo := importrepo.NewPreviewRepo(pool)
	importTaskRepo := importrepo.NewTaskRepo(pool)
	importMatchRepo := importrepo.NewSampleMatchRefRepo(pool)
	importPrepare := importapp.NewPrepareProjectAnnotationsUseCase(
		projectRepo,
		importUploadRepo,
		importPreviewRepo,
		importMatchRepo,
		importapp.NewParserRegistry(),
		objectProvider,
	)
	importExecute := importapp.NewExecuteProjectAnnotationsUseCase(
		projectRepo,
		importPreviewRepo,
		importTaskRepo,
		importapp.NewProjectAnnotationsTaskRunner(sampleRepo, annotationRepo, importTaskRepo),
	)

	handler, err := systemapi.NewHTTPHandler(systemapi.Dependencies{
		Authenticator:       accessapp.NewAuthenticator(cfg.AuthTokenSecret, tokenTTL).WithStore(accessStore),
		AccessStore:         accessStore,
		DatasetStore:        datasetStore,
		ProjectStore:        projectStore,
		RuntimeStore:        runtimequeries.NewRepoAdminStore(taskRepo, runtimerepo.NewExecutorRepo(pool)),
		RuntimeTaskCanceler: runtimecommands.NewCancelTaskHandlerWithTx(runtimerepo.NewCancelTaskTxRunner(pool)),
		AnnotationSamples:   sampleRepo,
		AnnotationDatasets:  datasetRepo,
		AnnotationStore:     annotationRepo,
		Asset: assetapi.Dependencies{
			Store:           assetStore,
			Provider:        objectProvider,
			UploadURLExpiry: 15 * time.Minute,
			DownloadExpiry:  15 * time.Minute,
		},
		AnnotationMapper: annotationmapping.NewClient(annotationmapping.ClientConfig{
			Command: []string{
				"uv",
				"run",
				"--project",
				"../saki-mapping-engine",
				"python",
				"-m",
				"saki_mapping_engine.worker_main",
			},
			Timeout: 5 * time.Second,
		}),
		Importing: importapi.Dependencies{
			Uploads:         importUploadRepo,
			Tasks:           importTaskRepo,
			Prepare:         importPrepare,
			Execute:         importExecute,
			Provider:        objectProvider,
			UploadURLExpiry: 15 * time.Minute,
		},
	})
	if err != nil {
		pool.Close()
		return nil, nil, err
	}

	server := &http.Server{
		Addr:              cfg.PublicAPIBind,
		Handler:           handler,
		ReadHeaderTimeout: 5 * time.Second,
	}
	server.RegisterOnShutdown(func() {
		pool.Close()
	})

	return server, logger, nil
}

func NewRuntime(ctx context.Context) (*runtimeapp.Runner, *slog.Logger, error) {
	cfg, err := config.Load()
	if err != nil {
		return nil, nil, err
	}

	logger := observe.NewLogger("runtime", observe.ParseLevel(cfg.LogLevel), cfg.LogFormat)
	objectProvider, err := objectProviderFactory(storage.Config{
		Endpoint:  cfg.MinIOEndpoint,
		AccessKey: cfg.MinIOAccessKey,
		SecretKey: cfg.MinIOSecretKey,
		Bucket:    cfg.MinIOBucketName,
		Secure:    cfg.MinIOSecure,
	})
	if err != nil {
		return nil, nil, err
	}

	runner, err := runtimeapp.New(ctx, runtimeapp.Options{
		Bind:                 cfg.RuntimeBind,
		DatabaseDSN:          cfg.DatabaseDSN,
		SchedulerTargetAgent: cfg.RuntimeSchedulerTargetAgent,
		AssetStoreFactory: func(pool *pgxpool.Pool) assetapp.Store {
			return assetrepo.NewAssetRepo(pool)
		},
		AssetProvider:        objectProvider,
		UploadTicketExpiry:   15 * time.Minute,
		DownloadTicketExpiry: 15 * time.Minute,
	}, logger)
	if err != nil {
		return nil, nil, err
	}

	return runner, logger, nil
}
