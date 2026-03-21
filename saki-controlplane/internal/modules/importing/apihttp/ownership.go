package apihttp

import (
	"context"
	"path/filepath"
	"strconv"
	"strings"

	authctx "github.com/elebirds/saki/saki-controlplane/internal/app/auth"
	importrepo "github.com/elebirds/saki/saki-controlplane/internal/modules/importing/repo"
	"github.com/google/uuid"
)

func (h *Handlers) requireEnabled() error {
	if !h.Enabled() {
		return badRequest("import endpoints are not configured")
	}
	return nil
}

func (h *Handlers) loadOwnedUploadSession(ctx context.Context, rawSessionID string) (*importrepo.UploadSession, error) {
	sessionID, err := uuid.Parse(rawSessionID)
	if err != nil {
		return nil, badRequest("invalid session_id")
	}
	principalID, err := currentPrincipalID(ctx)
	if err != nil {
		return nil, err
	}
	session, err := h.uploads.Get(ctx, sessionID)
	if err != nil {
		return nil, err
	}
	if session == nil {
		return nil, notFound("upload session not found")
	}
	if session.UserID != principalID {
		return nil, forbidden("upload session does not belong to current user")
	}
	return session, nil
}

func (h *Handlers) loadOwnedTask(ctx context.Context, rawTaskID string) (*importrepo.ImportTask, error) {
	taskID, err := uuid.Parse(rawTaskID)
	if err != nil {
		return nil, badRequest("invalid task_id")
	}
	principalID, err := currentPrincipalID(ctx)
	if err != nil {
		return nil, err
	}
	task, err := h.tasks.Get(ctx, taskID)
	if err != nil {
		return nil, err
	}
	if task == nil {
		return nil, notFound("import task not found")
	}
	if task.UserID != principalID {
		return nil, forbidden("import task does not belong to current user")
	}
	return task, nil
}

func currentPrincipalID(ctx context.Context) (uuid.UUID, error) {
	claims, ok := authctx.ClaimsFromContext(ctx)
	if !ok {
		return uuid.Nil, unauthorized("authentication required")
	}
	if claims.PrincipalID == uuid.Nil {
		// 关键设计：导入上传/任务归属统一绑定到主体 UUID，
		// 不再依赖 claims 中可能漂移的字符串标识。
		return uuid.Nil, unauthorized("missing principal identity")
	}
	return claims.PrincipalID, nil
}

func sanitizeFilename(name string) string {
	base := filepath.Base(strings.TrimSpace(name))
	if base == "." || base == string(filepath.Separator) || base == "" {
		return "import.zip"
	}
	replacer := strings.NewReplacer("/", "-", "\\", "-", "\x00", "-")
	return replacer.Replace(base)
}

func buildUploadObjectKey(filename string) string {
	return "imports/" + uuid.NewString() + "-" + sanitizeFilename(filename)
}

func parseAfterSeq(raw string) (int64, error) {
	if raw == "" {
		return 0, nil
	}
	return strconv.ParseInt(raw, 10, 64)
}
