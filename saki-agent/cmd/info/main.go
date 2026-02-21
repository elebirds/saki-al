package main

import (
	"encoding/json"
	"fmt"
	"log"

	"github.com/elebirds/saki/saki-agent/internal/device"
)

func main() {
	fmt.Println("=== 系统硬件能力检测 ===\n")

	// 检测全部硬件能力
	caps, err := device.DetectDeviceCapabilities()
	if err != nil {
		log.Fatalf("Failed to detect device capabilities: %v", err)
	}

	// 输出 JSON 格式
	jsonData, err := json.MarshalIndent(caps, "", "  ")
	if err != nil {
		log.Fatalf("Failed to marshal JSON: %v", err)
	}
	fmt.Println(string(jsonData))

	// 单独检测各项能力
	fmt.Println("\n=== 详细信息 ===\n")

	// CPU 能力
	cpuInfo := device.GetCPUCapability()
	fmt.Printf("CPU 信息:\n")
	fmt.Printf("  模型: %s\n", cpuInfo.ModelName)
	fmt.Printf("  物理核心: %d\n", cpuInfo.PhysicalCores)
	fmt.Printf("  逻辑核心: %d\n", cpuInfo.LogicalCores)
	fmt.Printf("  频率: %.0f MHz\n", cpuInfo.Frequency)
	fmt.Printf("  架构: %s\n\n", cpuInfo.Architecture)

	// CUDA 能力
	hasGPU, cudaInfo := device.GetCUDACapability()
	fmt.Printf("CUDA 信息:\n")
	fmt.Printf("  可用: %v\n", hasGPU)
	if hasGPU {
		fmt.Printf("  设备数量: %d\n", cudaInfo.DeviceCount)
		for i, name := range cudaInfo.DeviceNames {
			fmt.Printf("    设备 %d: %s\n", i, name)
		}
		fmt.Printf("  驱动版本: %s\n", cudaInfo.Version)
	}
	fmt.Println()

	// MPS 能力 (macOS only)
	hasMPS, mpsInfo := device.GetMPSCapability()
	fmt.Printf("MPS 信息 (Metal Performance Shaders):\n")
	fmt.Printf("  可用: %v\n", hasMPS)
	if hasMPS {
		fmt.Printf("  版本: %s\n", mpsInfo.Version)
	}
}
