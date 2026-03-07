import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Alert, Empty, Progress, Select, Spin, Tag, message } from 'antd';
import {useTranslation} from 'react-i18next';
import {
    Area,
    AreaChart,
    Bar,
    BarChart,
    CartesianGrid,
    Legend,
    ResponsiveContainer,
    Tooltip,
    XAxis,
    YAxis,
} from 'recharts';

import { api } from '../../services/api';
import {
    RuntimeExecutorListResponse,
    RuntimeExecutorPluginCapability,
    RuntimeExecutorRead,
    RuntimeExecutorStatsPoint,
    RuntimeExecutorStatsRange,
    RuntimeExecutorStatsResponse,
    RuntimeExecutorSummary,
} from '../../types';
import {
    buildExecutorCapabilitySummary,
    extractExecutorHostCapability,
    formatGpuDetailLine,
} from './executorCapability';

const POLLING_INTERVAL_MS = 10_000;

const STATUS_COLOR: Record<string, string> = {
    idle: 'success',
    reserved: 'processing',
    busy: 'processing',
    offline: 'default',
};

const RANGE_VALUES: RuntimeExecutorStatsRange[] = ['30m', '1h', '6h', '24h', '7d'];

const formatDateTime = (value?: string | null) => {
    if (!value) return '-';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    return date.toLocaleString();
};

const formatTickTime = (value: string, range: RuntimeExecutorStatsRange) => {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    if (range === '7d' || range === '24h') {
        return date.toLocaleDateString(undefined, { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
    }
    return date.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' });
};

const formatPercent = (ratio: number) => `${(ratio * 100).toFixed(2)}%`;

const formatAvailability = (available: boolean | null) => {
    if (available === true) return 'available';
    if (available === false) return 'unavailable';
    return 'unknown';
};

const extractPlugins = (executor: RuntimeExecutorRead | null): RuntimeExecutorPluginCapability[] => {
    if (!executor) return [];
    const raw = executor.pluginIds?.plugins;
    return Array.isArray(raw) ? raw : [];
};

const buildFallbackStats = (
    summary: RuntimeExecutorSummary | null | undefined,
    range: RuntimeExecutorStatsRange,
): RuntimeExecutorStatsResponse => {
    if (!summary) {
        return {
            range,
            bucketSeconds: 10,
            points: [],
        };
    }
    return {
        range,
        bucketSeconds: 10,
        points: [
            {
                ts: new Date().toISOString(),
                totalCount: summary.totalCount,
                onlineCount: summary.onlineCount,
                busyCount: summary.busyCount,
                availableCount: summary.availableCount,
                availabilityRate: summary.availabilityRate,
                pendingAssignCount: summary.pendingAssignCount,
                pendingStopCount: summary.pendingStopCount,
            },
        ],
    };
};

const RuntimeExecutors: React.FC = () => {
    const {t} = useTranslation();
    const [loading, setLoading] = useState(true);
    const [detailLoading, setDetailLoading] = useState(false);
    const [data, setData] = useState<RuntimeExecutorListResponse | null>(null);
    const [stats, setStats] = useState<RuntimeExecutorStatsResponse | null>(null);
    const [range, setRange] = useState<RuntimeExecutorStatsRange>('30m');
    const [selectedExecutorId, setSelectedExecutorId] = useState<string | null>(null);
    const [selectedExecutor, setSelectedExecutor] = useState<RuntimeExecutorRead | null>(null);
    const [detailOpen, setDetailOpen] = useState(false);
    const [statsApiSupported, setStatsApiSupported] = useState(true);
    const [lastUpdatedAt, setLastUpdatedAt] = useState<string | null>(null);
    const rangeOptions = useMemo(
        () => RANGE_VALUES.map((value) => ({value, label: t(`runtime.executors.range.${value}`)})),
        [t],
    );

    const selectedExecutorIdRef = useRef<string | null>(null);
    const detailOpenRef = useRef(false);

    useEffect(() => {
        selectedExecutorIdRef.current = selectedExecutorId;
    }, [selectedExecutorId]);

    useEffect(() => {
        detailOpenRef.current = detailOpen;
    }, [detailOpen]);

    const loadExecutorDetail = useCallback(async (executorId: string, silent: boolean = false) => {
        if (!silent) {
            setDetailLoading(true);
        }
        try {
            const detail = await api.getRuntimeExecutor(executorId);
            setSelectedExecutor(detail);
        } catch (error: any) {
            if (!silent) {
                message.error(error?.message || t('runtime.executors.messages.loadDetailFailed'));
            }
        } finally {
            if (!silent) {
                setDetailLoading(false);
            }
        }
    }, []);

    const loadDashboard = useCallback(async (silent: boolean = false) => {
        if (!silent) {
            setLoading(true);
        }
        try {
            const resp = await api.getRuntimeExecutors();
            setData(resp);

            const currentSelectedId = selectedExecutorIdRef.current;
            if (currentSelectedId) {
                const matched = resp.items.find((item) => item.executorId === currentSelectedId) || null;
                if (!matched) {
                    setSelectedExecutorId(null);
                    setSelectedExecutor(null);
                    setDetailOpen(false);
                } else {
                    setSelectedExecutor((prev) => {
                        if (!prev || prev.executorId !== matched.executorId) {
                            return matched;
                        }
                        return {
                            ...prev,
                            ...matched,
                        };
                    });
                }
            }

            if (statsApiSupported) {
                try {
                    const trend = await api.getRuntimeExecutorStats(range);
                    setStats(trend);
                } catch (error: any) {
                    const statusCode = Number(error?.statusCode || error?.originalError?.response?.status || 0);
                    if (statusCode === 400 || statusCode === 404 || statusCode === 405) {
                        setStatsApiSupported(false);
                    }
                    setStats(buildFallbackStats(resp.summary, range));
                }
            } else {
                setStats(buildFallbackStats(resp.summary, range));
            }

            if (detailOpenRef.current && currentSelectedId) {
                await loadExecutorDetail(currentSelectedId, true);
            }

            setLastUpdatedAt(new Date().toISOString());
        } catch (error: any) {
            if (!silent) {
                message.error(error?.message || t('runtime.executors.messages.loadStatusFailed'));
            }
        } finally {
            if (!silent) {
                setLoading(false);
            }
        }
    }, [range, statsApiSupported, loadExecutorDetail]);

    useEffect(() => {
        void loadDashboard(false);
    }, [loadDashboard]);

    useEffect(() => {
        const timer = window.setInterval(() => {
            void loadDashboard(true);
        }, POLLING_INTERVAL_MS);

        return () => window.clearInterval(timer);
    }, [loadDashboard]);

    const summary = data?.summary;
    const plugins = useMemo(() => extractPlugins(selectedExecutor), [selectedExecutor]);
    const selectedExecutorCapability = useMemo(
        () => extractExecutorHostCapability(selectedExecutor),
        [selectedExecutor],
    );
    const hasSelectedExecutorCpuInfo = useMemo(
        () => (
            Boolean(selectedExecutorCapability.platform)
            || Boolean(selectedExecutorCapability.arch)
            || selectedExecutorCapability.cpuWorkers !== null
            || selectedExecutorCapability.memoryMb !== null
            || selectedExecutorCapability.mpsAvailable !== null
        ),
        [selectedExecutorCapability],
    );
    const trendData = useMemo<RuntimeExecutorStatsPoint[]>(() => {
        if (!stats?.points?.length) return [];
        return [...stats.points].sort((a, b) => new Date(a.ts).getTime() - new Date(b.ts).getTime());
    }, [stats]);

    const chartData = useMemo(() => {
        return trendData.map((item) => {
            const total = Math.max(item.totalCount, 0);
            const busy = Math.max(item.busyCount, 0);
            const offline = Math.max(total - item.onlineCount, 0);
            const idle = Math.max(total - busy - offline, 0);
            const base = total > 0 ? total : 1;

            return {
                ...item,
                busyCountDerived: busy,
                idleCountDerived: idle,
                offlineCountDerived: offline,
                busyPercent: (busy / base) * 100,
                idlePercent: (idle / base) * 100,
                offlinePercent: (offline / base) * 100,
            };
        });
    }, [trendData]);

    const openDetail = async (executorId: string) => {
        setSelectedExecutorId(executorId);
        setDetailOpen(true);
        await loadExecutorDetail(executorId, false);
    };

    const closeDetail = () => {
        setDetailOpen(false);
    };

    if (loading) {
        return (
            <div className="flex h-full items-center justify-center">
                <Spin size="large" />
            </div>
        );
    }

    return (
        <>
            <div className="h-full min-h-0 overflow-hidden">
                <div className="rounded-md border border-github-border bg-github-panel p-4 mb-4">
                    <div className="flex flex-wrap items-center justify-between gap-3">
                        <div>
                            <h2 className="text-lg font-semibold text-github-text">{t('runtime.executors.title')}</h2>
                            <div className="mt-2 text-xs text-github-muted">
                                {t('runtime.executors.lastUpdated')}: {formatDateTime(lastUpdatedAt)}
                                {!statsApiSupported ? t('runtime.executors.realtimeSnapshotHint') : ''}
                            </div>
                        </div>
                        <Select
                            value={range}
                            style={{ width: 160 }}
                            options={rangeOptions}
                            onChange={(value) => setRange(value as RuntimeExecutorStatsRange)}
                        />
                    </div>
                </div>
                <div className="grid h-full min-h-0 grid-cols-1 gap-4 xl:grid-cols-[4fr_6fr]">
                    <section className="min-h-0 overflow-auto pr-1">
                        <div className="flex flex-col gap-4">

                            {summary ? (
                                <div className="grid grid-cols-4 gap-3">
                                    <div className="rounded-md border border-github-border bg-github-panel p-3">
                                        <div className="text-xs text-github-muted">{t('runtime.executors.summary.total')}</div>
                                        <div className="text-2xl font-semibold text-github-text">{summary.totalCount}</div>
                                    </div>
                                    <div className="rounded-md border border-github-border bg-github-panel p-3">
                                        <div className="text-xs text-github-muted">{t('runtime.executors.summary.online')}</div>
                                        <div className="text-2xl font-semibold text-github-text">{summary.onlineCount}</div>
                                    </div>
                                    <div className="rounded-md border border-github-border bg-github-panel p-3">
                                        <div className="text-xs text-github-muted">{t('runtime.executors.summary.busy')}</div>
                                        <div className="text-2xl font-semibold text-github-text">{summary.busyCount}</div>
                                    </div>
                                    <div className="rounded-md border border-github-border bg-github-panel p-3">
                                        <div className="text-xs text-github-muted">{t('runtime.executors.summary.available')}</div>
                                        <div className="text-2xl font-semibold text-github-text">{summary.availableCount}</div>
                                    </div>
                                </div>
                            ) : null}

                            <div className="rounded-md border border-github-border bg-github-panel p-4">
                                <div className="mb-2 text-sm font-medium text-github-text">{t('runtime.executors.availabilityTitle')}</div>
                                <Progress percent={Number(((summary?.availabilityRate || 0) * 100).toFixed(2))} />
                                <div className="mt-2 text-xs text-github-muted">
                                    {t('runtime.executors.currentAvailability', {value: formatPercent(summary?.availabilityRate || 0)})}，
                                    pending assign: {summary?.pendingAssignCount || 0}，
                                    pending stop: {summary?.pendingStopCount || 0}，
                                    latest heartbeat: {formatDateTime(summary?.latestHeartbeatAt)}
                                </div>
                            </div>

                            <div className="rounded-md border border-github-border bg-github-panel p-4">
                                <div className="mb-3 text-sm font-medium text-github-text">{t('runtime.executors.trendPercentTitle')}</div>
                                <div className="h-[250px]">
                                    {chartData.length === 0 ? (
                                        <Empty description={t('runtime.executors.emptyTrend')} image={Empty.PRESENTED_IMAGE_SIMPLE} />
                                    ) : (
                                        <ResponsiveContainer width="100%" height="100%">
                                            <AreaChart data={chartData}>
                                                <CartesianGrid strokeDasharray="3 3" />
                                                <XAxis
                                                    dataKey="ts"
                                                    minTickGap={24}
                                                    tickFormatter={(value) => formatTickTime(String(value), range)}
                                                />
                                                <YAxis domain={[0, 100]} unit="%" />
                                                <Tooltip
                                                    labelFormatter={(value) => formatDateTime(String(value))}
                                                    formatter={(value: number) => `${Number(value).toFixed(2)}%`}
                                                />
                                                <Legend />
                                                <Area type="monotone" dataKey="busyPercent" stackId="percent" name={t('runtime.executors.status.busy')} stroke="#fa8c16" fill="#fa8c16" fillOpacity={0.8} isAnimationActive={false} />
                                                <Area type="monotone" dataKey="idlePercent" stackId="percent" name={t('runtime.executors.status.idle')} stroke="#52c41a" fill="#52c41a" fillOpacity={0.8} isAnimationActive={false} />
                                                <Area type="monotone" dataKey="offlinePercent" stackId="percent" name={t('runtime.executors.status.offline')} stroke="#8c8c8c" fill="#8c8c8c" fillOpacity={0.8} isAnimationActive={false} />
                                            </AreaChart>
                                        </ResponsiveContainer>
                                    )}
                                </div>
                            </div>

                            <div className="rounded-md border border-github-border bg-github-panel p-4">
                                <div className="mb-3 text-sm font-medium text-github-text">{t('runtime.executors.trendCountTitle')}</div>
                                <div className="h-[270px]">
                                    {chartData.length === 0 ? (
                                        <Empty description={t('runtime.executors.emptyTrend')} image={Empty.PRESENTED_IMAGE_SIMPLE} />
                                    ) : (
                                        <ResponsiveContainer width="100%" height="100%">
                                            <BarChart data={chartData}>
                                                <CartesianGrid strokeDasharray="3 3" />
                                                <XAxis
                                                    dataKey="ts"
                                                    minTickGap={24}
                                                    tickFormatter={(value) => formatTickTime(String(value), range)}
                                                />
                                                <YAxis allowDecimals={false} />
                                                <Tooltip labelFormatter={(value) => formatDateTime(String(value))} />
                                                <Legend />
                                                <Bar dataKey="busyCountDerived" stackId="status" name={t('runtime.executors.status.busy')} fill="#fa8c16" isAnimationActive={false} />
                                                <Bar dataKey="idleCountDerived" stackId="status" name={t('runtime.executors.status.idle')} fill="#52c41a" isAnimationActive={false} />
                                                <Bar dataKey="offlineCountDerived" stackId="status" name={t('runtime.executors.status.offline')} fill="#8c8c8c" isAnimationActive={false} />
                                            </BarChart>
                                        </ResponsiveContainer>
                                    )}
                                </div>
                            </div>
                        </div>
                    </section>

                    <section className="min-h-0 overflow-hidden rounded-md border border-github-border bg-github-panel">
                        <div className="border-b border-github-border px-4 py-3">
                            <div className="flex items-center justify-between">
                                <h2 className="text-base font-semibold text-github-text">{t('runtime.executors.listTitle')}</h2>
                                <span className="text-xs text-github-muted">{t('runtime.executors.listTotal', {count: data?.items.length || 0})}</span>
                            </div>
                        </div>

                        {!data || data.items.length === 0 ? (
                            <div className="flex h-full items-center justify-center">
                                <Empty description={t('runtime.executors.emptyList')} />
                            </div>
                        ) : (
                            <div className="min-h-0 h-[calc(100%-52px)] overflow-auto">
                                <table className="min-w-full border-collapse text-sm">
                                    <thead className="sticky top-0 z-10 bg-github-header">
                                        <tr className="border-b border-github-border">
                                            <th className="px-4 py-3 text-left font-medium text-github-muted">Executor</th>
                                            <th className="px-4 py-3 text-left font-medium text-github-muted">{t('runtime.executors.table.status')}</th>
                                            <th className="px-4 py-3 text-left font-medium text-github-muted">{t('runtime.executors.table.online')}</th>
                                            <th className="px-4 py-3 text-left font-medium text-github-muted">{t('runtime.executors.table.currentStep')}</th>
                                            <th className="px-4 py-3 text-left font-medium text-github-muted">{t('runtime.executors.table.pending')}</th>
                                            <th className="px-4 py-3 text-left font-medium text-github-muted">{t('runtime.executors.table.lastHeartbeat')}</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {data.items.map((row) => {
                                            const active = row.executorId === selectedExecutorId;
                                            return (
                                                <tr
                                                    key={row.executorId}
                                                    className={`cursor-pointer border-b border-github-border-muted transition-colors hover:bg-github-header ${active ? 'bg-github-header' : ''}`}
                                                    onClick={() => {
                                                        void openDetail(row.executorId);
                                                    }}
                                                >
                                                    <td className="px-4 py-3 align-top">
                                                        <code className="rounded bg-github-badge px-1 py-0.5 text-xs">{row.executorId}</code>
                                                        <div className="mt-1 text-xs text-github-muted">
                                                            {buildExecutorCapabilitySummary(row)}
                                                        </div>
                                                    </td>
                                                    <td className="px-4 py-3 align-top">
                                                        <Tag color={STATUS_COLOR[row.status] || 'default'}>{row.status}</Tag>
                                                    </td>
                                                    <td className="px-4 py-3 align-top">
                                                        {row.isOnline ? <Tag color="success">online</Tag> : <Tag>offline</Tag>}
                                                    </td>
                                                    <td className="px-4 py-3 align-top">
                                                        {row.currentTaskId ? <code className="text-xs">{row.currentTaskId}</code> : '-'}
                                                    </td>
                                                    <td className="px-4 py-3 align-top">{row.pendingAssignCount}/{row.pendingStopCount}</td>
                                                    <td className="px-4 py-3 align-top text-xs text-github-muted">{formatDateTime(row.lastSeenAt)}</td>
                                                </tr>
                                            );
                                        })}
                                    </tbody>
                                </table>
                            </div>
                        )}
                    </section>
                </div>
            </div>

            <div className={`fixed inset-0 z-50 ${detailOpen ? 'pointer-events-auto' : 'pointer-events-none'}`}>
                <div
                    className={`absolute inset-0 bg-black/35 transition-opacity duration-200 ${detailOpen ? 'opacity-100' : 'opacity-0'}`}
                    onClick={closeDetail}
                />
                <aside
                    role="dialog"
                    aria-modal="true"
                    className={`absolute right-0 top-0 h-full w-full max-w-[560px] border-l border-github-border bg-github-header shadow-2xl transition-transform duration-200 ${detailOpen ? 'translate-x-0' : 'translate-x-full'}`}
                    style={{ backgroundColor: 'var(--github-header)' }}
                >
                    <div className="flex h-full flex-col">
                        <div className="flex items-center justify-between border-b border-github-border px-4 py-3">
                            <h3 className="text-base font-semibold text-github-text">{t('runtime.executors.detailTitle')}</h3>
                            <button
                                type="button"
                                className="rounded border border-github-border px-2 py-1 text-sm text-github-muted hover:bg-github-header"
                                onClick={closeDetail}
                            >
                                {t('common.close')}
                            </button>
                        </div>

                        <div className="min-h-0 flex-1 overflow-auto bg-github-header p-4" style={{ backgroundColor: 'var(--github-header)' }}>
                            {detailLoading ? (
                                <div className="flex h-full items-center justify-center">
                                    <Spin size="large" />
                                </div>
                            ) : !selectedExecutor ? (
                                <Empty description={t('runtime.executors.selectExecutor')} />
                            ) : (
                                <div className="space-y-4">
                                    <div className="rounded-md border border-github-border bg-github-panel p-3 shadow-sm" style={{ backgroundColor: 'var(--github-panel)' }}>
                                        <div className="grid grid-cols-1 gap-3 text-sm">
                                            <div>
                                                <div className="text-xs text-github-muted">Executor ID</div>
                                                <code className="text-xs">{selectedExecutor.executorId}</code>
                                            </div>
                                            <div>
                                                <div className="text-xs text-github-muted">{t('runtime.executors.detail.version')}</div>
                                                <div>{selectedExecutor.version || '-'}</div>
                                            </div>
                                            <div>
                                                <div className="text-xs text-github-muted">{t('runtime.executors.detail.status')}</div>
                                                <Tag color={STATUS_COLOR[selectedExecutor.status] || 'default'}>{selectedExecutor.status}</Tag>
                                            </div>
                                            <div>
                                                <div className="text-xs text-github-muted">{t('runtime.executors.table.currentStep')}</div>
                                                <div>{selectedExecutor.currentTaskId || '-'}</div>
                                            </div>
                                            <div>
                                                <div className="text-xs text-github-muted">{t('runtime.executors.detail.pending')}</div>
                                                <div>{selectedExecutor.pendingAssignCount}/{selectedExecutor.pendingStopCount}</div>
                                            </div>
                                            <div>
                                                <div className="text-xs text-github-muted">{t('runtime.executors.table.lastHeartbeat')}</div>
                                                <div>{formatDateTime(selectedExecutor.lastSeenAt)}</div>
                                            </div>
                                        </div>
                                    </div>

                                    {selectedExecutor.lastError ? (
                                        <Alert type="error" showIcon message={selectedExecutor.lastError} />
                                    ) : null}

                                    <div className="rounded-md border border-github-border bg-github-panel p-3 shadow-sm" style={{ backgroundColor: 'var(--github-panel)' }}>
                                        <div className="mb-2 text-sm font-medium text-github-text">{t('runtime.executors.hardware')}</div>
                                        {selectedExecutorCapability.gpus.length === 0 && hasSelectedExecutorCpuInfo ? (
                                            <div className="space-y-2">
                                                <div className="rounded border border-github-border-muted bg-github-header p-2" style={{ backgroundColor: 'var(--github-header)' }}>
                                                    <div className="text-sm font-medium text-github-text">
                                                        {t('runtime.executors.detail.cpuHostInfo')}
                                                    </div>
                                                    <div className="mt-1 text-xs text-github-muted">
                                                        platform={selectedExecutorCapability.platform || 'unknown'} · arch={selectedExecutorCapability.arch || 'unknown'}
                                                    </div>
                                                    <div className="mt-1 text-xs text-github-muted">
                                                        cpu_workers={selectedExecutorCapability.cpuWorkers ?? 'unknown'} · memory_mb={selectedExecutorCapability.memoryMb ?? 'unknown'}
                                                    </div>
                                                    <div className="mt-1 text-xs text-github-muted">
                                                        mps={formatAvailability(selectedExecutorCapability.mpsAvailable)}
                                                    </div>
                                                </div>
                                            </div>
                                        ) : (
                                            <div className="space-y-2">
                                                <div className="rounded border border-github-border-muted bg-github-header p-2 text-xs text-github-muted" style={{ backgroundColor: 'var(--github-header)' }}>
                                                    driver={selectedExecutorCapability.driverVersion || 'unknown'} · CUDA={selectedExecutorCapability.cudaVersion || 'unknown'}
                                                </div>
                                                {selectedExecutorCapability.gpus.map((gpu) => (
                                                    <div key={gpu.id} className="rounded border border-github-border-muted bg-github-header p-2" style={{ backgroundColor: 'var(--github-header)' }}>
                                                        <div className="text-sm font-medium text-github-text">{gpu.name || 'unknown'}</div>
                                                        <div className="mt-1 text-xs text-github-muted">GPU #{gpu.id}</div>
                                                        <div className="mt-1 text-xs text-github-muted">{formatGpuDetailLine(gpu)}</div>
                                                    </div>
                                                ))}
                                            </div>
                                        )}
                                        {selectedExecutorCapability.gpus.length === 0 && !hasSelectedExecutorCpuInfo ? (
                                            <Empty description={t('runtime.executors.noHardware')} image={Empty.PRESENTED_IMAGE_SIMPLE} />
                                        ) : null}
                                    </div>

                                    <div className="rounded-md border border-github-border bg-github-panel p-3 shadow-sm" style={{ backgroundColor: 'var(--github-panel)' }}>
                                        <div className="mb-2 text-sm font-medium text-github-text">{t('runtime.executors.pluginCapability', {count: plugins.length})}</div>
                                        {plugins.length === 0 ? (
                                            <Empty description={t('runtime.executors.noPluginCapability')} image={Empty.PRESENTED_IMAGE_SIMPLE} />
                                        ) : (
                                            <div className="space-y-2">
                                                {plugins.map((plugin) => (
                                                    <div key={plugin.pluginId} className="rounded border border-github-border-muted bg-github-header p-2" style={{ backgroundColor: 'var(--github-header)' }}>
                                                        <div className="flex items-start justify-between gap-2">
                                                            <div>
                                                                <div className="text-sm font-medium text-github-text">{plugin.displayName || plugin.pluginId}</div>
                                                                <div className="text-xs text-github-muted">{plugin.pluginId}</div>
                                                            </div>
                                                            <div className="text-xs text-github-muted">v{plugin.version || '-'}</div>
                                                        </div>
                                                        <div className="mt-2 flex flex-wrap gap-1">
                                                            {(plugin.supportedStrategies || []).length === 0 ? (
                                                                <span className="text-xs text-github-muted">{t('runtime.executors.noStrategy')}</span>
                                                            ) : (
                                                                plugin.supportedStrategies.map((item) => (
                                                                    <Tag key={item}>{item}</Tag>
                                                                ))
                                                            )}
                                                        </div>
                                                        <div className="mt-2 flex flex-wrap gap-1">
                                                            {(plugin.supportedAccelerators || []).length === 0 ? (
                                                                <span className="text-xs text-github-muted">{t('runtime.executors.noAccelerator')}</span>
                                                            ) : (
                                                                plugin.supportedAccelerators.map((item) => (
                                                                    <Tag key={item} color="blue">{item}</Tag>
                                                                ))
                                                            )}
                                                            <Tag color={plugin.supportsAutoFallback ? 'success' : 'default'}>
                                                                auto fallback: {plugin.supportsAutoFallback ? 'on' : 'off'}
                                                            </Tag>
                                                        </div>
                                                    </div>
                                                ))}
                                            </div>
                                        )}
                                    </div>
                                </div>
                            )}
                        </div>
                    </div>
                </aside>
            </div>
        </>
    );
};

export default RuntimeExecutors;
