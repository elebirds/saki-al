package apihttp

import (
	"context"
	"encoding/json"
	"fmt"

	openapi "github.com/elebirds/saki/saki-controlplane/internal/gen/openapi"
	importapp "github.com/elebirds/saki/saki-controlplane/internal/modules/importing/app"
	importrepo "github.com/elebirds/saki/saki-controlplane/internal/modules/importing/repo"
	"github.com/go-faster/jx"
)

func toOpenAPIIssues(issues []importapp.PrepareIssue) []openapi.ImportIssue {
	result := make([]openapi.ImportIssue, 0, len(issues))
	for _, issue := range issues {
		result = append(result, openapi.ImportIssue{
			Code:    issue.Code,
			Message: issue.Message,
		})
	}
	return result
}

func (h *Handlers) toOpenAPIUploadSession(ctx context.Context, session *importrepo.UploadSession) (*openapi.ImportUploadSession, error) {
	putURL := ""
	if session.Status == "initiated" {
		signed, err := h.provider.SignPutObject(ctx, session.ObjectKey, h.uploadExpiry, session.ContentType)
		if err != nil {
			return nil, err
		}
		putURL = signed
	}
	response := &openapi.ImportUploadSession{
		SessionID:   session.ID.String(),
		Mode:        session.Mode,
		FileName:    session.FileName,
		ObjectKey:   session.ObjectKey,
		ContentType: session.ContentType,
		Status:      session.Status,
		Strategy:    "single_put",
		URL:         putURL,
	}
	if session.CompletedAt != nil {
		response.CompletedAt.SetTo(*session.CompletedAt)
	}
	if session.AbortedAt != nil {
		response.AbortedAt.SetTo(*session.AbortedAt)
	}
	return response, nil
}

func toOpenAPITaskCreate(task *importrepo.ImportTask) *openapi.ImportTaskCreateResponse {
	taskID := task.ID.String()
	return &openapi.ImportTaskCreateResponse{
		TaskID:    taskID,
		Status:    task.Status,
		StatusURL: "/imports/tasks/" + taskID,
		ResultURL: "/imports/tasks/" + taskID + "/result",
		StreamURL: "/imports/tasks/" + taskID + "/events",
	}
}

func decodeRawObject(raw []byte) (openapi.ImportTaskResultResponseResult, error) {
	if len(raw) == 0 {
		return openapi.ImportTaskResultResponseResult{}, nil
	}
	decoded := map[string]json.RawMessage{}
	if err := json.Unmarshal(raw, &decoded); err != nil {
		return nil, fmt.Errorf("decode raw object: %w", err)
	}
	result := openapi.ImportTaskResultResponseResult{}
	for key, value := range decoded {
		result[key] = jx.Raw(value)
	}
	return result, nil
}
