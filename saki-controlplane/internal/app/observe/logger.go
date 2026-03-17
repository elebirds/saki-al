package observe

import (
	"context"
	"fmt"
	"io"
	"log/slog"
	"os"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"
	"unicode"

	"github.com/mattn/go-isatty"
)

type Format string

const (
	FormatAuto    Format = "auto"
	FormatJSON    Format = "json"
	FormatText    Format = "text"
	FormatConsole Format = "console"
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

func ParseFormat(format string) Format {
	switch strings.ToLower(strings.TrimSpace(format)) {
	case "", string(FormatAuto):
		return FormatAuto
	case string(FormatJSON):
		return FormatJSON
	case string(FormatText):
		return FormatText
	case string(FormatConsole):
		return FormatConsole
	default:
		return FormatAuto
	}
}

func NewLogger(service string, level slog.Leveler, format string) *slog.Logger {
	return newLogger(os.Stdout, service, "", level, ParseFormat(format), isTerminal(os.Stdout))
}

func newLogger(w io.Writer, service, module string, level slog.Leveler, format Format, tty bool) *slog.Logger {
	handler := newHandler(w, level, format, tty)

	logger := slog.New(handler).With("service", service)
	if module != "" {
		logger = logger.With("module", module)
	}
	return logger
}

func resolveFormat(format Format, tty bool) Format {
	switch format {
	case FormatJSON, FormatText, FormatConsole:
		return format
	case FormatAuto:
		if tty {
			return FormatConsole
		}
		return FormatJSON
	default:
		if tty {
			return FormatConsole
		}
		return FormatJSON
	}
}

func newHandler(w io.Writer, level slog.Leveler, format Format, tty bool) slog.Handler {
	options := &slog.HandlerOptions{Level: level}
	switch resolveFormat(format, tty) {
	case FormatConsole:
		return newConsoleHandler(w, level)
	case FormatText:
		return slog.NewTextHandler(w, options)
	default:
		return slog.NewJSONHandler(w, options)
	}
}

func isTerminal(w io.Writer) bool {
	file, ok := w.(*os.File)
	if !ok {
		return false
	}

	fd := file.Fd()
	return isatty.IsTerminal(fd) || isatty.IsCygwinTerminal(fd)
}

type consoleHandler struct {
	w      io.Writer
	level  slog.Leveler
	attrs  []slog.Attr
	groups []string
	mu     *sync.Mutex
}

type consoleField struct {
	key   string
	value slog.Value
}

func newConsoleHandler(w io.Writer, level slog.Leveler) slog.Handler {
	return &consoleHandler{
		w:     w,
		level: level,
		mu:    &sync.Mutex{},
	}
}

func (h *consoleHandler) Enabled(_ context.Context, level slog.Level) bool {
	return level >= minLevel(h.level)
}

func (h *consoleHandler) Handle(_ context.Context, record slog.Record) error {
	attrs := make([]slog.Attr, 0, len(h.attrs)+record.NumAttrs())
	attrs = append(attrs, h.attrs...)
	record.Attrs(func(attr slog.Attr) bool {
		attrs = append(attrs, attr)
		return true
	})

	var b strings.Builder
	if !record.Time.IsZero() {
		b.WriteString(colorize("\x1b[90m", record.Time.Format(time.Kitchen)))
		b.WriteByte(' ')
	}
	b.WriteString(colorize(levelColor(record.Level), levelLabel(record.Level)))
	if record.Message != "" {
		b.WriteByte(' ')
		b.WriteString(formatConsoleMessage(record.Level, record.Message))
	}
	fields := collectConsoleFields(h.groups, attrs)
	sortConsoleFields(fields)
	for _, field := range fields {
		b.WriteByte(' ')
		b.WriteString(formatConsoleFieldName(field.key))
		b.WriteString(formatConsoleValue(field.key, field.value))
	}
	b.WriteByte('\n')

	h.mu.Lock()
	defer h.mu.Unlock()
	_, err := io.WriteString(h.w, b.String())
	return err
}

func (h *consoleHandler) WithAttrs(attrs []slog.Attr) slog.Handler {
	return &consoleHandler{
		w:      h.w,
		level:  h.level,
		attrs:  append(cloneAttrs(h.attrs), attrs...),
		groups: cloneStrings(h.groups),
		mu:     h.mu,
	}
}

func (h *consoleHandler) WithGroup(name string) slog.Handler {
	return &consoleHandler{
		w:      h.w,
		level:  h.level,
		attrs:  cloneAttrs(h.attrs),
		groups: append(cloneStrings(h.groups), name),
		mu:     h.mu,
	}
}

func minLevel(level slog.Leveler) slog.Level {
	if level == nil {
		return slog.LevelInfo
	}
	return level.Level()
}

func collectConsoleFields(prefix []string, attrs []slog.Attr) []consoleField {
	fields := make([]consoleField, 0, len(attrs))
	for _, attr := range attrs {
		fields = appendConsoleField(fields, prefix, attr)
	}
	return fields
}

func appendConsoleField(fields []consoleField, prefix []string, attr slog.Attr) []consoleField {
	attr.Value = attr.Value.Resolve()
	if attr.Equal(slog.Attr{}) {
		return fields
	}

	if attr.Value.Kind() == slog.KindGroup {
		groupPrefix := prefix
		if attr.Key != "" {
			groupPrefix = appendPrefix(prefix, attr.Key)
		}
		for _, item := range attr.Value.Group() {
			fields = appendConsoleField(fields, groupPrefix, item)
		}
		return fields
	}

	key := attr.Key
	if key == "" {
		return fields
	}
	if len(prefix) > 0 {
		key = strings.Join(appendPrefix(prefix, key), ".")
	}

	fields = append(fields, consoleField{key: key, value: attr.Value})
	return fields
}

func sortConsoleFields(fields []consoleField) {
	sort.Slice(fields, func(i, j int) bool {
		leftError := isErrorKey(fields[i].key)
		rightError := isErrorKey(fields[j].key)
		if leftError != rightError {
			return leftError
		}
		return fields[i].key < fields[j].key
	})
}

func formatConsoleMessage(level slog.Level, message string) string {
	switch {
	case level >= slog.LevelInfo:
		return colorize("\x1b[1m", message)
	default:
		return message
	}
}

func formatConsoleFieldName(key string) string {
	return colorize("\x1b[36m", key+"=")
}

func formatConsoleValue(key string, value slog.Value) string {
	value = value.Resolve()
	rendered := formatConsoleValueText(value)
	if isErrorKey(key) {
		return colorize("\x1b[31;1m", rendered)
	}
	return rendered
}

func formatConsoleValueText(value slog.Value) string {
	switch value.Kind() {
	case slog.KindString:
		return quoteIfNeeded(value.String())
	case slog.KindInt64:
		return strconv.FormatInt(value.Int64(), 10)
	case slog.KindUint64:
		return strconv.FormatUint(value.Uint64(), 10)
	case slog.KindFloat64:
		return strconv.FormatFloat(value.Float64(), 'f', -1, 64)
	case slog.KindBool:
		return strconv.FormatBool(value.Bool())
	case slog.KindDuration:
		return value.Duration().String()
	case slog.KindTime:
		return value.Time().Format(time.RFC3339Nano)
	case slog.KindAny:
		return quoteIfNeeded(fmt.Sprint(value.Any()))
	default:
		return quoteIfNeeded(value.String())
	}
}

func quoteIfNeeded(s string) string {
	if s == "" {
		return `""`
	}
	for _, r := range s {
		if unicode.IsSpace(r) || r == '=' || r == '"' || unicode.IsControl(r) {
			return strconv.Quote(s)
		}
	}
	return s
}

func appendPrefix(prefix []string, value string) []string {
	out := make([]string, 0, len(prefix)+1)
	out = append(out, prefix...)
	out = append(out, value)
	return out
}

func cloneAttrs(attrs []slog.Attr) []slog.Attr {
	if len(attrs) == 0 {
		return nil
	}
	out := make([]slog.Attr, len(attrs))
	copy(out, attrs)
	return out
}

func cloneStrings(values []string) []string {
	if len(values) == 0 {
		return nil
	}
	out := make([]string, len(values))
	copy(out, values)
	return out
}

func levelColor(level slog.Level) string {
	switch {
	case level < slog.LevelDebug:
		return "\x1b[34m"
	case level <= slog.LevelDebug:
		return ""
	case level < slog.LevelWarn:
		return "\x1b[32m"
	case level < slog.LevelError:
		return "\x1b[33m"
	default:
		return "\x1b[31m"
	}
}

func levelLabel(level slog.Level) string {
	switch {
	case level < slog.LevelDebug:
		return "TRC"
	case level == slog.LevelDebug:
		return "DBG"
	case level < slog.LevelWarn:
		return "INF"
	case level < slog.LevelError:
		return "WRN"
	case level < slog.LevelError+4:
		return "ERR"
	default:
		return "ERR"
	}
}

func isErrorKey(key string) bool {
	return key == "err" || key == "error"
}

func colorize(colorCode, value string) string {
	if colorCode == "" {
		return value
	}
	return colorCode + value + "\x1b[0m"
}
