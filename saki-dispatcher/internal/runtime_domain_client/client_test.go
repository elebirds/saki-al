package runtime_domain_client

import (
	"context"
	"errors"
	"testing"
	"time"

	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
)

func TestIsTransientError(t *testing.T) {
	t.Parallel()

	if !IsTransientError(ErrDisabled) {
		t.Fatalf("ErrDisabled 应被识别为临时错误")
	}
	if !IsTransientError(ErrNotConnected) {
		t.Fatalf("ErrNotConnected 应被识别为临时错误")
	}
	if IsTransientError(ErrNotConfigured) {
		t.Fatalf("ErrNotConfigured 不应被识别为临时错误")
	}
	if !IsTransientError(status.Error(codes.Unavailable, "unavailable")) {
		t.Fatalf("Unavailable 应被识别为临时错误")
	}
	if IsTransientError(status.Error(codes.InvalidArgument, "bad request")) {
		t.Fatalf("InvalidArgument 不应被识别为临时错误")
	}
	if !IsTransientError(context.DeadlineExceeded) {
		t.Fatalf("context.DeadlineExceeded 应被识别为临时错误")
	}
}

func TestEnableDisableRequireConfigured(t *testing.T) {
	t.Parallel()

	client := New("", "", 5)
	if client.Configured() {
		t.Fatalf("未配置 target 时，Configured 应为 false")
	}
	if !errors.Is(client.Enable(), ErrNotConfigured) {
		t.Fatalf("Enable 应返回 ErrNotConfigured")
	}
	if !errors.Is(client.Disable(), ErrNotConfigured) {
		t.Fatalf("Disable 应返回 ErrNotConfigured")
	}
	if !errors.Is(client.Reconnect(), ErrNotConfigured) {
		t.Fatalf("Reconnect 应返回 ErrNotConfigured")
	}
}

func TestBackoffThenDisable(t *testing.T) {
	t.Parallel()

	client := New("127.0.0.1:1", "", 1)
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	client.Start(ctx)
	defer func() {
		if err := client.Close(); err != nil {
			t.Fatalf("关闭客户端失败: %v", err)
		}
	}()

	deadline := time.Now().Add(2 * time.Second)
	for time.Now().Before(deadline) {
		snapshot := client.Status()
		if snapshot.State == StateBackoff || snapshot.State == StateConnecting {
			break
		}
		time.Sleep(50 * time.Millisecond)
	}

	if err := client.Disable(); err != nil {
		t.Fatalf("Disable 返回错误: %v", err)
	}
	snapshot := client.Status()
	if snapshot.State != StateDisabled {
		t.Fatalf("Disable 后状态应为 disabled，实际为 %s", snapshot.State)
	}
}
