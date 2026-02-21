package device

import (
	"testing"
)

func TestBestDevice(t *testing.T) {
	cases := []struct {
		name string
		caps *DeviceCapabilities
		want string
	}{
		{
			name: "nil_caps_fallback_cpu",
			caps: nil,
			want: BestDeviceCPU,
		},
		{
			name: "cpu_only",
			caps: &DeviceCapabilities{
				CPU: &CPUInfo{LogicalCores: 8},
			},
			want: BestDeviceCPU,
		},
		{
			name: "mps_only",
			caps: &DeviceCapabilities{
				MPS: &MPSInfo{Available: true},
				CPU: &CPUInfo{LogicalCores: 8},
			},
			want: BestDeviceMPS,
		},
		{
			name: "cuda_only",
			caps: &DeviceCapabilities{
				CUDA: &CUDAInfo{Available: true, DeviceCount: 1},
				CPU:  &CPUInfo{LogicalCores: 8},
			},
			want: BestDeviceCUDA,
		},
		{
			name: "cuda_prior_higher_than_mps",
			caps: &DeviceCapabilities{
				CUDA: &CUDAInfo{Available: true, DeviceCount: 2},
				MPS:  &MPSInfo{Available: true},
				CPU:  &CPUInfo{LogicalCores: 8},
			},
			want: BestDeviceCUDA,
		},
	}

	for _, tc := range cases {
		tc := tc
		t.Run(tc.name, func(t *testing.T) {
			got := tc.caps.BestDevice()
			if got != tc.want {
				t.Fatalf("BestDevice mismatch: got=%s want=%s", got, tc.want)
			}
		})
	}
}

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
