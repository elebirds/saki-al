package device

import (
	"testing"
)

func TestDetectDeviceCapabilities(t *testing.T) {
	caps, err := DetectDeviceCapabilities()
	if err != nil {
		t.Fatalf("DetectDeviceCapabilities failed: %v", err)
	}

	if caps == nil {
		t.Fatal("DeviceCapabilities should not be nil")
	}

	// 检查平台信息
	if caps.Platform == "" {
		t.Error("Platform should not be empty")
	}
	t.Logf("Platform: %s\n", caps.Platform)

	// 检查 CPU 信息
	if caps.CPU == nil {
		t.Error("CPUInfo should not be nil")
	} else {
		t.Logf("CPU Model: %s\n", caps.CPU.ModelName)
		t.Logf("Physical Cores: %d\n", caps.CPU.PhysicalCores)
		t.Logf("Logical Cores: %d\n", caps.CPU.LogicalCores)
		t.Logf("Architecture: %s\n", caps.CPU.Architecture)
	}

	// 检查 CUDA 信息
	if caps.CUDA != nil {
		t.Logf("CUDA Available: %v\n", caps.CUDA.Available)
		if caps.CUDA.Available {
			t.Logf("CUDA Device Count: %d\n", caps.CUDA.DeviceCount)
			t.Logf("CUDA Device Names: %v\n", caps.CUDA.DeviceNames)
		}
	}

	// 检查 MPS 信息 (仅 macOS)
	if caps.MPS != nil {
		t.Logf("MPS Available: %v\n", caps.MPS.Available)
		if caps.MPS.Available {
			t.Logf("MPS Version: %s\n", caps.MPS.Version)
		}
	}
}

func TestGetCPUCapability(t *testing.T) {
	cpuInfo := GetCPUCapability()
	if cpuInfo == nil {
		t.Fatal("CPUInfo should not be nil")
	}

	t.Logf("CPU Model: %s\n", cpuInfo.ModelName)
	t.Logf("Physical Cores: %d\n", cpuInfo.PhysicalCores)
	t.Logf("Logical Cores: %d\n", cpuInfo.LogicalCores)
	t.Logf("Frequency: %.0f MHz\n", cpuInfo.Frequency)
	t.Logf("Architecture: %s\n", cpuInfo.Architecture)
}
