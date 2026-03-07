import {RuntimeExecutorRead, RuntimeExecutorPluginCapability} from '../../types';

export type ExecutorGpuCapability = {
    id: string;
    name: string;
    memoryMb: number | null;
    computeCapability: string;
    fp32Tflops: number | null;
};

export type ExecutorHostCapabilityView = {
    platform: string;
    arch: string;
    cpuWorkers: number | null;
    memoryMb: number | null;
    driverVersion: string;
    cudaVersion: string;
    gpus: ExecutorGpuCapability[];
};

const asRecord = (value: unknown): Record<string, any> =>
    value && typeof value === 'object' ? (value as Record<string, any>) : {};

const toText = (value: unknown, fallback: string = ''): string => {
    const text = String(value ?? '').trim();
    return text || fallback;
};

const toNumber = (value: unknown): number | null => {
    if (value === null || value === undefined || value === '') return null;
    const parsed = Number(value);
    if (!Number.isFinite(parsed)) return null;
    return parsed;
};

const formatMemory = (memoryMb: number | null): string => {
    if (memoryMb === null || memoryMb <= 0) return 'unknown';
    if (memoryMb >= 1024) {
        return `${(memoryMb / 1024).toFixed(1)} GB`;
    }
    return `${Math.trunc(memoryMb)} MB`;
};

const normalizeGpuRows = (hostCapability: Record<string, any>, resources: Record<string, any>): ExecutorGpuCapability[] => {
    const rows = Array.isArray(hostCapability.gpus) ? hostCapability.gpus : [];
    const gpus: ExecutorGpuCapability[] = rows
        .map((row: unknown, index: number) => {
            const item = asRecord(row);
            return {
                id: toText(item.id, String(index)),
                name: toText(item.name, 'unknown'),
                memoryMb: toNumber(item.memoryMb ?? item.memory_mb),
                computeCapability: toText(item.computeCapability ?? item.compute_capability, 'unknown'),
                fp32Tflops: toNumber(item.fp32Tflops ?? item.fp32_tflops),
            };
        })
        .filter((item) => item.id !== '');
    if (gpus.length > 0) {
        return gpus;
    }

    const accelerators = Array.isArray(resources.accelerators) ? resources.accelerators : [];
    const cuda = accelerators.find((row: any) => String(row?.type || '').toLowerCase() === 'cuda');
    if (!cuda) {
        return [];
    }
    const ids = Array.isArray(cuda.deviceIds)
        ? cuda.deviceIds.map((item: unknown) => String(item ?? '').trim()).filter(Boolean)
        : [];
    const count = Math.max(
        Number(cuda.deviceCount || 0),
        ids.length,
        Number(resources.gpuCount || resources.gpu_count || 0),
    );
    const fallbackRows: ExecutorGpuCapability[] = [];
    for (let idx = 0; idx < count; idx += 1) {
        fallbackRows.push({
            id: ids[idx] || String(idx),
            name: 'unknown',
            memoryMb: null,
            computeCapability: 'unknown',
            fp32Tflops: null,
        });
    }
    return fallbackRows;
};

export const extractExecutorHostCapability = (executor: RuntimeExecutorRead | null | undefined): ExecutorHostCapabilityView => {
    const resources = asRecord(executor?.resources);
    const hostCapability = asRecord(resources.hostCapability ?? resources.host_capability);
    const driverInfo = asRecord(hostCapability.driverInfo ?? hostCapability.driver_info);
    const gpus = normalizeGpuRows(hostCapability, resources);
    return {
        platform: toText(hostCapability.platform),
        arch: toText(hostCapability.arch),
        cpuWorkers: toNumber(
            hostCapability.cpuWorkers
            ?? hostCapability.cpu_workers
            ?? resources.cpuWorkers
            ?? resources.cpu_workers,
        ),
        memoryMb: toNumber(
            hostCapability.memoryMb
            ?? hostCapability.memory_mb
            ?? resources.memoryMb
            ?? resources.memory_mb,
        ),
        driverVersion: toText(driverInfo.driverVersion ?? driverInfo.driver_version),
        cudaVersion: toText(driverInfo.cudaVersion ?? driverInfo.cuda_version),
        gpus,
    };
};

export const buildExecutorCapabilitySummary = (executor: RuntimeExecutorRead): string => {
    const capability = extractExecutorHostCapability(executor);
    if (capability.gpus.length > 0) {
        const first = capability.gpus[0];
        const tflopsText = first.fp32Tflops !== null ? first.fp32Tflops.toFixed(1) : 'unknown';
        return `GPU ${first.name} x${capability.gpus.length} · ${formatMemory(first.memoryMb)} · CUDA ${capability.cudaVersion || 'unknown'} · ${tflopsText} TFLOPS`;
    }
    const cpuWorkersText = capability.cpuWorkers !== null ? String(Math.trunc(capability.cpuWorkers)) : 'unknown';
    return `CPU ${(capability.platform || 'unknown')}/${(capability.arch || 'unknown')} · ${cpuWorkersText} workers · ${formatMemory(capability.memoryMb)}`;
};

export const formatGpuDetailLine = (gpu: ExecutorGpuCapability): string => {
    const tflops = gpu.fp32Tflops !== null ? gpu.fp32Tflops.toFixed(1) : 'unknown';
    return `Memory ${formatMemory(gpu.memoryMb)} · Compute ${gpu.computeCapability || 'unknown'} · FP32 ${tflops} TFLOPS`;
};

export const executorSupportsPlugin = (
    executor: RuntimeExecutorRead,
    pluginId: string | undefined,
): boolean => {
    const normalizedPluginId = toText(pluginId);
    if (!normalizedPluginId) return true;
    const plugins = Array.isArray(executor.pluginIds?.plugins)
        ? (executor.pluginIds.plugins as RuntimeExecutorPluginCapability[])
        : [];
    if (plugins.length === 0) return true;
    return plugins.some((item) => toText(item.pluginId) === normalizedPluginId);
};
