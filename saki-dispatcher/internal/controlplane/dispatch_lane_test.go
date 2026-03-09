package controlplane

import (
	"testing"
	"time"

	"github.com/google/uuid"
)

func TestSelectDispatchPassPrefersAgedLaneWithinDispatchClass(t *testing.T) {
	now := time.Now().UTC()
	service := &Service{
		laneState: map[string]dispatchLaneState{
			"lane-a": {SkipRounds: 1, LastDispatchAt: now.Add(-2 * time.Hour)},
			"lane-b": {SkipRounds: 4, LastDispatchAt: now.Add(-1 * time.Hour)},
			"lane-c": {SkipRounds: 4, LastDispatchAt: now.Add(-30 * time.Minute)},
		},
	}

	selected := service.selectDispatchPass([]dispatchLaneCandidate{
		{
			TaskID:        uuid.New(),
			LaneID:        "lane-a",
			DispatchClass: "demo|gpu",
			ReadyAt:       now.Add(-3 * time.Minute),
			IsReady:       true,
		},
		{
			TaskID:        uuid.New(),
			LaneID:        "lane-b",
			DispatchClass: "demo|gpu",
			ReadyAt:       now.Add(-2 * time.Minute),
			IsReady:       true,
		},
		{
			TaskID:        uuid.New(),
			LaneID:        "lane-c",
			DispatchClass: "demo|gpu",
			ReadyAt:       now.Add(-1 * time.Minute),
			IsReady:       true,
		},
	}, 3)

	if len(selected) != 3 {
		t.Fatalf("selected length mismatch: got=%d", len(selected))
	}
	if selected[0].LaneID != "lane-b" {
		t.Fatalf("expected highest aged lane first, got=%q", selected[0].LaneID)
	}
	if selected[1].LaneID != "lane-c" {
		t.Fatalf("expected second highest aged lane second, got=%q", selected[1].LaneID)
	}
	if selected[2].LaneID != "lane-a" {
		t.Fatalf("expected least aged lane last, got=%q", selected[2].LaneID)
	}
}

func TestSelectDispatchPassRoundRobinAcrossDispatchClasses(t *testing.T) {
	now := time.Now().UTC()
	service := &Service{
		laneState: map[string]dispatchLaneState{
			"loop-a":       {SkipRounds: 3, LastDispatchAt: now.Add(-4 * time.Hour)},
			"prediction-a": {SkipRounds: 2, LastDispatchAt: now.Add(-3 * time.Hour)},
			"loop-b":       {SkipRounds: 1, LastDispatchAt: now.Add(-2 * time.Hour)},
			"prediction-b": {SkipRounds: 0, LastDispatchAt: now.Add(-1 * time.Hour)},
		},
	}

	selected := service.selectDispatchPass([]dispatchLaneCandidate{
		{
			TaskID:        uuid.New(),
			LaneID:        "loop-b",
			DispatchClass: "a|gpu",
			ReadyAt:       now.Add(-1 * time.Minute),
			IsReady:       true,
		},
		{
			TaskID:        uuid.New(),
			LaneID:        "loop-a",
			DispatchClass: "a|gpu",
			ReadyAt:       now.Add(-2 * time.Minute),
			IsReady:       true,
		},
		{
			TaskID:        uuid.New(),
			LaneID:        "prediction-b",
			DispatchClass: "b|gpu",
			ReadyAt:       now.Add(-1 * time.Minute),
			IsReady:       true,
		},
		{
			TaskID:        uuid.New(),
			LaneID:        "prediction-a",
			DispatchClass: "b|gpu",
			ReadyAt:       now.Add(-2 * time.Minute),
			IsReady:       true,
		},
	}, 4)

	if len(selected) != 4 {
		t.Fatalf("selected length mismatch: got=%d", len(selected))
	}

	got := []string{selected[0].LaneID, selected[1].LaneID, selected[2].LaneID, selected[3].LaneID}
	want := []string{"loop-a", "prediction-a", "loop-b", "prediction-b"}
	for idx := range want {
		if got[idx] != want[idx] {
			t.Fatalf("round-robin order mismatch at %d: got=%q want=%q", idx, got[idx], want[idx])
		}
	}
}
