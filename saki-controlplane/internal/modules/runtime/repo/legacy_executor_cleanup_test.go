package repo

import (
	"os"
	"path/filepath"
	"runtime"
	"testing"
)

func TestLegacyExecutorRepoRemoved(t *testing.T) {
	_, currentFile, _, ok := runtime.Caller(0)
	if !ok {
		t.Fatal("resolve current file")
	}

	target := filepath.Join(filepath.Dir(currentFile), "executor_repo.go")
	if _, err := os.Stat(target); err == nil {
		// 关键设计：旧 runtime_executor 表的兼容访问若仍留在 repo 主路径，会让人继续从旧真相读写，
		// 这与当前 agent/task_assignment/agent_command 的新真相模型相冲突，因此必须显式收口。
		t.Fatalf("legacy executor repo should be removed: %s", filepath.Base(target))
	} else if !os.IsNotExist(err) {
		t.Fatalf("stat legacy repo: %v", err)
	}
}
