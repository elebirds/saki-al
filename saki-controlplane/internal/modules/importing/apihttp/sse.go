package apihttp

import (
	"encoding/json"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"time"

	openapi "github.com/elebirds/saki/saki-controlplane/internal/gen/openapi"
	"github.com/google/uuid"
)

func (h *Handlers) TryServeHTTP(w http.ResponseWriter, r *http.Request) bool {
	if !h.Enabled() {
		return false
	}
	if r.Method == http.MethodPut {
		if sessionID, ok := matchUploadContentPath(r.URL.Path); ok {
			h.serveUploadContent(w, r, sessionID)
			return true
		}
	}
	if r.Method == http.MethodGet {
		if taskID, ok := matchTaskEventsPath(r.URL.Path); ok {
			h.serveTaskEvents(w, r, taskID)
			return true
		}
	}
	return false
}

func (h *Handlers) serveUploadContent(w http.ResponseWriter, r *http.Request, rawSessionID string) {
	sessionID, err := parseUUIDOrWrite(w, rawSessionID, "invalid session_id")
	if err != nil {
		return
	}
	session, err := h.uploads.Get(r.Context(), sessionID)
	if err != nil {
		writeManualError(w, http.StatusInternalServerError, "internal_error", "internal server error")
		return
	}
	if session == nil {
		writeManualError(w, http.StatusNotFound, "not_found", "upload session not found")
		return
	}
	if session.Status == "aborted" {
		writeManualError(w, http.StatusBadRequest, "bad_request", "upload session is aborted")
		return
	}
	if err := os.MkdirAll(filepath.Dir(session.ObjectKey), 0o755); err != nil {
		writeManualError(w, http.StatusInternalServerError, "internal_error", "failed to prepare upload path")
		return
	}
	file, err := os.OpenFile(session.ObjectKey, os.O_CREATE|os.O_TRUNC|os.O_WRONLY, 0o644)
	if err != nil {
		writeManualError(w, http.StatusInternalServerError, "internal_error", "failed to create upload file")
		return
	}
	_, copyErr := io.Copy(file, r.Body)
	closeErr := file.Close()
	if copyErr != nil {
		writeManualError(w, http.StatusInternalServerError, "internal_error", "failed to write upload content")
		return
	}
	if closeErr != nil {
		writeManualError(w, http.StatusInternalServerError, "internal_error", "failed to finalize upload content")
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

func (h *Handlers) serveTaskEvents(w http.ResponseWriter, r *http.Request, rawTaskID string) {
	task, err := h.loadOwnedTask(r.Context(), rawTaskID)
	if err != nil {
		writeOpenAPIError(w, err)
		return
	}
	afterSeq, err := parseAfterSeq(r.URL.Query().Get("after_seq"))
	if err != nil {
		writeManualError(w, http.StatusBadRequest, "bad_request", "invalid after_seq")
		return
	}
	events, err := h.tasks.ListEventsAfter(r.Context(), task.ID, afterSeq, 1024)
	if err != nil {
		writeManualError(w, http.StatusInternalServerError, "internal_error", "internal server error")
		return
	}

	w.Header().Set("Content-Type", "text/event-stream; charset=utf-8")
	w.Header().Set("Cache-Control", "no-cache")
	w.Header().Set("Connection", "keep-alive")
	flusher, _ := w.(http.Flusher)

	encoder := json.NewEncoder(w)
	for _, event := range events {
		payload := map[string]any{}
		if len(event.Payload) > 0 {
			_ = json.Unmarshal(event.Payload, &payload)
		}
		sseEvent := map[string]any{
			"seq":    event.Seq,
			"ts":     event.CreatedAt.UTC().Format(time.RFC3339),
			"event":  event.Event,
			"phase":  event.Phase,
			"detail": payload,
		}
		if message, ok := payload["message"].(string); ok && message != "" {
			sseEvent["message"] = message
		}
		_, _ = w.Write([]byte("data: "))
		if err := encoder.Encode(sseEvent); err != nil {
			return
		}
		_, _ = w.Write([]byte("\n"))
		if flusher != nil {
			flusher.Flush()
		}
	}
}

func matchUploadContentPath(path string) (string, bool) {
	const prefix = "/imports/uploads/"
	const suffix = "/content"
	if !strings.HasPrefix(path, prefix) || !strings.HasSuffix(path, suffix) {
		return "", false
	}
	trimmed := strings.TrimSuffix(strings.TrimPrefix(path, prefix), suffix)
	trimmed = strings.Trim(trimmed, "/")
	if trimmed == "" || strings.Contains(trimmed, "/") {
		return "", false
	}
	return trimmed, true
}

func matchTaskEventsPath(path string) (string, bool) {
	const prefix = "/imports/tasks/"
	const suffix = "/events"
	if !strings.HasPrefix(path, prefix) || !strings.HasSuffix(path, suffix) {
		return "", false
	}
	trimmed := strings.TrimSuffix(strings.TrimPrefix(path, prefix), suffix)
	trimmed = strings.Trim(trimmed, "/")
	if trimmed == "" || strings.Contains(trimmed, "/") {
		return "", false
	}
	return trimmed, true
}

func parseUUIDOrWrite(w http.ResponseWriter, raw string, message string) (uuid.UUID, error) {
	id, err := uuid.Parse(raw)
	if err != nil {
		writeManualError(w, http.StatusBadRequest, "bad_request", message)
		return uuid.Nil, err
	}
	return id, nil
}

func writeManualError(w http.ResponseWriter, status int, code string, message string) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(map[string]string{
		"code":    code,
		"message": message,
	})
}

func writeOpenAPIError(w http.ResponseWriter, err error) {
	if mapped, ok := err.(*openapi.ErrorResponseStatusCode); ok {
		w.Header().Set("Content-Type", "application/json; charset=utf-8")
		w.WriteHeader(mapped.StatusCode)
		_ = json.NewEncoder(w).Encode(mapped.Response)
		return
	}
	writeManualError(w, http.StatusInternalServerError, "internal_error", "internal server error")
}
