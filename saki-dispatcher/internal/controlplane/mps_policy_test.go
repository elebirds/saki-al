package controlplane

import (
	"testing"

	"google.golang.org/protobuf/types/known/structpb"
)

func TestShouldInjectMPSFallback(t *testing.T) {
	t.Run("runtime hints contains mps", func(t *testing.T) {
		hints, _ := structpb.NewStruct(map[string]any{"accelerator": "mps"})
		payload := stepDispatchPayload{RuntimeHints: hints}
		if !shouldInjectMPSFallback(payload) {
			t.Fatal("expected mps fallback injection")
		}
	})

	t.Run("params contains mps", func(t *testing.T) {
		params, _ := structpb.NewStruct(map[string]any{"device": map[string]any{"type": "MPS"}})
		payload := stepDispatchPayload{Params: params}
		if !shouldInjectMPSFallback(payload) {
			t.Fatal("expected mps fallback injection")
		}
	})

	t.Run("no mps signal", func(t *testing.T) {
		params, _ := structpb.NewStruct(map[string]any{"accelerator": "cuda"})
		payload := stepDispatchPayload{Params: params}
		if shouldInjectMPSFallback(payload) {
			t.Fatal("did not expect mps fallback injection")
		}
	})
}
