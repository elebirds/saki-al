package bootstrap

import (
	"context"
	"log/slog"
	"net/http"
	"strings"
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
)

var objectProviderFactory = storage.NewMinIOProvider
var assetCleanerLoopFactory = func(staleStore assetapp.StalePendingStore, readyStore assetapp.ReadyOrphanStore, readyTx assetapp.ReadyOrphanTxRunner, provider storage.Provider, logger *slog.Logger, readyRetentionWindow time.Duration) backgroundLoop {
	staleCleaner := assetapp.NewStalePendingCleaner(staleStore, provider, assetapp.StalePendingCleanerConfig{
		UploadGraceWindow: 30 * time.Minute,
	})
	readyCleaner := assetapp.NewReadyOrphanCleaner(readyStore, readyTx, provider, assetapp.ReadyOrphanCleanerConfig{
		RetentionWindow: readyRetentionWindow,
	})
	return newBackgroundPollingLoop("asset-cleaner", 5*time.Minute, logger, func(ctx context.Context) error {
		var firstErr error
		if err := staleCleaner.RunOnce(ctx); err != nil && firstErr == nil {
			firstErr = err
		}
		if err := readyCleaner.RunOnce(ctx); err != nil && firstErr == nil {
			firstErr = err
		}
		return firstErr
	})
}

type backgroundLoop interface {
	Run(ctx context.Context) error
}

type backgroundLoopFunc func(ctx context.Context) error

func (f backgroundLoopFunc) Run(ctx context.Context) error {
	return f(ctx)
}

func hasObjectStorageConfig(cfg config.Config) bool {
	return strings.TrimSpace(cfg.MinIOEndpoint) != "" ||
		strings.TrimSpace(cfg.MinIOAccessKey) != "" ||
		strings.TrimSpace(cfg.MinIOSecretKey) != "" ||
		strings.TrimSpace(cfg.MinIOBucketName) != ""
}

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
	readyRetentionWindow, err := time.ParseDuration(cfg.AssetReadyRetentionWindow)
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
	var objectProvider storage.Provider
	if hasObjectStorageConfig(cfg) {
		objectProvider, err = objectProviderFactory(storage.Config{
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
	}

	sampleRepo := annotationrepo.NewSampleRepo(pool)
	annotationRepo := annotationrepo.NewAnnotationRepo(pool)
	assetStore := assetrepo.NewAssetRepo(pool)
	assetReadStore := assetapp.NewRepoStore(assetStore)
	assetIntentStore := assetapp.NewRepoIntentStore(assetrepo.NewAssetUploadIntentRepo(pool))
	assetReadyOrphanStore := assetapp.NewRepoReadyOrphanStore(assetStore)
	assetReadyOrphanTx := assetapp.NewRepoReadyOrphanTxRunner(assetrepo.NewReadyOrphanGCTxRunner(pool))
	durableUploadConfig := assetapp.DurableUploadConfig{
		UploadURLExpiry:    15 * time.Minute,
		IntentTTL:          15 * time.Minute,
		UploadGraceWindow:  30 * time.Minute,
		MaxObjectKeyTrials: 3,
	}
	assetDurableTx := assetapp.NewRepoDurableUploadTxRunner(assetrepo.NewDurableUploadTxRunner(pool))
	datasetRepo := datasetrepo.NewDatasetRepo(pool)
	datasetStore := datasetapp.NewRepoStore(datasetRepo)
	datasetDelete := datasetapp.NewDeleteDatasetUseCaseWithTx(
		datasetapp.NewRepoDeleteDatasetTxRunner(datasetrepo.NewDeleteDatasetTxRunner(pool)),
	)
	sampleDelete := datasetapp.NewDeleteSampleUseCaseWithTx(
		datasetapp.NewRepoDeleteSampleTxRunner(datasetrepo.NewDeleteSampleTxRunner(pool)),
	)
	projectRepo := projectrepo.NewProjectRepo(pool)
	projectStore := projectapp.NewRepoStore(projectRepo)
	importUploadRepo := importrepo.NewUploadRepo(pool)
	importPreviewRepo := importrepo.NewPreviewRepo(pool)
	importTaskRepo := importrepo.NewTaskRepo(pool)
	importMatchRepo := importrepo.NewSampleMatchRefRepo(pool)
	var importDeps importapi.Dependencies
	if objectProvider != nil {
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
		importDeps = importapi.Dependencies{
			Uploads:         importUploadRepo,
			Tasks:           importTaskRepo,
			Prepare:         importPrepare,
			Execute:         importExecute,
			Provider:        objectProvider,
			UploadURLExpiry: 15 * time.Minute,
		}
	}

	handler, err := systemapi.NewHTTPHandler(systemapi.Dependencies{
		Authenticator:       accessapp.NewAuthenticator(cfg.AuthTokenSecret, tokenTTL).WithStore(accessStore),
		AccessStore:         accessStore,
		DatasetStore:        datasetStore,
		DatasetDelete:       datasetDelete,
		DatasetDeleteSample: sampleDelete,
		ProjectStore:        projectStore,
		RuntimeStore:        runtimequeries.NewRepoAdminStore(taskRepo, runtimerepo.NewAgentRepo(pool)),
		RuntimeTaskCanceler: runtimecommands.NewCancelTaskHandlerWithTx(runtimerepo.NewCancelTaskTxRunner(pool)),
		AnnotationSamples:   sampleRepo,
		AnnotationDatasets:  datasetRepo,
		AnnotationStore:     annotationRepo,
		Asset: assetapi.Dependencies{
			Store:           assetReadStore,
			IntentStore:     assetIntentStore,
			InitUpload:      assetapp.NewInitDurableUploadUseCase(assetDurableTx, objectProvider, durableUploadConfig),
			CompleteUpload:  assetapp.NewCompleteDurableUploadUseCase(assetDurableTx, objectProvider, durableUploadConfig),
			CancelUpload:    assetapp.NewCancelDurableUploadUseCase(assetDurableTx, durableUploadConfig),
			Provider:        objectProvider,
			UploadURLExpiry: durableUploadConfig.UploadURLExpiry,
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
			Uploads:         importDeps.Uploads,
			Tasks:           importDeps.Tasks,
			Prepare:         importDeps.Prepare,
			Execute:         importDeps.Execute,
			Provider:        importDeps.Provider,
			UploadURLExpiry: importDeps.UploadURLExpiry,
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
	cleanerCtx, cancelCleaner := context.WithCancel(ctx)
	if objectProvider != nil {
		cleanerLoop := assetCleanerLoopFactory(
			assetapp.NewRepoStalePendingStore(assetStore),
			assetReadyOrphanStore,
			assetReadyOrphanTx,
			objectProvider,
			logger,
			readyRetentionWindow,
		)
		if cleanerLoop != nil {
			go func() {
				if err := cleanerLoop.Run(cleanerCtx); err != nil && cleanerCtx.Err() == nil {
					logger.Error("asset cleaner loop failed", "err", err)
				}
			}()
		}
	}
	server.RegisterOnShutdown(func() {
		cancelCleaner()
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
		Roles:                runtimeapp.NewRoleSet(cfg.RuntimeRoles...),
		DatabaseDSN:          cfg.DatabaseDSN,
		SchedulerTargetAgent: cfg.RuntimeSchedulerTargetAgent,
		AgentControlBaseURL:  cfg.RuntimeAgentControlBaseURL,
		AssetProvider:        objectProvider,
		UploadTicketExpiry:   15 * time.Minute,
		DownloadTicketExpiry: 15 * time.Minute,
	}, logger)
	if err != nil {
		return nil, nil, err
	}

	return runner, logger, nil
}

func newBackgroundPollingLoop(name string, interval time.Duration, logger *slog.Logger, runOnce func(ctx context.Context) error) backgroundLoop {
	log := logger
	if log == nil {
		log = slog.Default()
	}
	if interval <= 0 {
		interval = 5 * time.Minute
	}
	if runOnce == nil {
		return backgroundLoopFunc(func(context.Context) error { return nil })
	}

	return backgroundLoopFunc(func(ctx context.Context) error {
		if err := runOnce(ctx); err != nil && ctx.Err() == nil {
			log.Error("background loop tick failed", "loop", name, "err", err)
		}

		ticker := time.NewTicker(interval)
		defer ticker.Stop()

		for {
			select {
			case <-ctx.Done():
				return nil
			case <-ticker.C:
				if err := runOnce(ctx); err != nil && ctx.Err() == nil {
					log.Error("background loop tick failed", "loop", name, "err", err)
				}
			}
		}
	})
}
