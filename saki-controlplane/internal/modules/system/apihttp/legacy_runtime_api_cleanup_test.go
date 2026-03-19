package apihttp

import (
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
)

func TestLegacyRuntimeExecutorsPublicAliasRemoved(t *testing.T) {
	_, currentFile, _, ok := runtime.Caller(0)
	if !ok {
		t.Fatal("resolve current file")
	}

	root := filepath.Clean(filepath.Join(filepath.Dir(currentFile), "..", "..", "..", ".."))
	for _, target := range []string{
		filepath.Join(filepath.Dir(currentFile), "server.go"),
		filepath.Join(root, "api", "openapi", "public-api.yaml"),
	} {
		content, err := os.ReadFile(target)
		if err != nil {
			t.Fatalf("read %s: %v", target, err)
		}

		if strings.Contains(string(content), "/runtime/executors") || strings.Contains(string(content), "ListRuntimeExecutors") {
			// 关键设计：兼容 alias 的生命周期必须明确结束；否则 public-api 会长期同时暴露 agent/executor 两套名词，
			// 让调用方无法判断哪一套才是当前 contract。
			t.Fatalf("legacy runtime executors alias should be removed from %s", target)
		}
	}
}
