package mapping

import (
	"context"
	"encoding/json"
	"os"
	"testing"
	"time"
)

func TestClientCallsLocalMappingSidecar(t *testing.T) {
	if os.Getenv("SAKI_MAPPING_HELPER_PROCESS") == "1" {
		runMappingHelperProcess()
		return
	}

	client := NewClient(ClientConfig{
		Command: helperCommand(t),
		Env:     append(os.Environ(), "SAKI_MAPPING_HELPER_PROCESS=1"),
		Timeout: 2 * time.Second,
	})

	resp, err := client.MapFedoOBB(context.Background(), MapFedoOBBRequest{
		SourceView: "time-energy",
		TargetView: "L-omegad",
		SourceGeometry: map[string]any{
			"rect": map[string]any{
				"x":      1,
				"y":      2,
				"width":  3,
				"height": 4,
			},
		},
		LookupTable:      []byte("lookup-bytes"),
		TimeGapThreshold: 17,
	})
	if err != nil {
		t.Fatalf("map fedo obb: %v", err)
	}

	if len(resp.MappedGeometries) != 1 {
		t.Fatalf("unexpected mapped geometries: %+v", resp.MappedGeometries)
	}
	rect, ok := resp.MappedGeometries[0]["rect"].(map[string]any)
	if !ok {
		t.Fatalf("expected rect geometry, got %+v", resp.MappedGeometries[0])
	}
	if rect["x"] != float64(10) || rect["width"] != float64(30) {
		t.Fatalf("unexpected mapped rect: %+v", rect)
	}
}

func helperCommand(t *testing.T) []string {
	t.Helper()

	return []string{
		os.Args[0],
		"-test.run=TestClientCallsLocalMappingSidecar",
		"--",
	}
}

func runMappingHelperProcess() {
	req, err := readExecuteRequest(os.Stdin)
	if err != nil {
		panic(err)
	}
	if req.Action != "map_fedo_obb" {
		panic("unexpected action")
	}

	var payload map[string]any
	if err := json.Unmarshal(req.Payload, &payload); err != nil {
		panic(err)
	}
	if payload["source_view"] != "time-energy" || payload["target_view"] != "L-omegad" {
		panic("unexpected views")
	}
	if payload["lookup_table_b64"] != "bG9va3VwLWJ5dGVz" {
		panic("unexpected lookup payload")
	}
	if payload["time_gap_threshold"] != float64(17) {
		panic("unexpected time gap threshold")
	}

	if err := writeExecuteResult(os.Stdout, MapFedoOBBResponse{
		MappedGeometries: []map[string]any{
			{
				"rect": map[string]any{
					"x":      10,
					"y":      20,
					"width":  30,
					"height": 40,
				},
			},
		},
	}); err != nil {
		panic(err)
	}
}
