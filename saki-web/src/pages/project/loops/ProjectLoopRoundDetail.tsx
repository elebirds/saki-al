import React, {useCallback, useEffect, useMemo, useRef, useState} from 'react';
import {
    App,
    Alert,
    Button,
    Card,
    Descriptions,
    Empty,
    Image,
    List,
    Progress,
    Spin,
    Table,
    Tag,
    Typography,
} from 'antd';
import {
    CartesianGrid,
    Line,
    LineChart,
    ResponsiveContainer,
    Tooltip,
    XAxis,
    YAxis,
} from 'recharts';
import {useNavigate, useParams} from 'react-router-dom';

import {useResourcePermission} from '../../../hooks';
import {api} from '../../../services/api';
import {useAuthStore} from '../../../store/authStore';
import {
    RuntimeRound,
    RuntimeStep,
    RuntimeStepArtifact,
    RuntimeStepCandidate,
    RuntimeStepEvent,
    RuntimeStepMetricPoint,
} from '../../../types';

const {Text, Title} = Typography;

const ROUND_STATE_COLOR: Record<string, string> = {
    pending: 'default',
    running: 'processing',
    completed: 'success',
    failed: 'error',
    cancelled: 'warning',
};

const STEP_STATE_COLOR: Record<string, string> = {
    pending: 'default',
    ready: 'processing',
    dispatching: 'processing',
    running: 'processing',
    retrying: 'warning',
    succeeded: 'success',
    failed: 'error',
    cancelled: 'warning',
    skipped: 'default',
};

const TERMINAL_STEP_STATE = new Set(['succeeded', 'failed', 'cancelled', 'skipped']);

const formatDateTime = (value?: string | null) => {
    if (!value) return '-';
    try {
        return new Date(value).toLocaleString();
    } catch {
        return value;
    }
};

const buildWsUrl = (stepId: string, afterSeq: number, token: string): string => {
    const apiBaseUrlRaw = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api/v1';
    const apiBaseUrl = apiBaseUrlRaw.endsWith('/') ? apiBaseUrlRaw.slice(0, -1) : apiBaseUrlRaw;
    const suffix = `/steps/${stepId}/events/ws?after_seq=${afterSeq}&token=${encodeURIComponent(token)}`;
    if (apiBaseUrl.startsWith('http://') || apiBaseUrl.startsWith('https://')) {
        return `${apiBaseUrl.replace(/^http/, 'ws')}${suffix}`;
    }
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const path = apiBaseUrl.startsWith('/') ? apiBaseUrl : `/${apiBaseUrl}`;
    return `${protocol}//${window.location.host}${path}${suffix}`;
};

type RawRuntimeStepEvent = {
    seq?: unknown;
    ts?: unknown;
    eventType?: unknown;
    event_type?: unknown;
    payload?: unknown;
};

const normalizeWsEvent = (raw: RawRuntimeStepEvent): RuntimeStepEvent | null => {
    const seq = Number(raw.seq);
    if (!Number.isFinite(seq)) return null;
    const eventTypeRaw = raw.eventType ?? raw.event_type;
    const eventType = String(eventTypeRaw || 'unknown_event');
    const ts = typeof raw.ts === 'string' ? raw.ts : new Date().toISOString();
    const payload = raw.payload && typeof raw.payload === 'object' ? (raw.payload as Record<string, any>) : {};
    return {seq, ts, eventType, payload};
};

const eventToText = (event: RuntimeStepEvent): string => {
    if (event.eventType === 'log') {
        return `[${event.payload.level || 'INFO'}] ${event.payload.message || ''}`;
    }
    if (event.eventType === 'status') {
        return `状态 => ${event.payload.status || ''} ${event.payload.reason || ''}`.trim();
    }
    if (event.eventType === 'progress') {
        return `进度 epoch=${event.payload.epoch ?? '-'} step=${event.payload.step ?? '-'} / ${event.payload.totalSteps ?? event.payload.total_steps ?? '-'}`;
    }
    if (event.eventType === 'metric') {
        return `指标 ${JSON.stringify(event.payload.metrics || {})}`;
    }
    if (event.eventType === 'artifact') {
        return `制品 ${event.payload.name || ''} -> ${event.payload.uri || ''}`;
    }
    return `${event.eventType} ${JSON.stringify(event.payload || {})}`;
};

const isImageArtifact = (artifact: RuntimeStepArtifact): boolean => {
    const name = (artifact.name || '').toLowerCase();
    const kind = (artifact.kind || '').toLowerCase();
    return (
        kind.includes('confusion_matrix') ||
        kind.includes('image') ||
        name.endsWith('.png') ||
        name.endsWith('.jpg') ||
        name.endsWith('.jpeg') ||
        name.endsWith('.webp')
    );
};

const pickDefaultStep = (steps: RuntimeStep[]): RuntimeStep | null => {
    if (steps.length === 0) return null;
    const sortByStepIndexDesc = (left: RuntimeStep, right: RuntimeStep) => (right.stepIndex || 0) - (left.stepIndex || 0);
    const latestFailed = [...steps].filter((item) => item.state === 'failed').sort(sortByStepIndexDesc)[0];
    return (
        steps.find((item) => ['running', 'dispatching', 'retrying'].includes(item.state))
        || latestFailed
        || steps.find((item) => item.state === 'ready')
        || steps.find((item) => item.state === 'pending')
        || steps[steps.length - 1]
    );
};

const ProjectLoopRoundDetail: React.FC = () => {
    const {projectId, loopId, roundId} = useParams<{ projectId: string; loopId: string; roundId: string }>();
    const navigate = useNavigate();
    const {message: messageApi} = App.useApp();
    const token = useAuthStore((state) => state.token);
    const {can: canProject} = useResourcePermission('project', projectId);
    const canManageLoops = canProject('loop:manage:assigned');

    const [loading, setLoading] = useState(true);
    const [refreshing, setRefreshing] = useState(false);
    const [retrying, setRetrying] = useState(false);
    const [round, setRound] = useState<RuntimeRound | null>(null);
    const [steps, setSteps] = useState<RuntimeStep[]>([]);
    const [selectedStepId, setSelectedStepId] = useState<string>('');
    const [selectedStep, setSelectedStep] = useState<RuntimeStep | null>(null);
    const [metricPoints, setMetricPoints] = useState<RuntimeStepMetricPoint[]>([]);
    const [candidates, setCandidates] = useState<RuntimeStepCandidate[]>([]);
    const [events, setEvents] = useState<RuntimeStepEvent[]>([]);
    const [artifacts, setArtifacts] = useState<RuntimeStepArtifact[]>([]);
    const [wsConnected, setWsConnected] = useState(false);
    const [artifactUrls, setArtifactUrls] = useState<Record<string, string>>({});

    const eventCursorRef = useRef<number>(0);

    const metricNames = useMemo(() => {
        const names = new Set<string>();
        metricPoints.forEach((item) => names.add(item.metricName));
        return Array.from(names);
    }, [metricPoints]);

    const metricChartData = useMemo(() => {
        const rows = new Map<number, Record<string, number>>();
        metricPoints.forEach((point) => {
            const stepKey = Number(point.step || 0);
            const current = rows.get(stepKey) || {step: stepKey};
            current[point.metricName] = Number(point.metricValue);
            rows.set(stepKey, current);
        });
        return Array.from(rows.values()).sort((a, b) => (a.step || 0) - (b.step || 0));
    }, [metricPoints]);

    const imageArtifacts = useMemo(() => artifacts.filter((item) => isImageArtifact(item)), [artifacts]);

    const ensureArtifactUrls = useCallback(async (stepId: string, items: RuntimeStepArtifact[]) => {
        if (!stepId || items.length === 0) return;
        const missing = items.filter((item) => !artifactUrls[item.name]);
        if (missing.length === 0) return;

        const updates: Record<string, string> = {};
        for (const artifact of missing) {
            const uri = String(artifact.uri || '');
            if (uri.startsWith('http://') || uri.startsWith('https://')) {
                updates[artifact.name] = uri;
                continue;
            }
            if (!uri.startsWith('s3://')) continue;
            try {
                const row = await api.getStepArtifactDownloadUrl(stepId, artifact.name, 2);
                updates[artifact.name] = row.downloadUrl;
            } catch {
                // ignore unavailable artifacts
            }
        }

        if (Object.keys(updates).length > 0) {
            setArtifactUrls((prev) => ({...prev, ...updates}));
        }
    }, [artifactUrls]);

    const loadStepDashboard = useCallback(async (stepId: string) => {
        const [stepRow, points, topk, artifactsResp, initialEvents] = await Promise.all([
            api.getStep(stepId),
            api.getStepMetricSeries(stepId, 5000),
            api.getStepCandidates(stepId, 200),
            api.getStepArtifacts(stepId),
            api.getStepEvents(stepId, 0, 5000),
        ]);
        setSelectedStep(stepRow);
        setMetricPoints(points);
        setCandidates(topk);
        setArtifacts(artifactsResp.artifacts || []);
        setEvents(initialEvents);
        eventCursorRef.current = initialEvents.reduce((max, item) => Math.max(max, item.seq), 0);
        await ensureArtifactUrls(stepId, artifactsResp.artifacts || []);
    }, [ensureArtifactUrls]);

    const loadRoundDashboard = useCallback(async () => {
        if (!roundId || !canManageLoops) return;
        const [roundRow, stepRows] = await Promise.all([
            api.getRound(roundId),
            api.getRoundSteps(roundId, 2000),
        ]);
        setRound(roundRow);
        setSteps(stepRows);

        const chosenStep = stepRows.find((item) => item.id === selectedStepId) || pickDefaultStep(stepRows);
        if (chosenStep) {
            setSelectedStepId(chosenStep.id);
            await loadStepDashboard(chosenStep.id);
        } else {
            setSelectedStepId('');
            setSelectedStep(null);
            setMetricPoints([]);
            setCandidates([]);
            setArtifacts([]);
            setEvents([]);
        }
    }, [roundId, selectedStepId, loadStepDashboard, canManageLoops]);

    const loadData = useCallback(async (silent: boolean = false) => {
        if (!roundId || !canManageLoops) return;
        if (!silent) setLoading(true);
        if (silent) setRefreshing(true);
        try {
            await loadRoundDashboard();
        } catch (error: any) {
            messageApi.error(error?.message || '加载 Round 详情失败');
        } finally {
            setLoading(false);
            setRefreshing(false);
        }
    }, [roundId, loadRoundDashboard, canManageLoops]);

    const handleRetryRound = useCallback(async () => {
        if (!round || !loopId) return;
        setRetrying(true);
        try {
            await api.actLoop(loopId, {
                action: 'retry_round',
                payload: {roundId: round.id, reason: 'round detail retry'},
            });
            messageApi.success('已触发重跑');
            await loadData(false);
        } catch (error: any) {
            messageApi.error(error?.message || '重跑失败');
        } finally {
            setRetrying(false);
        }
    }, [round, loopId, loadData, messageApi]);

    useEffect(() => {
        if (!canManageLoops) return;
        void loadData(false);
    }, [canManageLoops, loadData]);

    useEffect(() => {
        if (!canManageLoops || !selectedStepId) return;
        const timer = window.setInterval(async () => {
            try {
                const [latestRound, latestSteps, newEvents, latestStep] = await Promise.all([
                    api.getRound(roundId as string),
                    api.getRoundSteps(roundId as string, 2000),
                    api.getStepEvents(selectedStepId, eventCursorRef.current, 5000),
                    api.getStep(selectedStepId),
                ]);

                setRound(latestRound);
                setSteps(latestSteps);
                setSelectedStep(latestStep);

                if (newEvents.length > 0) {
                    setEvents((prev) => {
                        const merged = [...prev, ...newEvents];
                        const dedup = new Map<number, RuntimeStepEvent>();
                        merged.forEach((item) => dedup.set(item.seq, item));
                        return Array.from(dedup.values()).sort((a, b) => a.seq - b.seq);
                    });
                    eventCursorRef.current = Math.max(eventCursorRef.current, ...newEvents.map((item) => item.seq));
                }

                const shouldRefreshMetrics =
                    latestStep.state === 'running' ||
                    latestStep.state === 'dispatching' ||
                    newEvents.some((item) => item.eventType === 'metric');
                const shouldRefreshArtifacts =
                    newEvents.some((item) => item.eventType === 'artifact') ||
                    TERMINAL_STEP_STATE.has(latestStep.state);

                if (shouldRefreshMetrics) {
                    const points = await api.getStepMetricSeries(selectedStepId, 5000);
                    setMetricPoints(points);
                }
                if (shouldRefreshArtifacts) {
                    const artifactsResp = await api.getStepArtifacts(selectedStepId);
                    setArtifacts(artifactsResp.artifacts || []);
                    await ensureArtifactUrls(selectedStepId, artifactsResp.artifacts || []);
                }
                if (TERMINAL_STEP_STATE.has(latestStep.state)) {
                    const topk = await api.getStepCandidates(selectedStepId, 200);
                    setCandidates(topk);
                }
            } catch {
                // ignore polling errors
            }
        }, 3000);
        return () => window.clearInterval(timer);
    }, [canManageLoops, selectedStepId, roundId, ensureArtifactUrls]);

    useEffect(() => {
        if (!canManageLoops || !selectedStepId || !token) return;
        const ws = new WebSocket(buildWsUrl(selectedStepId, eventCursorRef.current, token));
        ws.onopen = () => setWsConnected(true);
        ws.onclose = () => setWsConnected(false);
        ws.onerror = () => setWsConnected(false);
        ws.onmessage = (event: MessageEvent<string>) => {
            try {
                const raw = JSON.parse(event.data || '{}') as RawRuntimeStepEvent;
                const payload = normalizeWsEvent(raw);
                if (!payload) return;
                setEvents((prev) => {
                    const merged = [...prev, payload];
                    const dedup = new Map<number, RuntimeStepEvent>();
                    merged.forEach((item) => dedup.set(item.seq, item));
                    return Array.from(dedup.values()).sort((a, b) => a.seq - b.seq);
                });
                eventCursorRef.current = Math.max(eventCursorRef.current, payload.seq);
            } catch {
                // ignore malformed ws payload
            }
        };
        return () => {
            ws.close();
            setWsConnected(false);
        };
    }, [canManageLoops, selectedStepId, token]);

    if (loading) {
        return (
            <div className="flex h-full items-center justify-center">
                <Spin size="large"/>
            </div>
        );
    }

    if (!canManageLoops) {
        return (
            <Card className="!border-github-border !bg-github-panel">
                <Alert type="warning" showIcon message="暂无权限访问 Loop 页面"/>
            </Card>
        );
    }

    if (!round) {
        return (
            <Card className="!border-github-border !bg-github-panel">
                <Empty description="Round 不存在或无权限访问"/>
            </Card>
        );
    }

    return (
        <div className="flex h-full flex-col gap-4 overflow-auto pr-1">
            <Card className="!border-github-border !bg-github-panel">
                <div className="flex w-full flex-wrap items-start justify-between gap-3">
                    <div className="flex min-w-0 flex-col gap-1">
                        <div className="flex flex-wrap items-center gap-2">
                            <Button onClick={() => navigate(`/projects/${projectId}/loops/${loopId}`)}>返回 Loop 详情</Button>
                            <Title level={4} className="!mb-0">Round #{round.roundIndex} · Attempt {round.attemptIndex || 1}</Title>
                            <Tag color={ROUND_STATE_COLOR[round.state] || 'default'}>{round.state}</Tag>
                            {round.awaitingConfirm ? <Tag color="gold">awaiting_confirm</Tag> : null}
                        </div>
                        <Text type="secondary">{round.id}</Text>
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                        <Tag color={wsConnected ? 'success' : 'default'}>{wsConnected ? 'WebSocket 已连接' : 'WebSocket 未连接'}</Tag>
                        {round.state === 'failed' ? (
                            <Button type="primary" loading={retrying} onClick={handleRetryRound}>
                                重跑本轮
                            </Button>
                        ) : null}
                        <Button loading={refreshing} onClick={() => loadData(true)}>刷新</Button>
                    </div>
                </div>
            </Card>

            <Card className="!border-github-border !bg-github-panel" title="Round 概览">
                <Descriptions size="small" column={4}>
                    <Descriptions.Item label="插件">{round.pluginId}</Descriptions.Item>
                    <Descriptions.Item label="采样策略">{round.resolvedParams?.sampling?.strategy || '-'}</Descriptions.Item>
                    <Descriptions.Item label="模式">{round.mode}</Descriptions.Item>
                    <Descriptions.Item label="Attempt">{round.attemptIndex || 1}</Descriptions.Item>
                    <Descriptions.Item label="开始时间">{formatDateTime(round.startedAt)}</Descriptions.Item>
                    <Descriptions.Item label="结束时间">{formatDateTime(round.endedAt)}</Descriptions.Item>
                    <Descriptions.Item label="Step 数量">{steps.length}</Descriptions.Item>
                    <Descriptions.Item label="Step 聚合">{JSON.stringify(round.stepCounts || {})}</Descriptions.Item>
                    <Descriptions.Item label="Retry From">{round.retryOfRoundId || '-'}</Descriptions.Item>
                    <Descriptions.Item label="Retry Reason">{round.retryReason || '-'}</Descriptions.Item>
                </Descriptions>
                {round.lastError ? (
                    <Alert className="!mt-3" type="error" showIcon message={round.lastError}/>
                ) : null}
            </Card>

            <Card className="!border-github-border !bg-github-panel" title="Step 时间线">
                <Table
                    size="small"
                    rowKey={(item) => item.id}
                    pagination={false}
                    dataSource={steps}
                    rowClassName={(row) => (row.id === selectedStepId ? 'bg-github-surface' : '')}
                    onRow={(row) => ({
                        onClick: () => {
                            setSelectedStepId(row.id);
                            void loadStepDashboard(row.id);
                        },
                    })}
                    columns={[
                        {title: '#', dataIndex: 'stepIndex', width: 60},
                        {title: 'Type', dataIndex: 'stepType', width: 180},
                        {
                            title: 'Status',
                            dataIndex: 'state',
                            width: 140,
                            render: (value: string) => <Tag color={STEP_STATE_COLOR[value] || 'default'}>{value}</Tag>,
                        },
                        {title: 'Executor', dataIndex: 'assignedExecutorId', render: (v: string | null) => v || '-'},
                        {title: 'Attempt', dataIndex: 'attempt', width: 90},
                        {title: 'Error', dataIndex: 'lastError', render: (v: string | null) => v || '-'},
                    ]}
                />
            </Card>

            {!selectedStep ? (
                <Card className="!border-github-border !bg-github-panel">
                    <Empty description="当前 Round 没有可查看的 Step"/>
                </Card>
            ) : (
                <>
                    <Card className="!border-github-border !bg-github-panel" title={`当前 Step: ${selectedStep.stepType} (#${selectedStep.stepIndex})`}>
                        <Descriptions size="small" column={4}>
                            <Descriptions.Item label="状态">
                                <Tag color={STEP_STATE_COLOR[selectedStep.state] || 'default'}>{selectedStep.state}</Tag>
                            </Descriptions.Item>
                            <Descriptions.Item label="执行器">{selectedStep.assignedExecutorId || '-'}</Descriptions.Item>
                            <Descriptions.Item label="开始时间">{formatDateTime(selectedStep.startedAt)}</Descriptions.Item>
                            <Descriptions.Item label="结束时间">{formatDateTime(selectedStep.endedAt)}</Descriptions.Item>
                        </Descriptions>
                    </Card>

                    <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
                        <div className="min-w-0 lg:col-span-7">
                            <Card className="!border-github-border !bg-github-panel" title="指标曲线">
                                {metricChartData.length === 0 ? (
                                    <Empty description="暂无指标曲线"/>
                                ) : (
                                    <div className="h-[320px]">
                                        <ResponsiveContainer width="100%" height="100%">
                                            <LineChart data={metricChartData}>
                                                <CartesianGrid strokeDasharray="3 3"/>
                                                <XAxis dataKey="step"/>
                                                <YAxis/>
                                                <Tooltip/>
                                                {metricNames.map((name, idx) => (
                                                    <Line
                                                        key={name}
                                                        type="monotone"
                                                        dataKey={name}
                                                        dot={false}
                                                        stroke={['#1677ff', '#52c41a', '#faad14', '#13c2c2', '#eb2f96'][idx % 5]}
                                                        strokeWidth={2}
                                                    />
                                                ))}
                                            </LineChart>
                                        </ResponsiveContainer>
                                    </div>
                                )}
                            </Card>
                        </div>
                        <div className="min-w-0 lg:col-span-5">
                            <Card className="!border-github-border !bg-github-panel" title="实时日志（最新 200 条）">
                                <List
                                    size="small"
                                    dataSource={events.slice(-200)}
                                    locale={{emptyText: '暂无日志'}}
                                    className="max-h-[320px] overflow-auto"
                                    renderItem={(item) => (
                                        <List.Item className="!items-start">
                                            <div className="w-full">
                                                <div className="text-xs text-github-muted">#{item.seq} · {formatDateTime(item.ts)}</div>
                                                <div className="font-mono text-xs whitespace-pre-wrap break-all">{eventToText(item)}</div>
                                            </div>
                                        </List.Item>
                                    )}
                                />
                            </Card>
                        </div>
                    </div>

                    <Card className="!border-github-border !bg-github-panel" title="混淆矩阵/图像制品">
                        {imageArtifacts.length === 0 ? (
                            <Empty description="未检测到图像制品"/>
                        ) : (
                            <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
                                {imageArtifacts.map((artifact) => {
                                    const imageUrl = artifactUrls[artifact.name];
                                    return (
                                        <div key={artifact.name} className="min-w-0">
                                            <Card size="small" className="!border-github-border !bg-github-panel" title={artifact.name} extra={<Tag>{artifact.kind}</Tag>}>
                                                {imageUrl ? (
                                                    <Image src={imageUrl} alt={artifact.name} className="w-full"/>
                                                ) : (
                                                    <Alert
                                                        type="info"
                                                        showIcon
                                                        message="当前环境无法直接预览该图片制品"
                                                        description={artifact.uri}
                                                    />
                                                )}
                                            </Card>
                                        </div>
                                    );
                                })}
                            </div>
                        )}
                    </Card>

                    <Card className="!border-github-border !bg-github-panel" title="候选样本（Step 级）">
                        <Table
                            size="small"
                            pagination={{pageSize: 10, showSizeChanger: false}}
                            dataSource={candidates}
                            rowKey={(item) => `${item.sampleId}-${item.rank}`}
                            columns={[
                                {title: '#', dataIndex: 'rank', width: 60},
                                {
                                    title: 'Sample ID',
                                    dataIndex: 'sampleId',
                                    render: (value: string) => <Text code>{value}</Text>,
                                },
                                {
                                    title: 'Score',
                                    dataIndex: 'score',
                                    width: 220,
                                    render: (value: number) => (
                                        <div className="flex w-full flex-col gap-0.5">
                                            <Progress percent={Math.max(0, Math.min(100, Number((value * 100).toFixed(2))))}/>
                                            <Text type="secondary">{value.toFixed(6)}</Text>
                                        </div>
                                    ),
                                },
                                {
                                    title: 'Reason',
                                    dataIndex: 'reason',
                                    render: (value: Record<string, any>) => <Text type="secondary">{JSON.stringify(value || {})}</Text>,
                                },
                            ]}
                        />
                    </Card>

                    <Card className="!border-github-border !bg-github-panel" title="Step 制品">
                        {artifacts.length === 0 ? (
                            <Empty description="暂无制品"/>
                        ) : (
                            <Table
                                size="small"
                                rowKey={(item) => item.name}
                                dataSource={artifacts}
                                pagination={{pageSize: 8}}
                                columns={[
                                    {title: '名称', dataIndex: 'name'},
                                    {title: '类型', dataIndex: 'kind', width: 180, render: (v: string) => <Tag>{v}</Tag>},
                                    {
                                        title: '大小',
                                        width: 120,
                                        render: (_value: unknown, row: RuntimeStepArtifact) => {
                                            const size = Number(row.meta?.size || 0);
                                            return size > 0 ? `${(size / 1024 / 1024).toFixed(2)} MB` : '-';
                                        },
                                    },
                                    {
                                        title: '操作',
                                        width: 220,
                                        render: (_value: unknown, row: RuntimeStepArtifact) => {
                                            const url = artifactUrls[row.name];
                                            return url ? (
                                                <Button size="small" onClick={() => window.open(url, '_blank', 'noopener,noreferrer')}>
                                                    下载/预览
                                                </Button>
                                            ) : (
                                                <Text type="secondary">暂不可下载</Text>
                                            );
                                        },
                                    },
                                ]}
                            />
                        )}
                    </Card>
                </>
            )}
        </div>
    );
};

export default ProjectLoopRoundDetail;
