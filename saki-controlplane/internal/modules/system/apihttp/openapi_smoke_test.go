package apihttp_test

import (
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/elebirds/saki/saki-controlplane/internal/app/bootstrap"
)

func TestPublicAPISmoke(t *testing.T) {
	server, _, err := bootstrap.NewPublicAPI(context.Background())
	if err != nil {
		t.Fatalf("bootstrap public api: %v", err)
	}

	httpServer := httptest.NewServer(server.Handler)
	defer httpServer.Close()

	resp, err := http.Get(httpServer.URL + "/healthz")
	if err != nil {
		t.Fatalf("get healthz: %v", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("unexpected healthz status: %d", resp.StatusCode)
	}

	loginResp, err := http.Post(
		httpServer.URL+"/auth/login",
		"application/json",
		bytes.NewBufferString(`{"user_id":"smoke-user","permissions":["projects:read"]}`),
	)
	if err != nil {
		t.Fatalf("post login: %v", err)
	}
	defer loginResp.Body.Close()
	if loginResp.StatusCode != http.StatusOK {
		t.Fatalf("unexpected login status: %d", loginResp.StatusCode)
	}

	summaryResp, err := http.Get(httpServer.URL + "/runtime/summary")
	if err != nil {
		t.Fatalf("get runtime summary: %v", err)
	}
	defer summaryResp.Body.Close()
	if summaryResp.StatusCode != http.StatusOK {
		t.Fatalf("unexpected runtime summary status: %d", summaryResp.StatusCode)
	}

	var summary map[string]any
	if err := json.NewDecoder(summaryResp.Body).Decode(&summary); err != nil {
		t.Fatalf("decode runtime summary: %v", err)
	}
	if _, ok := summary["pending_tasks"]; !ok {
		t.Fatalf("unexpected runtime summary body: %+v", summary)
	}
}
