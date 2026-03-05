export const formatDateTime = (value?: string | null): string => {
    if (!value) return '-';
    try {
        return new Date(value).toLocaleString();
    } catch {
        return value;
    }
};

export const computeDurationMs = (
    startedAt?: string | null,
    endedAt?: string | null,
    nowMs: number = Date.now(),
): number => {
    if (!startedAt) return 0;
    const start = new Date(startedAt).getTime();
    if (!Number.isFinite(start) || start <= 0) return 0;
    const end = endedAt ? new Date(endedAt).getTime() : nowMs;
    if (!Number.isFinite(end) || end <= 0) return 0;
    return Math.max(0, end - start);
};

export const formatDuration = (durationMs: number): string => {
    if (!Number.isFinite(durationMs) || durationMs <= 0) return '-';
    const totalSec = Math.floor(durationMs / 1000);
    const hours = Math.floor(totalSec / 3600);
    const mins = Math.floor((totalSec % 3600) / 60);
    const secs = totalSec % 60;
    if (hours > 0) return `${hours}h ${mins}m ${secs}s`;
    if (mins > 0) return `${mins}m ${secs}s`;
    return `${secs}s`;
};
