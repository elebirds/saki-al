package pluginloader

import (
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"github.com/spf13/cast"
	"gopkg.in/yaml.v3"
)

type PluginSpec struct {
	ID                   string
	Version              string
	DisplayName          string
	SupportedStepTypes   []string
	SupportedStrategies  []string
	RequestConfigSchema  map[string]any
	DefaultRequestConfig map[string]any
	SupportsAutoFallback bool
	SourcePath           string
}

type kernelManifest struct {
	ID                  string         `yaml:"id"`
	Version             string         `yaml:"version"`
	DisplayName         string         `yaml:"display_name"`
	SupportedStepTypes  []string       `yaml:"supported_step_types"`
	SupportedStrategies []string       `yaml:"supported_strategies"`
	ConfigSchema        map[string]any `yaml:"config_schema"`
	DefaultConfig       map[string]any `yaml:"default_config"`
	Capabilities        map[string]any `yaml:"capabilities"`
}

const (
	kernelYAML = "kernel.yaml"
	kernelYML  = "kernel.yml"
)

func LoadFromDir(root string) ([]PluginSpec, error) {
	root = strings.TrimSpace(root)
	if root == "" {
		return nil, nil
	}
	info, err := os.Stat(root)
	if err != nil {
		if os.IsNotExist(err) {
			return nil, nil
		}
		return nil, err
	}
	if !info.IsDir() {
		return nil, fmt.Errorf("kernels dir is not a directory: %s", root)
	}

	manifestFiles := []string{}
	walkErr := filepath.WalkDir(root, func(path string, d os.DirEntry, walkErr error) error {
		if walkErr != nil {
			return walkErr
		}
		if d.IsDir() {
			switch d.Name() {
			case ".git", ".venv", "__pycache__":
				return filepath.SkipDir
			}
			return nil
		}
		name := strings.ToLower(strings.TrimSpace(d.Name()))
		if name == kernelYAML || name == kernelYML {
			manifestFiles = append(manifestFiles, path)
		}
		return nil
	})
	if walkErr != nil {
		return nil, walkErr
	}
	sort.Strings(manifestFiles)

	plugins := make([]PluginSpec, 0, len(manifestFiles))
	seen := make(map[string]struct{})
	var firstErr error
	for _, file := range manifestFiles {
		spec, parseErr := parseKernelManifest(file)
		if parseErr != nil {
			if firstErr == nil {
				firstErr = parseErr
			}
			continue
		}
		if _, exists := seen[spec.ID]; exists {
			if firstErr == nil {
				firstErr = fmt.Errorf("duplicated plugin id %q in kernels dir", spec.ID)
			}
			continue
		}
		seen[spec.ID] = struct{}{}
		plugins = append(plugins, spec)
	}

	sort.Slice(plugins, func(i, j int) bool {
		return plugins[i].ID < plugins[j].ID
	})
	return plugins, firstErr
}

func parseKernelManifest(path string) (PluginSpec, error) {
	content, err := os.ReadFile(path)
	if err != nil {
		return PluginSpec{}, err
	}
	manifest := kernelManifest{}
	if err := yaml.Unmarshal(content, &manifest); err != nil {
		return PluginSpec{}, fmt.Errorf("parse %s: %w", path, err)
	}
	id := strings.TrimSpace(manifest.ID)
	if id == "" {
		return PluginSpec{}, fmt.Errorf("invalid %s: missing id", path)
	}
	version := strings.TrimSpace(manifest.Version)
	if version == "" {
		version = "dev"
	}
	displayName := strings.TrimSpace(manifest.DisplayName)
	if displayName == "" {
		displayName = id
	}
	spec := PluginSpec{
		ID:                   id,
		Version:              version,
		DisplayName:          displayName,
		SupportedStepTypes:   normalizeStrings(manifest.SupportedStepTypes),
		SupportedStrategies:  normalizeStrings(manifest.SupportedStrategies),
		RequestConfigSchema:  cloneMap(manifest.ConfigSchema),
		DefaultRequestConfig: cloneMap(manifest.DefaultConfig),
		SupportsAutoFallback: true,
		SourcePath:           path,
	}
	if len(spec.SupportedStepTypes) == 0 {
		spec.SupportedStepTypes = []string{"TRAIN"}
	}
	if len(spec.SupportedStrategies) == 0 {
		spec.SupportedStrategies = []string{"uncertainty", "entropy", "random"}
	}
	if value, ok := manifest.Capabilities["supports_auto_fallback"]; ok {
		if parsed, err := cast.ToBoolE(value); err == nil {
			spec.SupportsAutoFallback = parsed
		}
	}
	return spec, nil
}

func normalizeStrings(items []string) []string {
	if len(items) == 0 {
		return nil
	}
	set := make(map[string]struct{})
	out := make([]string, 0, len(items))
	for _, item := range items {
		normalized := strings.TrimSpace(item)
		if normalized == "" {
			continue
		}
		if _, exists := set[normalized]; exists {
			continue
		}
		set[normalized] = struct{}{}
		out = append(out, normalized)
	}
	return out
}

func cloneMap(input map[string]any) map[string]any {
	if len(input) == 0 {
		return map[string]any{}
	}
	out := make(map[string]any, len(input))
	for key, value := range input {
		out[key] = value
	}
	return out
}
