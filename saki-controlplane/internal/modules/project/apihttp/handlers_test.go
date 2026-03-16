package apihttp_test

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	systemapi "github.com/elebirds/saki/saki-controlplane/internal/modules/system/apihttp"
)

func TestCreateListAndGetProjectEndpoints(t *testing.T) {
	handler, err := systemapi.NewHTTPHandler()
	if err != nil {
		t.Fatalf("new http handler: %v", err)
	}

	createReq := httptest.NewRequest(http.MethodPost, "/projects", bytes.NewBufferString(`{"name":"alpha"}`))
	createReq.Header.Set("Content-Type", "application/json")
	createRec := httptest.NewRecorder()
	handler.ServeHTTP(createRec, createReq)

	if createRec.Code != http.StatusCreated {
		t.Fatalf("unexpected create status: %d body=%s", createRec.Code, createRec.Body.String())
	}

	var created struct {
		ID   string `json:"id"`
		Name string `json:"name"`
	}
	if err := json.Unmarshal(createRec.Body.Bytes(), &created); err != nil {
		t.Fatalf("decode create response: %v", err)
	}
	if created.ID == "" || created.Name != "alpha" {
		t.Fatalf("unexpected created project: %+v", created)
	}

	listReq := httptest.NewRequest(http.MethodGet, "/projects", nil)
	listRec := httptest.NewRecorder()
	handler.ServeHTTP(listRec, listReq)

	if listRec.Code != http.StatusOK {
		t.Fatalf("unexpected list status: %d body=%s", listRec.Code, listRec.Body.String())
	}

	var listed []map[string]any
	if err := json.Unmarshal(listRec.Body.Bytes(), &listed); err != nil {
		t.Fatalf("decode list response: %v", err)
	}
	if len(listed) != 1 || listed[0]["id"] != created.ID {
		t.Fatalf("unexpected listed projects: %+v", listed)
	}

	getReq := httptest.NewRequest(http.MethodGet, "/projects/"+created.ID, nil)
	getRec := httptest.NewRecorder()
	handler.ServeHTTP(getRec, getReq)

	if getRec.Code != http.StatusOK {
		t.Fatalf("unexpected get status: %d body=%s", getRec.Code, getRec.Body.String())
	}

	var loaded map[string]any
	if err := json.Unmarshal(getRec.Body.Bytes(), &loaded); err != nil {
		t.Fatalf("decode get response: %v", err)
	}
	if loaded["id"] != created.ID || loaded["name"] != "alpha" {
		t.Fatalf("unexpected loaded project: %+v", loaded)
	}
}
