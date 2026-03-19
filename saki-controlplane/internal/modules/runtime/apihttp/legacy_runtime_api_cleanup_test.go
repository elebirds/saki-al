package apihttp

import (
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
)

func TestLegacyRuntimeExecutorsHandlerRemoved(t *testing.T) {
	_, currentFile, _, ok := runtime.Caller(0)
	if !ok {
		t.Fatal("resolve current file")
	}

	target := filepath.Join(filepath.Dir(currentFile), "handlers.go")
	content, err := os.ReadFile(target)
	if err != nil {
		t.Fatalf("read handlers.go: %v", err)
	}

	if strings.Contains(string(content), "ListRuntimeExecutors") {
		// 关键设计：公开语义已经固定为 runtime agents，兼容 alias 若继续留在 handler 层，
		// 生成代码和调用方就会误以为 executors 仍是正式 API 名词。
		t.Fatalf("legacy runtime executors handler should be removed from %s", target)
	}
}
