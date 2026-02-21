package device

import (
	"fmt"
	"log"
	"os/exec"
	"runtime"
	"strings"

	"github.com/shirou/gopsutil/v3/cpu"
)

// DeviceCapabilities 代表系统的硬件能力
type DeviceCapabilities struct {
	CUDA     *CUDAInfo `json:"cuda,omitempty"`
	MPS      *MPSInfo  `json:"mps,omitempty"`
	CPU      *CPUInfo  `json:"cpu"`
	Platform string    `json:"platform"`
}

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

// detectCUDA 检测 CUDA 是否可用及其信息
func detectCUDA() *CUDAInfo {
	cudaInfo := &CUDAInfo{Available: false}

	// 检查 nvidia-smi 是否存在
	path, err := exec.LookPath("nvidia-smi")
	if err != nil {
		log.Printf("nvidia-smi not found: %v", err)
		return cudaInfo
	}

	// 执行 nvidia-smi --query-gpu=count --format=csv,noheader
	cmd := exec.Command(path, "--query-gpu=count", "--format=csv,noheader")
	output, err := cmd.Output()
	if err != nil {
		log.Printf("failed to query GPU count: %v", err)
		return cudaInfo
	}

	countStr := strings.TrimSpace(string(output))
	var deviceCount int
	_, err = fmt.Sscanf(countStr, "%d", &deviceCount)
	if err != nil {
		log.Printf("failed to parse GPU count: %v", err)
		return cudaInfo
	}

	if deviceCount == 0 {
		return cudaInfo
	}

	cudaInfo.Available = true
	cudaInfo.DeviceCount = deviceCount

	// 获取 CUDA 版本
	cmd = exec.Command(path, "--query-cuda=compute_cap", "--format=csv,noheader")
	output, err = cmd.Output()
	if err == nil {
		cudaInfo.ComputeCapability = strings.TrimSpace(string(output))
	}

	// 获取设备名称
	cmd = exec.Command(path, "--query-gpu=name", "--format=csv,noheader")
	output, err = cmd.Output()
	if err == nil {
		names := strings.Split(strings.TrimSpace(string(output)), "\n")
		cudaInfo.DeviceNames = names
	}

	// 获取 CUDA 驱动版本
	cmd = exec.Command(path, "--query-gpu=driver_version", "--format=csv,noheader")
	output, err = cmd.Output()
	if err == nil {
		cudaInfo.Version = strings.TrimSpace(string(output))
	}

	return cudaInfo
}

// detectMPS 检测 Metal Performance Shaders 是否可用 (macOS only)
func detectMPS() *MPSInfo {
	mpsInfo := &MPSInfo{Available: false}

	if runtime.GOOS != "darwin" {
		return mpsInfo
	}

	// 在 macOS 上检查 GPU 是否可用
	// 使用 system_profiler SPDisplaysDataType 命令
	cmd := exec.Command("system_profiler", "SPDisplaysDataType")
	output, err := cmd.Output()
	if err != nil {
		log.Printf("failed to query system GPU info: %v", err)
		return mpsInfo
	}

	// 检查输出中是否包含 GPU 信息
	outputStr := string(output)
	if strings.Contains(outputStr, "Metal") ||
		strings.Contains(outputStr, "GPU") ||
		strings.Contains(outputStr, "Graphics") {
		mpsInfo.Available = true

		// 尝试从 GPU 名称中识别
		if strings.Contains(outputStr, "Apple") {
			mpsInfo.Version = "Apple Silicon (MPS available)"
		} else {
			// 对于独立 GPU（如 AMD, NVIDIA），MPS 仍然可用
			mpsInfo.Version = "Discrete GPU (MPS available)"
		}
	}

	return mpsInfo
}

// detectCPUInfo 检测 CPU 信息
func detectCPUInfo() *CPUInfo {
	cpuInfo := &CPUInfo{}

	// 获取物理核心数
	physicalCores, err := cpu.Counts(false)
	if err != nil {
		log.Printf("failed to get physical CPU cores: %v", err)
		physicalCores = runtime.NumCPU()
	}
	cpuInfo.PhysicalCores = physicalCores

	// 获取逻辑核心数
	logicalCores := runtime.NumCPU()
	cpuInfo.LogicalCores = logicalCores

	// 获取 CPU 模型名称
	cpuInfos, err := cpu.Info()
	if err == nil && len(cpuInfos) > 0 {
		cpuInfo.ModelName = cpuInfos[0].ModelName
		cpuInfo.Frequency = float64(cpuInfos[0].Mhz)
	}

	// 获取架构信息
	cpuInfo.Architecture = runtime.GOARCH

	return cpuInfo
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
