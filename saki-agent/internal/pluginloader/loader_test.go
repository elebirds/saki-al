package pluginloader

import (
	"os"
	"path/filepath"
	"testing"
)

func TestLoadFromDir(t *testing.T) {
	root := t.TempDir()
	if err := os.MkdirAll(filepath.Join(root, "example"), 0o755); err != nil {
		t.Fatalf("mkdir failed: %v", err)
	}
	manifest := `id: "example-train"
version: "0.1.0"
display_name: "Example Train"
supported_step_types:
  - "TRAIN"
  - "EVAL"
supported_strategies:
  - "entropy"
capabilities:
  supports_auto_fallback: false
config_schema:
  type: object
default_config:
  epochs: 50
`
	if err := os.WriteFile(filepath.Join(root, "example", "kernel.yaml"), []byte(manifest), 0o644); err != nil {
		t.Fatalf("write manifest failed: %v", err)
	}

	plugins, err := LoadFromDir(root)
	if err != nil {
		t.Fatalf("load plugins failed: %v", err)
	}
	if len(plugins) != 1 {
		t.Fatalf("expected 1 plugin, got %d", len(plugins))
	}
	item := plugins[0]
	if item.ID != "example-train" {
		t.Fatalf("unexpected id: %s", item.ID)
	}
	if item.Version != "0.1.0" {
		t.Fatalf("unexpected version: %s", item.Version)
	}
	if item.DisplayName != "Example Train" {
		t.Fatalf("unexpected display name: %s", item.DisplayName)
	}
	if len(item.SupportedStepTypes) != 2 {
		t.Fatalf("unexpected step types: %+v", item.SupportedStepTypes)
	}
	if item.SupportsAutoFallback {
		t.Fatal("expected supports_auto_fallback=false")
	}
}

func TestLoadFromDirMissingOrEmpty(t *testing.T) {
	plugins, err := LoadFromDir("")
	if err != nil {
		t.Fatalf("unexpected error for empty root: %v", err)
	}
	if len(plugins) != 0 {
		t.Fatalf("expected no plugins for empty root, got %d", len(plugins))
	}

	plugins, err = LoadFromDir(filepath.Join(t.TempDir(), "missing"))
	if err != nil {
		t.Fatalf("unexpected error for missing root: %v", err)
	}
	if len(plugins) != 0 {
		t.Fatalf("expected no plugins for missing root, got %d", len(plugins))
	}
}

func TestLoadFromDirDuplicateID(t *testing.T) {
	root := t.TempDir()
	for _, name := range []string{"a", "b"} {
		dir := filepath.Join(root, name)
		if err := os.MkdirAll(dir, 0o755); err != nil {
			t.Fatalf("mkdir %s failed: %v", dir, err)
		}
		if err := os.WriteFile(filepath.Join(dir, "kernel.yaml"), []byte("id: duplicated\n"), 0o644); err != nil {
			t.Fatalf("write manifest %s failed: %v", dir, err)
		}
	}
	plugins, err := LoadFromDir(root)
	if err == nil {
		t.Fatal("expected duplicate id error")
	}
	if len(plugins) != 1 {
		t.Fatalf("expected 1 plugin kept, got %d", len(plugins))
	}
}
