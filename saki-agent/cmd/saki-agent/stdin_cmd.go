package main

import (
	"bufio"
	"context"
	"fmt"
	"os"
	"strings"
	"time"

	"github.com/rs/zerolog"

	"github.com/elebirds/saki/saki-agent/internal/agent"
	"github.com/elebirds/saki/saki-agent/internal/runtimeclient"
)

func startStdinCommandLoop(
	ctx context.Context,
	stop context.CancelFunc,
	daemon *agent.Agent,
	runtimeClient *runtimeclient.Client,
	logger zerolog.Logger,
) {
	if daemon == nil {
		logger.Warn().Msg("stdin 命令台未启动：agent 未就绪")
		return
	}
	go runStdinCommandLoop(ctx, stop, daemon, runtimeClient, logger)
}

func runStdinCommandLoop(
	ctx context.Context,
	stop context.CancelFunc,
	daemon *agent.Agent,
	runtimeClient *runtimeclient.Client,
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
			printStatus(daemon, runtimeClient)
		case "kernels":
			printKernels(daemon)
		case "cache":
			printCache(daemon)
		case "drain":
			handleDrainCommand(daemon, args)
		case "kill":
			handleKillCommand(daemon, args)
		case "reconnect":
			if runtimeClient == nil {
				fmt.Fprintln(os.Stdout, "runtime client 未启用")
				break
			}
			if err := runtimeClient.Reconnect(); err != nil {
				fmt.Fprintf(os.Stdout, "reconnect 失败: %v\n", err)
				break
			}
			daemon.MarkReconnect()
			fmt.Fprintln(os.Stdout, "已触发 dispatcher stream 重连")
		case "quit", "exit":
			fmt.Fprintln(os.Stdout, "收到退出命令，正在停止 saki-agent...")
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
	fmt.Fprintln(os.Stdout, "  status|st            查看 agent 运行状态")
	fmt.Fprintln(os.Stdout, "  kernels              查看推断中的 kernel instance")
	fmt.Fprintln(os.Stdout, "  cache                查看缓存目录统计")
	fmt.Fprintln(os.Stdout, "  drain [on|off]       切换/查看 drain 状态")
	fmt.Fprintln(os.Stdout, "  kill <kernel_id>     触发 kernel kill（当前实现: 清理 IPC socket）")
	fmt.Fprintln(os.Stdout, "  reconnect            记录一次 reconnect 操作")
	fmt.Fprintln(os.Stdout, "  help|h|?             显示帮助")
	fmt.Fprintln(os.Stdout, "  exit|quit            退出 saki-agent")
}

func printStatus(daemon *agent.Agent, runtimeClient *runtimeclient.Client) {
	snapshot := daemon.Status()
	fmt.Fprintf(
		os.Stdout,
		"agent: run_dir=%s cache_dir=%s draining=%t uploader=%t kernels=%d sockets=%d reconnect_count=%d last_reconnect_at=%s\n",
		defaultText(snapshot.RunDir),
		defaultText(snapshot.CacheDir),
		snapshot.Draining,
		snapshot.UploaderConfigured,
		snapshot.KernelInstanceCount,
		snapshot.SocketCount,
		snapshot.ReconnectCount,
		formatTime(snapshot.LastReconnectAt),
	)
	if snapshot.Capabilities != nil {
		cuda := snapshot.Capabilities.CUDA
		mps := snapshot.Capabilities.MPS
		fmt.Fprintf(
			os.Stdout,
			"hardware: platform=%s cpu=%s cores=%d/%d cuda=%t mps=%t\n",
			snapshot.Capabilities.Platform,
			defaultText(snapshot.Capabilities.CPU.ModelName),
			snapshot.Capabilities.CPU.PhysicalCores,
			snapshot.Capabilities.CPU.LogicalCores,
			cuda != nil && cuda.Available,
			mps != nil && mps.Available,
		)
	}
	if snapshot.CapabilityError != "" {
		fmt.Fprintf(os.Stdout, "warning: %s\n", snapshot.CapabilityError)
	}
	if runtimeClient != nil {
		runtimeSnapshot := runtimeClient.Status()
		fmt.Fprintf(
			os.Stdout,
			"runtime_control: configured=%t state=%s target=%s executor_id=%s node_id=%s busy=%t current_step_id=%s failures=%d last_error=%s last_connected_at=%s next_retry_at=%s\n",
			runtimeSnapshot.Configured,
			defaultText(runtimeSnapshot.State),
			defaultText(runtimeSnapshot.Target),
			defaultText(runtimeSnapshot.ExecutorID),
			defaultText(runtimeSnapshot.NodeID),
			runtimeSnapshot.Busy,
			defaultText(runtimeSnapshot.CurrentStepID),
			runtimeSnapshot.ConsecutiveFailures,
			defaultText(runtimeSnapshot.LastError),
			formatTime(runtimeSnapshot.LastConnectedAt),
			formatTime(runtimeSnapshot.NextRetryAt),
		)
		fmt.Fprintf(
			os.Stdout,
			"plugins: loaded=%t count=%d loaded_at=%s load_error=%s\n",
			runtimeSnapshot.PluginCatalogLoaded,
			runtimeSnapshot.PluginCatalogSize,
			formatTime(runtimeSnapshot.PluginCatalogAt),
			defaultText(runtimeSnapshot.PluginCatalogError),
		)
		if len(runtimeSnapshot.Plugins) > 0 {
			pluginLabels := make([]string, 0, len(runtimeSnapshot.Plugins))
			for _, plugin := range runtimeSnapshot.Plugins {
				label := fmt.Sprintf("%s@%s", plugin.ID, plugin.Version)
				pluginLabels = append(pluginLabels, label)
			}
			fmt.Fprintf(os.Stdout, "plugins_loaded: %s\n", strings.Join(pluginLabels, ", "))
		}
	}
}

func printKernels(daemon *agent.Agent) {
	kernels, err := daemon.ListKernelInstanceIDs()
	if err != nil {
		fmt.Fprintf(os.Stdout, "读取 kernel 列表失败: %v\n", err)
		return
	}
	if len(kernels) == 0 {
		fmt.Fprintln(os.Stdout, "当前无活跃 kernel instance")
		return
	}
	fmt.Fprintln(os.Stdout, "kernel instances:")
	for _, kernelID := range kernels {
		fmt.Fprintf(os.Stdout, "  - %s\n", kernelID)
	}
}

func printCache(daemon *agent.Agent) {
	summary, err := daemon.CacheSummary()
	if err != nil {
		fmt.Fprintf(os.Stdout, "读取缓存统计失败: %v\n", err)
		return
	}
	fmt.Fprintf(
		os.Stdout,
		"cache: root=%s entries=%d bytes=%d\n",
		defaultText(summary.Root),
		summary.Entries,
		summary.Bytes,
	)
}

func handleDrainCommand(daemon *agent.Agent, args []string) {
	if len(args) == 1 {
		fmt.Fprintf(os.Stdout, "drain=%t\n", daemon.IsDraining())
		return
	}
	mode := strings.ToLower(strings.TrimSpace(args[1]))
	switch mode {
	case "on", "true", "1":
		daemon.SetDraining(true)
		fmt.Fprintln(os.Stdout, "drain 已开启")
	case "off", "false", "0":
		daemon.SetDraining(false)
		fmt.Fprintln(os.Stdout, "drain 已关闭")
	default:
		fmt.Fprintln(os.Stdout, "用法: drain [on|off]")
	}
}

func handleKillCommand(daemon *agent.Agent, args []string) {
	if len(args) < 2 {
		fmt.Fprintln(os.Stdout, "用法: kill <kernel_id>")
		return
	}
	kernelID := strings.TrimSpace(args[1])
	if err := daemon.KillKernel(kernelID); err != nil {
		fmt.Fprintf(os.Stdout, "kill 失败: %v\n", err)
		return
	}
	fmt.Fprintf(os.Stdout, "kernel %s 已触发 kill\n", kernelID)
}

func printPrompt(interactive bool) {
	if !interactive {
		return
	}
	fmt.Fprint(os.Stdout, "saki-agent> ")
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
