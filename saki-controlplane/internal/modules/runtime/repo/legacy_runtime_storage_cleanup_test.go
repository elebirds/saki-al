package repo

import (
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
)

func TestLegacyRuntimeStorageFilesRemoved(t *testing.T) {
	_, currentFile, _, ok := runtime.Caller(0)
	if !ok {
		t.Fatal("resolve current file")
	}

	root := filepath.Clean(filepath.Join(filepath.Dir(currentFile), "..", "..", "..", ".."))
	for _, target := range []string{
		filepath.Join(filepath.Dir(currentFile), "outbox_repo.go"),
		filepath.Join(root, "db", "queries", "runtime", "outbox.sql"),
		filepath.Join(root, "db", "queries", "runtime", "executor.sql"),
	} {
		if _, err := os.Stat(target); err == nil {
			// 关键设计：agent_command/agent 已经成为 controlplane 的运行时真相后，
			// 旧 runtime_outbox/runtime_executor 的主路径文件若继续存在，就会持续诱导新代码回写旧表。
			t.Fatalf("legacy runtime storage file should be removed: %s", target)
		} else if !os.IsNotExist(err) {
			t.Fatalf("stat %s: %v", target, err)
		}
	}
}

func TestLegacyRuntimeExecutorTypeRegistrationRemoved(t *testing.T) {
	_, currentFile, _, ok := runtime.Caller(0)
	if !ok {
		t.Fatal("resolve current file")
	}

	root := filepath.Clean(filepath.Join(filepath.Dir(currentFile), "..", "..", "..", ".."))
	poolFile := filepath.Join(root, "internal", "app", "db", "pool.go")
	content, err := os.ReadFile(poolFile)
	if err != nil {
		t.Fatalf("read pool.go: %v", err)
	}

	if strings.Contains(string(content), "runtime_executor_status") {
		// 关键设计：旧枚举类型注册一旦残留，后续 sqlc 或 repo 很容易继续偷偷依赖 runtime_executor。
		t.Fatalf("legacy runtime_executor_status registration should be removed from %s", poolFile)
	}
}
