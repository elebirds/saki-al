package observe

import (
	"bytes"
	"log/slog"
	"strings"
	"testing"
)

func TestNewLoggerIncludesStaticFields(t *testing.T) {
	var buf bytes.Buffer

	logger := newLogger(&buf, "controlplane", "bootstrap", slog.LevelInfo, true)
	logger.Info("started")

	got := buf.String()
	if !strings.Contains(got, `"service":"controlplane"`) {
		t.Fatalf("expected service field in log output: %s", got)
	}
	if !strings.Contains(got, `"module":"bootstrap"`) {
		t.Fatalf("expected module field in log output: %s", got)
	}
}
