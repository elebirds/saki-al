package agent

import (
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"

	"github.com/elebirds/saki/saki-agent/internal/device"
)

type CacheSummary struct {
	Root    string
	Entries int
	Bytes   int64
}

type StatusSnapshot struct {
	RunDir              string
	CacheDir            string
	Draining            bool
	UploaderConfigured  bool
	SocketCount         int
	KernelInstanceCount int
	KernelInstanceIDs   []string
	ReconnectCount      int64
	LastReconnectAt     time.Time
	Cache               CacheSummary
	Capabilities        *device.DeviceCapabilities
	CapabilityError     string
}

func (a *Agent) Status() StatusSnapshot {
	kernelIDs, listErr := a.ListKernelInstanceIDs()
	socketCount, socketErr := a.SocketCount()
	cacheSummary, cacheErr := a.CacheSummary()
	capabilities, capabilityErr := device.DetectDeviceCapabilities()
	reconnectCount, lastReconnectAt := a.ReconnectSnapshot()

	snapshot := StatusSnapshot{
		RunDir:              a.cfg.RunDir,
		CacheDir:            a.cfg.CacheDir,
		Draining:            a.IsDraining(),
		UploaderConfigured:  a.uploader != nil,
		SocketCount:         socketCount,
		KernelInstanceCount: len(kernelIDs),
		KernelInstanceIDs:   kernelIDs,
		ReconnectCount:      reconnectCount,
		LastReconnectAt:     lastReconnectAt,
		Cache:               cacheSummary,
		Capabilities:        capabilities,
	}
	var errs []string
	if listErr != nil {
		errs = append(errs, fmt.Sprintf("kernels=%v", listErr))
	}
	if socketErr != nil {
		errs = append(errs, fmt.Sprintf("sockets=%v", socketErr))
	}
	if cacheErr != nil {
		errs = append(errs, fmt.Sprintf("cache=%v", cacheErr))
	}
	if capabilityErr != nil {
		errs = append(errs, fmt.Sprintf("capabilities=%v", capabilityErr))
	}
	if len(errs) > 0 {
		snapshot.CapabilityError = strings.Join(errs, "; ")
	}
	return snapshot
}

func (a *Agent) ListKernelInstanceIDs() ([]string, error) {
	dir := strings.TrimSpace(a.cfg.RunDir)
	if dir == "" {
		return nil, fmt.Errorf("run dir is empty")
	}
	entries, err := os.ReadDir(dir)
	if err != nil {
		return nil, err
	}
	ids := make(map[string]struct{})
	for _, entry := range entries {
		name := entry.Name()
		switch {
		case strings.HasSuffix(name, ".ctl.sock"):
			ids[strings.TrimSuffix(name, ".ctl.sock")] = struct{}{}
		case strings.HasSuffix(name, ".evt.sock"):
			ids[strings.TrimSuffix(name, ".evt.sock")] = struct{}{}
		}
	}
	out := make([]string, 0, len(ids))
	for id := range ids {
		if strings.TrimSpace(id) == "" {
			continue
		}
		out = append(out, id)
	}
	sort.Strings(out)
	return out, nil
}

func (a *Agent) SocketCount() (int, error) {
	dir := strings.TrimSpace(a.cfg.RunDir)
	if dir == "" {
		return 0, fmt.Errorf("run dir is empty")
	}
	entries, err := os.ReadDir(dir)
	if err != nil {
		return 0, err
	}
	count := 0
	for _, entry := range entries {
		name := entry.Name()
		if strings.HasSuffix(name, ".ctl.sock") || strings.HasSuffix(name, ".evt.sock") {
			count++
		}
	}
	return count, nil
}

func (a *Agent) KillKernel(instanceID string) error {
	id := strings.TrimSpace(instanceID)
	if id == "" {
		return fmt.Errorf("kernel_instance_id is required")
	}
	removed := false
	for _, suffix := range []string{".ctl.sock", ".evt.sock"} {
		socketPath := filepath.Join(a.cfg.RunDir, id+suffix)
		if err := os.Remove(socketPath); err != nil {
			if os.IsNotExist(err) {
				continue
			}
			return err
		}
		removed = true
	}
	if !removed {
		return fmt.Errorf("kernel instance not found: %s", id)
	}
	a.logger.Warn().Str("kernel_instance_id", id).Msg("kernel kill 已触发（当前实现为清理 IPC socket）")
	return nil
}

func (a *Agent) CacheSummary() (CacheSummary, error) {
	root := strings.TrimSpace(a.cfg.CacheDir)
	if root == "" {
		return CacheSummary{Root: ""}, nil
	}
	summary := CacheSummary{Root: root}
	err := filepath.WalkDir(root, func(path string, d fs.DirEntry, walkErr error) error {
		if walkErr != nil {
			return walkErr
		}
		if d.IsDir() {
			return nil
		}
		info, err := d.Info()
		if err != nil {
			return err
		}
		summary.Entries++
		summary.Bytes += info.Size()
		return nil
	})
	if err != nil {
		return summary, err
	}
	return summary, nil
}
