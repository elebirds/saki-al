package main

import (
	"bufio"
	"context"
	"fmt"
	"os"
	"strings"
	"time"

	"github.com/rs/zerolog"

	"github.com/elebirds/saki/saki-dispatcher/internal/dispatch"
	"github.com/elebirds/saki/saki-dispatcher/internal/runtime_domain_client"
)

func startStdinCommandLoop(
	ctx context.Context,
	stop context.CancelFunc,
	domainClient *runtime_domain_client.Client,
	dispatcher *dispatch.Dispatcher,
	logger zerolog.Logger,
) {
	if domainClient == nil || dispatcher == nil {
		logger.Warn().Msg("stdin 命令台未启动：依赖未就绪")
		return
	}
	go runStdinCommandLoop(ctx, stop, domainClient, dispatcher, logger)
}

func runStdinCommandLoop(
	ctx context.Context,
	stop context.CancelFunc,
	domainClient *runtime_domain_client.Client,
	dispatcher *dispatch.Dispatcher,
	logger zerolog.Logger,
) {
	interactive := isTTY(os.Stdin)
	scanner := bufio.NewScanner(os.Stdin)
	logger.Info().Msg("开发命令台已启动，输入 help 查看可用命令")
	printPrompt(interactive)

	for {
		select {
		case <-ctx.Done():
			logger.Info().Msg("开发命令台已停止")
			return
		default:
		}

		if !scanner.Scan() {
			if err := scanner.Err(); err != nil {
				logger.Warn().Err(err).Msg("读取标准输入失败，开发命令台停止")
				return
			}
			logger.Info().Msg("标准输入已关闭，开发命令台停止")
			return
		}

		line := strings.TrimSpace(scanner.Text())
		if line == "" {
			printPrompt(interactive)
			continue
		}
		args := strings.Fields(line)
		cmd := strings.ToLower(args[0])
		switch cmd {
		case "help", "h", "?":
			printHelp()
		case "status", "st":
			printStatus(domainClient, dispatcher)
		case "connect":
			if err := domainClient.Enable(); err != nil {
				fmt.Fprintf(os.Stdout, "执行失败: %v\n", err)
			} else {
				fmt.Fprintln(os.Stdout, "已启用 runtime_domain 连接")
			}
		case "disconnect":
			if err := domainClient.Disable(); err != nil {
				fmt.Fprintf(os.Stdout, "执行失败: %v\n", err)
			} else {
				fmt.Fprintln(os.Stdout, "已停用 runtime_domain 连接")
			}
		case "reconnect":
			if err := domainClient.Reconnect(); err != nil {
				fmt.Fprintf(os.Stdout, "执行失败: %v\n", err)
			} else {
				fmt.Fprintln(os.Stdout, "已触发 runtime_domain 重连")
			}
		case "quit", "exit":
			fmt.Fprintln(os.Stdout, "收到退出命令，正在停止 dispatcher...")
			stop()
			return
		default:
			fmt.Fprintf(os.Stdout, "未知命令: %s（输入 help 查看可用命令）\n", cmd)
		}
		printPrompt(interactive)
	}
}

func printHelp() {
	fmt.Fprintln(os.Stdout, "可用命令:")
	fmt.Fprintln(os.Stdout, "  status|st     查看 runtime_domain 与 dispatcher 状态")
	fmt.Fprintln(os.Stdout, "  connect       启用 runtime_domain 连接")
	fmt.Fprintln(os.Stdout, "  disconnect    停用 runtime_domain 连接")
	fmt.Fprintln(os.Stdout, "  reconnect     触发 runtime_domain 重连")
	fmt.Fprintln(os.Stdout, "  help|h|?      显示帮助")
	fmt.Fprintln(os.Stdout, "  exit|quit     退出 dispatcher")
}

func printStatus(domainClient *runtime_domain_client.Client, dispatcher *dispatch.Dispatcher) {
	snapshot := domainClient.Status()
	summary := dispatcher.Summary()
	fmt.Fprintf(
		os.Stdout,
		"runtime_domain: configured=%t enabled=%t state=%s failures=%d target=%s last_error=%s last_connected_at=%s next_retry_at=%s\n",
		snapshot.Configured,
		snapshot.Enabled,
		snapshot.State,
		snapshot.ConsecutiveFailures,
		snapshot.Target,
		defaultText(snapshot.LastError),
		formatTime(snapshot.LastConnectedAt),
		formatTime(snapshot.NextRetryAt),
	)
	fmt.Fprintf(
		os.Stdout,
		"dispatcher: online=%d busy=%d pending_assign=%d pending_stop=%d queued_step=%d latest_heartbeat_at=%s\n",
		summary.OnlineExecutors,
		summary.BusyExecutors,
		summary.PendingAssign,
		summary.PendingStop,
		summary.QueuedStepCount,
		formatTime(summary.LatestHeartbeatAt),
	)
}

func printPrompt(interactive bool) {
	if !interactive {
		return
	}
	fmt.Fprint(os.Stdout, "dispatcher> ")
}

func isTTY(file *os.File) bool {
	if file == nil {
		return false
	}
	info, err := file.Stat()
	if err != nil {
		return false
	}
	return (info.Mode() & os.ModeCharDevice) != 0
}

func formatTime(ts time.Time) string {
	if ts.IsZero() {
		return "-"
	}
	return ts.Local().Format(time.RFC3339)
}

func defaultText(v string) string {
	v = strings.TrimSpace(v)
	if v == "" {
		return "-"
	}
	return v
}
