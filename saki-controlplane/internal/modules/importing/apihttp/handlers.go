package apihttp

import (
	"context"
	"time"

	"github.com/elebirds/saki/saki-controlplane/internal/app/storage"
	importapp "github.com/elebirds/saki/saki-controlplane/internal/modules/importing/app"
	importrepo "github.com/elebirds/saki/saki-controlplane/internal/modules/importing/repo"
	"github.com/google/uuid"
)

type UploadStore interface {
	Init(ctx context.Context, params importrepo.InitUploadSessionParams) (*importrepo.UploadSession, error)
	Get(ctx context.Context, id uuid.UUID) (*importrepo.UploadSession, error)
	MarkCompleted(ctx context.Context, id uuid.UUID) (*importrepo.UploadSession, error)
	Abort(ctx context.Context, id uuid.UUID) (*importrepo.UploadSession, error)
}

type TaskStore interface {
	Get(ctx context.Context, id uuid.UUID) (*importrepo.ImportTask, error)
	ListEventsAfter(ctx context.Context, taskID uuid.UUID, afterSeq int64, limit int32) ([]importrepo.ImportTaskEvent, error)
}

type PrepareUseCase interface {
	Execute(ctx context.Context, input importapp.PrepareProjectAnnotationsInput) (*importapp.PrepareProjectAnnotationsResult, error)
}

type ExecuteUseCase interface {
	Execute(ctx context.Context, input importapp.ExecuteProjectAnnotationsInput) (*importrepo.ImportTask, error)
}

type Dependencies struct {
	Uploads         UploadStore
	Tasks           TaskStore
	Prepare         PrepareUseCase
	Execute         ExecuteUseCase
	Provider        storage.Provider
	UploadURLExpiry time.Duration
}

type Handlers struct {
	uploads      UploadStore
	tasks        TaskStore
	prepare      PrepareUseCase
	execute      ExecuteUseCase
	provider     storage.Provider
	uploadExpiry time.Duration
}

// 关键设计：importing transport 入口只保留依赖装配与能力开关。
// 上传会话流、导入执行流、SSE 事件流分别拆开，避免一个 handlers.go 同时承担三类协议边界。
func NewHandlers(deps Dependencies) *Handlers {
	expiry := deps.UploadURLExpiry
	if expiry <= 0 {
		expiry = 15 * time.Minute
	}
	return &Handlers{
		uploads:      deps.Uploads,
		tasks:        deps.Tasks,
		prepare:      deps.Prepare,
		execute:      deps.Execute,
		provider:     deps.Provider,
		uploadExpiry: expiry,
	}
}

func (h *Handlers) Enabled() bool {
	return h != nil && h.uploads != nil && h.tasks != nil && h.prepare != nil && h.execute != nil && h.provider != nil
}
