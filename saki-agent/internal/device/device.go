package device

import (
	"bufio"
	"context"
	"errors"
	"os"
	"os/exec"
	"runtime"
	"strings"
	"time"

	"github.com/spf13/cast"
)

// DeviceCapabilities 代表系统的硬件能力
type DeviceCapabilities struct {
	CUDA     *CUDAInfo `json:"cuda,omitempty"`
	MPS      *MPSInfo  `json:"mps,omitempty"`
	CPU      *CPUInfo  `json:"cpu"`
	Platform string    `json:"platform"`
}

const (
	BestDeviceCPU  = "cpu"
	BestDeviceCUDA = "cuda"
	BestDeviceMPS  = "mps"
)

// CUDAInfo 包含 CUDA 设备的信息
type CUDAInfo struct {
	Available         bool     `json:"available"`
	Version           string   `json:"version,omitempty"`
	DeviceCount       int      `json:"device_count,omitempty"`
	DeviceNames       []string `json:"device_names,omitempty"`
	ComputeCapability string   `json:"compute_capability,omitempty"`
}

// MPSInfo 包含 Metal Performance Shaders 的信息 (macOS/iOS)
type MPSInfo struct {
	Available bool   `json:"available"`
	Version   string `json:"version,omitempty"`
}

// CPUInfo 包含 CPU 的信息
type CPUInfo struct {
	PhysicalCores int     `json:"physical_cores"`
	LogicalCores  int     `json:"logical_cores"`
	ModelName     string  `json:"model_name"`
	Frequency     float64 `json:"frequency_mhz"`
	Architecture  string  `json:"architecture"`
}

// DetectDeviceCapabilities 检测系统的硬件能力
func DetectDeviceCapabilities() (*DeviceCapabilities, error) {
	caps := &DeviceCapabilities{
		Platform: runtime.GOOS,
		CPU:      detectCPUInfo(),
	}

	// 检测 CUDA
	caps.CUDA = detectCUDA()

	// 检测 MPS (仅在 Darwin/macOS 上)
	if runtime.GOOS == "darwin" {
		caps.MPS = detectMPS()
	}

	return caps, nil
}

// BestDevice 返回建议的默认设备类型（优先级：CUDA > MPS > CPU）。
func (c *DeviceCapabilities) BestDevice() string {
	if c == nil {
		return BestDeviceCPU
	}
	if c.CUDA != nil && c.CUDA.Available && c.CUDA.DeviceCount > 0 {
		return BestDeviceCUDA
	}
	if c.MPS != nil && c.MPS.Available {
		return BestDeviceMPS
	}
	return BestDeviceCPU
}

// detectCUDA 检测 CUDA 是否可用及其信息
func detectCUDA() *CUDAInfo {
	cudaInfo := &CUDAInfo{Available: false}

	// nvidia-smi 不存在是常态（例如 Apple Silicon），此处静默返回。
	path, err := exec.LookPath("nvidia-smi")
	if err != nil {
		return cudaInfo
	}

	// 通过设备名列表统计设备数量，兼容性更稳定。
	rawNames, err := commandOutput(path, "--query-gpu=name", "--format=csv,noheader")
	if err != nil {
		return cudaInfo
	}
	names := parseLines(rawNames)
	if len(names) == 0 {
		return cudaInfo
	}

	cudaInfo.Available = true
	cudaInfo.DeviceCount = len(names)
	cudaInfo.DeviceNames = names

	// 计算能力（可能是一行一个设备，去重后逗号拼接）
	if rawCC, ccErr := commandOutput(path, "--query-gpu=compute_cap", "--format=csv,noheader"); ccErr == nil {
		cudaInfo.ComputeCapability = strings.Join(parseUniqueLines(rawCC), ",")
	}

	// 驱动版本（可能一行一个设备，通常相同，取第一项）
	if rawVer, verErr := commandOutput(path, "--query-gpu=driver_version", "--format=csv,noheader"); verErr == nil {
		versions := parseLines(rawVer)
		if len(versions) > 0 {
			cudaInfo.Version = versions[0]
		}
	}

	return cudaInfo
}

// detectMPS 检测 Metal Performance Shaders 是否可用 (macOS only)
func detectMPS() *MPSInfo {
	mpsInfo := &MPSInfo{Available: false}
	if runtime.GOOS != "darwin" {
		return mpsInfo
	}

	output, err := commandOutput("system_profiler", "SPDisplaysDataType")
	if err != nil {
		// 退化策略：Apple Silicon 默认认为 MPS 可用。
		if runtime.GOARCH == "arm64" {
			mpsInfo.Available = true
			mpsInfo.Version = "Apple Silicon (MPS available)"
		}
		return mpsInfo
	}

	if strings.Contains(output, "Metal") ||
		strings.Contains(output, "GPU") ||
		strings.Contains(output, "Graphics") {
		mpsInfo.Available = true
		if strings.Contains(output, "Apple") {
			mpsInfo.Version = "Apple Silicon (MPS available)"
		} else {
			mpsInfo.Version = "Discrete GPU (MPS available)"
		}
	}
	return mpsInfo
}

// detectCPUInfo 检测 CPU 信息
func detectCPUInfo() *CPUInfo {
	logical := runtime.NumCPU()
	info := &CPUInfo{
		PhysicalCores: logical,
		LogicalCores:  logical,
		Architecture:  runtime.GOARCH,
	}

	switch runtime.GOOS {
	case "darwin":
		if model, err := commandOutput("sysctl", "-n", "machdep.cpu.brand_string"); err == nil {
			info.ModelName = model
		}
		if physical, err := commandOutput("sysctl", "-n", "hw.physicalcpu"); err == nil {
			if n, parseErr := cast.ToIntE(strings.TrimSpace(physical)); parseErr == nil && n > 0 {
				info.PhysicalCores = n
			}
		}
		if hz, err := commandOutput("sysctl", "-n", "hw.cpufrequency"); err == nil {
			if v, parseErr := cast.ToFloat64E(strings.TrimSpace(hz)); parseErr == nil && v > 0 {
				info.Frequency = v / 1_000_000
			}
		}
	case "linux":
		if content, err := os.ReadFile("/proc/cpuinfo"); err == nil {
			fillCPUInfoFromProc(string(content), info)
		}
	}

	return info
}

// GetCUDACapability 获取 CUDA 能力，如果不可用返回 false
func GetCUDACapability() (bool, *CUDAInfo) {
	cudaInfo := detectCUDA()
	return cudaInfo.Available, cudaInfo
}

// GetMPSCapability 获取 MPS 能力 (macOS only)，如果不可用返回 false
func GetMPSCapability() (bool, *MPSInfo) {
	if runtime.GOOS != "darwin" {
		return false, &MPSInfo{Available: false}
	}
	mpsInfo := detectMPS()
	return mpsInfo.Available, mpsInfo
}

// GetCPUCapability 获取 CPU 能力信息
func GetCPUCapability() *CPUInfo {
	return detectCPUInfo()
}

// IsCUDAAvailable 检查 CUDA 是否可用
func IsCUDAAvailable() bool {
	available, _ := GetCUDACapability()
	return available
}

// IsMPSAvailable 检查 MPS 是否可用 (仅 macOS)
func IsMPSAvailable() bool {
	if runtime.GOOS != "darwin" {
		return false
	}
	available, _ := GetMPSCapability()
	return available
}

func commandOutput(name string, args ...string) (string, error) {
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()

	cmd := exec.CommandContext(ctx, name, args...)
	output, err := cmd.Output()
	if err != nil {
		if errors.Is(ctx.Err(), context.DeadlineExceeded) {
			return "", ctx.Err()
		}
		return "", err
	}
	return strings.TrimSpace(string(output)), nil
}

func parseLines(raw string) []string {
	items := make([]string, 0)
	scanner := bufio.NewScanner(strings.NewReader(raw))
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" {
			continue
		}
		items = append(items, line)
	}
	return items
}

func parseUniqueLines(raw string) []string {
	set := make(map[string]struct{})
	items := make([]string, 0)
	for _, line := range parseLines(raw) {
		if _, exists := set[line]; exists {
			continue
		}
		set[line] = struct{}{}
		items = append(items, line)
	}
	return items
}

func fillCPUInfoFromProc(content string, info *CPUInfo) {
	if info == nil {
		return
	}

	var model string
	var mhz float64
	corePairs := make(map[string]struct{})
	hasPair := false
	physicalID := ""
	coreID := ""

	scanner := bufio.NewScanner(strings.NewReader(content))
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" {
			if physicalID != "" && coreID != "" {
				corePairs[physicalID+":"+coreID] = struct{}{}
				hasPair = true
			}
			physicalID = ""
			coreID = ""
			continue
		}

		parts := strings.SplitN(line, ":", 2)
		if len(parts) != 2 {
			continue
		}
		key := strings.TrimSpace(parts[0])
		value := strings.TrimSpace(parts[1])

		switch key {
		case "model name":
			if model == "" {
				model = value
			}
		case "cpu MHz":
			if mhz <= 0 {
				if parsed, err := cast.ToFloat64E(value); err == nil && parsed > 0 {
					mhz = parsed
				}
			}
		case "physical id":
			physicalID = value
		case "core id":
			coreID = value
		}
	}
	if physicalID != "" && coreID != "" {
		corePairs[physicalID+":"+coreID] = struct{}{}
		hasPair = true
	}

	if hasPair && len(corePairs) > 0 {
		info.PhysicalCores = len(corePairs)
	}
	if model != "" {
		info.ModelName = model
	}
	if mhz > 0 {
		info.Frequency = mhz
	}
}
