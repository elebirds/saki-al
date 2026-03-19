package commands

import (
	"os"
	"path/filepath"
	"runtime"
	"testing"
)

func TestLegacyExecutorCommandAdaptersRemoved(t *testing.T) {
	_, currentFile, _, ok := runtime.Caller(0)
	if !ok {
		t.Fatal("resolve current file")
	}

	for _, name := range []string{"register_executor.go", "heartbeat_executor.go"} {
		target := filepath.Join(filepath.Dir(currentFile), name)
		if _, err := os.Stat(target); err == nil {
			// 关键设计：数据库兼容窗口允许保留旧 executor 表，但 controlplane 主链路不能继续保留旧 executor adapter，
			// 否则后续接入者会误以为 executor 仍是当前语义，导致新代码继续长在废弃路径上。
			t.Fatalf("legacy executor command adapter should be removed: %s", name)
		} else if !os.IsNotExist(err) {
			t.Fatalf("stat legacy adapter %s: %v", name, err)
		}
	}
}
