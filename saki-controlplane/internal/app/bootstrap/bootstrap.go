package bootstrap

import (
	"context"
	"log/slog"
	"net/http"
	"time"

	"github.com/elebirds/saki/saki-controlplane/internal/app/config"
	appdb "github.com/elebirds/saki/saki-controlplane/internal/app/db"
	"github.com/elebirds/saki/saki-controlplane/internal/app/observe"
	accessapp "github.com/elebirds/saki/saki-controlplane/internal/modules/access/app"
	annotationmapping "github.com/elebirds/saki/saki-controlplane/internal/modules/annotation/app/mapping"
	annotationrepo "github.com/elebirds/saki/saki-controlplane/internal/modules/annotation/repo"
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
	sampleRepo := annotationrepo.NewSampleRepo(pool)
	annotationRepo := annotationrepo.NewAnnotationRepo(pool)
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
	)
	importExecute := importapp.NewExecuteProjectAnnotationsUseCase(
		importPreviewRepo,
		importTaskRepo,
		importapp.NewProjectAnnotationsTaskRunner(annotationRepo, importTaskRepo),
	)

	handler, err := systemapi.NewHTTPHandler(systemapi.Dependencies{
		Authenticator:       accessapp.NewAuthenticator(cfg.AuthTokenSecret, tokenTTL),
		ProjectStore:        projectStore,
		RuntimeStore:        runtimequeries.NewRepoAdminStore(taskRepo, runtimerepo.NewExecutorRepo(pool)),
		RuntimeTaskCanceler: runtimecommands.NewCancelTaskHandlerWithTx(runtimerepo.NewCancelTaskTxRunner(pool)),
		AnnotationSamples:   sampleRepo,
		AnnotationStore:     annotationRepo,
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
			Uploads: importUploadRepo,
			Tasks:   importTaskRepo,
			Prepare: importPrepare,
			Execute: importExecute,
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
	runner, err := runtimeapp.New(ctx, runtimeapp.Options{
		Bind:                 cfg.RuntimeBind,
		DatabaseDSN:          cfg.DatabaseDSN,
		SchedulerTargetAgent: cfg.RuntimeSchedulerTargetAgent,
	}, logger)
	if err != nil {
		return nil, nil, err
	}

	return runner, logger, nil
}
