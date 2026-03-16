package apihttp_test

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	systemapi "github.com/elebirds/saki/saki-controlplane/internal/modules/system/apihttp"
)

func TestRuntimeAdminEndpoints(t *testing.T) {
	handler, err := systemapi.NewHTTPHandler()
	if err != nil {
		t.Fatalf("new http handler: %v", err)
	}

	summaryReq := httptest.NewRequest(http.MethodGet, "/runtime/summary", nil)
	summaryRec := httptest.NewRecorder()
	handler.ServeHTTP(summaryRec, summaryReq)

	if summaryRec.Code != http.StatusOK {
		t.Fatalf("unexpected summary status: %d body=%s", summaryRec.Code, summaryRec.Body.String())
	}

	var summary map[string]any
	if err := json.Unmarshal(summaryRec.Body.Bytes(), &summary); err != nil {
		t.Fatalf("decode summary response: %v", err)
	}
	if _, ok := summary["pending_tasks"]; !ok {
		t.Fatalf("unexpected summary body: %+v", summary)
	}

	executorsReq := httptest.NewRequest(http.MethodGet, "/runtime/executors", nil)
	executorsRec := httptest.NewRecorder()
	handler.ServeHTTP(executorsRec, executorsReq)

	if executorsRec.Code != http.StatusOK {
		t.Fatalf("unexpected executors status: %d body=%s", executorsRec.Code, executorsRec.Body.String())
	}

	var executors []map[string]any
	if err := json.Unmarshal(executorsRec.Body.Bytes(), &executors); err != nil {
		t.Fatalf("decode executors response: %v", err)
	}
	if len(executors) != 0 {
		t.Fatalf("expected empty executors list, got %+v", executors)
	}

	commandReq := httptest.NewRequest(http.MethodPost, "/runtime/tasks/task-1/cancel", nil)
	commandRec := httptest.NewRecorder()
	handler.ServeHTTP(commandRec, commandReq)

	if commandRec.Code != http.StatusAccepted {
		t.Fatalf("unexpected command status: %d body=%s", commandRec.Code, commandRec.Body.String())
	}

	var commandResp map[string]any
	if err := json.Unmarshal(commandRec.Body.Bytes(), &commandResp); err != nil {
		t.Fatalf("decode command response: %v", err)
	}
	if commandResp["accepted"] != true {
		t.Fatalf("unexpected command response: %+v", commandResp)
	}
}
