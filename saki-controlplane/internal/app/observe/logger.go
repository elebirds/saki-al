package observe

import (
	"io"
	"log/slog"
	"os"
	"strings"
)

func ParseLevel(level string) slog.Level {
	switch strings.ToUpper(level) {
	case "DEBUG":
		return slog.LevelDebug
	case "WARN":
		return slog.LevelWarn
	case "ERROR":
		return slog.LevelError
	default:
		return slog.LevelInfo
	}
}

func NewLogger(service string, level slog.Leveler) *slog.Logger {
	return newLogger(os.Stdout, service, "", level, true)
}

func newLogger(w io.Writer, service, module string, level slog.Leveler, json bool) *slog.Logger {
	var handler slog.Handler
	options := &slog.HandlerOptions{Level: level}
	if json {
		handler = slog.NewJSONHandler(w, options)
	} else {
		handler = slog.NewTextHandler(w, options)
	}

	logger := slog.New(handler).With("service", service)
	if module != "" {
		logger = logger.With("module", module)
	}
	return logger
}
