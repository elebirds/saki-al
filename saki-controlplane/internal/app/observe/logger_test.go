package observe

import (
	"bytes"
	"log/slog"
	"regexp"
	"strings"
	"testing"
)

func TestNewLoggerIncludesStaticFields(t *testing.T) {
	var buf bytes.Buffer

	logger := newLogger(&buf, "controlplane", "bootstrap", slog.LevelInfo, FormatJSON, false)
	logger.Info("started")

	got := buf.String()
	if !strings.Contains(got, `"service":"controlplane"`) {
		t.Fatalf("expected service field in log output: %s", got)
	}
	if !strings.Contains(got, `"module":"bootstrap"`) {
		t.Fatalf("expected module field in log output: %s", got)
	}
}

func TestResolveFormatAutoUsesConsoleForTTY(t *testing.T) {
	if got := resolveFormat(ParseFormat(""), true); got != FormatConsole {
		t.Fatalf("expected auto format to use console on tty, got %q", got)
	}

	if got := resolveFormat(ParseFormat("auto"), false); got != FormatJSON {
		t.Fatalf("expected auto format to use json off tty, got %q", got)
	}
}

func TestNewLoggerConsoleUsesColoredTextOutput(t *testing.T) {
	var buf bytes.Buffer

	logger := newLogger(&buf, "public-api", "", slog.LevelInfo, FormatConsole, true)
	logger.Info("started", "addr", ":8080")

	got := buf.String()
	if strings.HasPrefix(strings.TrimSpace(got), "{") {
		t.Fatalf("expected console output, got json: %s", got)
	}
	if !strings.Contains(got, "\x1b[") {
		t.Fatalf("expected ansi color codes in console output: %q", got)
	}
	plain := stripANSI(strings.TrimSpace(got))
	if matched := regexp.MustCompile(`^\d{1,2}:\d{2}[AP]M INF started addr=:8080 service=public-api$`).MatchString(plain); !matched {
		t.Fatalf("expected dispatcher-like console output, got %q", plain)
	}
}

var ansiPattern = regexp.MustCompile(`\x1b\[[0-9;]*m`)

func stripANSI(s string) string {
	return ansiPattern.ReplaceAllString(s, "")
}
