import React, {useCallback, useEffect, useMemo, useRef, useState} from 'react';
import {
    Alert,
    Button,
    Card,
    Col,
    Descriptions,
    Empty,
    Image,
    List,
    Progress,
    Row,
    Space,
    Spin,
    Table,
    Tag,
    Typography,
    message,
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

import {api} from '../../../services/api';
import {useAuthStore} from '../../../store/authStore';
import {
    RuntimeArtifact,
    RuntimeJob,
    RuntimeJobEvent,
    RuntimeMetricPoint,
    RuntimeTopKCandidate,
} from '../../../types';

const {Text, Title} = Typography;

const JOB_STATUS_COLOR: Record<string, string> = {
    pending: 'default',
    running: 'processing',
    success: 'success',
    failed: 'error',
    cancelled: 'warning',
};

const TERMINAL_STATUS = new Set(['success', 'failed', 'cancelled']);

const formatDateTime = (value?: string | null) => {
    if (!value) return '-';
    try {
        return new Date(value).toLocaleString();
    } catch {
        return value;
    }
};

const buildWsUrl = (jobId: string, afterSeq: number, token: string): string => {
    const apiBaseUrlRaw = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api/v1';
    const apiBaseUrl = apiBaseUrlRaw.endsWith('/') ? apiBaseUrlRaw.slice(0, -1) : apiBaseUrlRaw;
    const suffix = `/jobs/${jobId}/events/ws?after_seq=${afterSeq}&token=${encodeURIComponent(token)}`;
    if (apiBaseUrl.startsWith('http://') || apiBaseUrl.startsWith('https://')) {
        return `${apiBaseUrl.replace(/^http/, 'ws')}${suffix}`;
    }
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const path = apiBaseUrl.startsWith('/') ? apiBaseUrl : `/${apiBaseUrl}`;
    return `${protocol}//${window.location.host}${path}${suffix}`;
};

const eventToText = (event: RuntimeJobEvent): string => {
    if (event.eventType === 'log') {
        return `[${event.payload.level || 'INFO'}] ${event.payload.message || ''}`;
    }
    if (event.eventType === 'status') {
        return `状态 => ${event.payload.status || ''} ${event.payload.reason || ''}`.trim();
    }
    if (event.eventType === 'progress') {
        return `进度 epoch=${event.payload.epoch ?? '-'} step=${event.payload.step ?? '-'} / ${event.payload.totalSteps ?? '-'}`;
    }
    if (event.eventType === 'metric') {
        return `指标 ${JSON.stringify(event.payload.metrics || {})}`;
    }
    if (event.eventType === 'artifact') {
        return `制品 ${event.payload.name || ''} -> ${event.payload.uri || ''}`;
    }
    return `${event.eventType} ${JSON.stringify(event.payload || {})}`;
};

const isImageArtifact = (artifact: RuntimeArtifact): boolean => {
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

const ProjectLoopJobDetail: React.FC = () => {
    const {projectId, loopId, jobId} = useParams<{ projectId: string; loopId: string; jobId: string }>();
    const navigate = useNavigate();
    const token = useAuthStore((state) => state.token);

    const [loading, setLoading] = useState(true);
    const [refreshing, setRefreshing] = useState(false);
    const [job, setJob] = useState<RuntimeJob | null>(null);
    const [metricPoints, setMetricPoints] = useState<RuntimeMetricPoint[]>([]);
    const [topk, setTopk] = useState<RuntimeTopKCandidate[]>([]);
    const [events, setEvents] = useState<RuntimeJobEvent[]>([]);
    const [artifacts, setArtifacts] = useState<RuntimeArtifact[]>([]);
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

    const topkDataSource = useMemo(() => {
        return topk.map((item, idx) => ({
            rank: idx + 1,
            sampleId: item.sampleId,
            score: item.score,
            extra: item.extra || {},
        }));
    }, [topk]);

    const imageArtifacts = useMemo(() => {
        return artifacts.filter((item) => isImageArtifact(item));
    }, [artifacts]);

    const ensureArtifactUrls = useCallback(async (items: RuntimeArtifact[]) => {
        if (!jobId || items.length === 0) return;
        const missing = items.filter((item) => !artifactUrls[item.name]);
        if (missing.length === 0) return;

        const updates: Record<string, string> = {};
        for (const artifact of missing) {
            const uri = String(artifact.uri || '');
            if (uri.startsWith('http://') || uri.startsWith('https://')) {
                updates[artifact.name] = uri;
                continue;
            }
            try {
                const row = await api.getJobArtifactDownloadUrl(jobId, artifact.name, 2);
                updates[artifact.name] = row.downloadUrl;
            } catch {
                // Keep silent for unsupported artifact URI.
            }
        }

        if (Object.keys(updates).length > 0) {
            setArtifactUrls((prev) => ({...prev, ...updates}));
        }
    }, [jobId, artifactUrls]);

    const loadJobDashboard = useCallback(async () => {
        if (!jobId) return;
        const [jobRow, points, candidates, artifactsResp, initialEvents] = await Promise.all([
            api.getJob(jobId),
            api.getJobMetricSeries(jobId, 5000),
            api.getJobSamplingTopK(jobId, 200),
            api.getJobArtifacts(jobId),
            api.getJobEvents(jobId, 0),
        ]);
        setJob(jobRow);
        setMetricPoints(points);
        setTopk(candidates);
        setArtifacts(artifactsResp.artifacts || []);
        setEvents(initialEvents);
        eventCursorRef.current = initialEvents.reduce((max, item) => Math.max(max, item.seq), 0);
        await ensureArtifactUrls(artifactsResp.artifacts || []);
    }, [jobId, ensureArtifactUrls]);

    const loadData = useCallback(async (silent: boolean = false) => {
        if (!jobId) return;
        if (!silent) setLoading(true);
        if (silent) setRefreshing(true);
        try {
            await loadJobDashboard();
        } catch (error: any) {
            message.error(error?.message || '加载 Job 详情失败');
        } finally {
            setLoading(false);
            setRefreshing(false);
        }
    }, [jobId, loadJobDashboard]);

    useEffect(() => {
        void loadData(false);
    }, [loadData]);

    useEffect(() => {
        if (!jobId) return;
        const timer = window.setInterval(async () => {
            try {
                const [newEvents, latestJob] = await Promise.all([
                    api.getJobEvents(jobId, eventCursorRef.current),
                    api.getJob(jobId),
                ]);

                if (newEvents.length > 0) {
                    setEvents((prev) => {
                        const merged = [...prev, ...newEvents];
                        const dedup = new Map<number, RuntimeJobEvent>();
                        merged.forEach((item) => dedup.set(item.seq, item));
                        return Array.from(dedup.values()).sort((a, b) => a.seq - b.seq);
                    });
                    eventCursorRef.current = Math.max(
                        eventCursorRef.current,
                        ...newEvents.map((item) => item.seq),
                    );
                }

                setJob(latestJob);

                const shouldRefreshMetrics =
                    latestJob.status === 'running' ||
                    newEvents.some((item) => item.eventType === 'metric');
                const shouldRefreshArtifacts =
                    newEvents.some((item) => item.eventType === 'artifact') || TERMINAL_STATUS.has(latestJob.status);

                if (shouldRefreshMetrics) {
                    const points = await api.getJobMetricSeries(jobId, 5000);
                    setMetricPoints(points);
                }
                if (shouldRefreshArtifacts) {
                    const artifactsResp = await api.getJobArtifacts(jobId);
                    setArtifacts(artifactsResp.artifacts || []);
                    await ensureArtifactUrls(artifactsResp.artifacts || []);
                }
                if (TERMINAL_STATUS.has(latestJob.status)) {
                    const candidates = await api.getJobSamplingTopK(jobId, 200);
                    setTopk(candidates);
                }
            } catch {
                // ignore polling errors
            }
        }, 3000);
        return () => window.clearInterval(timer);
    }, [jobId, ensureArtifactUrls]);

    useEffect(() => {
        if (!jobId || !token) return;
        const ws = new WebSocket(buildWsUrl(jobId, eventCursorRef.current, token));
        ws.onopen = () => setWsConnected(true);
        ws.onclose = () => setWsConnected(false);
        ws.onerror = () => setWsConnected(false);
        ws.onmessage = (event: MessageEvent<string>) => {
            try {
                const payload = JSON.parse(event.data || '{}') as RuntimeJobEvent;
                if (!payload || typeof payload.seq !== 'number') return;
                setEvents((prev) => {
                    const merged = [...prev, payload];
                    const dedup = new Map<number, RuntimeJobEvent>();
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
    }, [jobId, token]);

    if (loading) {
        return (
            <div className="flex h-full items-center justify-center">
                <Spin size="large"/>
            </div>
        );
    }

    if (!job) {
        return (
            <Card className="!border-github-border !bg-github-panel">
                <Empty description="Job 不存在或无权限访问"/>
            </Card>
        );
    }

    return (
        <div className="flex h-full flex-col gap-4 overflow-auto pr-1">
            <Card className="!border-github-border !bg-github-panel">
                <Space className="w-full !justify-between" wrap>
                    <Space direction="vertical" size={2}>
                        <Space>
                            <Button onClick={() => navigate(`/projects/${projectId}/loops/${loopId}`)}>返回 Loop 详情</Button>
                            <Title level={4} className="!mb-0">Job #{job.roundIndex || job.iteration}</Title>
                            <Tag color={JOB_STATUS_COLOR[job.status] || 'default'}>{job.status}</Tag>
                        </Space>
                        <Text type="secondary">{job.id}</Text>
                    </Space>
                    <Space>
                        <Tag color={wsConnected ? 'success' : 'default'}>{wsConnected ? 'WebSocket 已连接' : 'WebSocket 未连接'}</Tag>
                        <Button loading={refreshing} onClick={() => loadData(true)}>刷新</Button>
                    </Space>
                </Space>
            </Card>

            <Card className="!border-github-border !bg-github-panel" title="任务概览">
                <Descriptions size="small" column={4}>
                    <Descriptions.Item label="插件">{job.pluginId}</Descriptions.Item>
                    <Descriptions.Item label="采样策略">{job.queryStrategy}</Descriptions.Item>
                    <Descriptions.Item label="执行器">{job.assignedExecutorId || '-'}</Descriptions.Item>
                    <Descriptions.Item label="模式">{job.mode}</Descriptions.Item>
                    <Descriptions.Item label="开始时间">{formatDateTime(job.startedAt)}</Descriptions.Item>
                    <Descriptions.Item label="结束时间">{formatDateTime(job.endedAt)}</Descriptions.Item>
                    <Descriptions.Item label="制品数量">{artifacts.length}</Descriptions.Item>
                    <Descriptions.Item label="TopK 数量">{topk.length}</Descriptions.Item>
                </Descriptions>
                {job.lastError ? (
                    <Alert className="!mt-3" type="error" showIcon message={job.lastError}/>
                ) : null}
            </Card>

            <Row gutter={[16, 16]}>
                <Col xs={24} lg={14}>
                    <Card className="!border-github-border !bg-github-panel" title="训练曲线">
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
                </Col>
                <Col xs={24} lg={10}>
                    <Card className="!border-github-border !bg-github-panel" title="实时日志（最新 200 条）">
                        <List
                            size="small"
                            dataSource={events.slice(-200)}
                            locale={{emptyText: '暂无日志'}}
                            className="max-h-[320px] overflow-auto"
                            renderItem={(item) => (
                                <List.Item className="!items-start">
                                    <div className="w-full">
                                        <div className="text-xs text-github-muted">
                                            #{item.seq} · {formatDateTime(item.ts)}
                                        </div>
                                        <div className="font-mono text-xs whitespace-pre-wrap break-all">
                                            {eventToText(item)}
                                        </div>
                                    </div>
                                </List.Item>
                            )}
                        />
                    </Card>
                </Col>
            </Row>

            <Card className="!border-github-border !bg-github-panel" title="混淆矩阵">
                {imageArtifacts.length === 0 ? (
                    <Empty description="未检测到混淆矩阵制品"/>
                ) : (
                    <Row gutter={[16, 16]}>
                        {imageArtifacts.map((artifact) => {
                            const imageUrl = artifactUrls[artifact.name];
                            return (
                                <Col key={artifact.name} xs={24} xl={12}>
                                    <Card
                                        size="small"
                                        className="!border-github-border !bg-github-panel"
                                        title={artifact.name}
                                        extra={<Tag>{artifact.kind}</Tag>}
                                    >
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
                                </Col>
                            );
                        })}
                    </Row>
                )}
            </Card>

            <Card className="!border-github-border !bg-github-panel" title="TopK 候选样本">
                <Table
                    size="small"
                    pagination={{pageSize: 10, showSizeChanger: false}}
                    dataSource={topkDataSource}
                    rowKey={(item) => item.sampleId}
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
                                <Space direction="vertical" size={2} className="w-full">
                                    <Progress percent={Math.max(0, Math.min(100, Number((value * 100).toFixed(2))))}/>
                                    <Text type="secondary">{value.toFixed(6)}</Text>
                                </Space>
                            ),
                        },
                        {
                            title: 'Detail',
                            dataIndex: 'extra',
                            render: (value: Record<string, any>) => (
                                <Text type="secondary">{JSON.stringify(value || {})}</Text>
                            ),
                        },
                    ]}
                />
            </Card>

            <Card className="!border-github-border !bg-github-panel" title="模型制品">
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
                                render: (_value: unknown, row: RuntimeArtifact) => {
                                    const size = Number(row.meta?.size || 0);
                                    return size > 0 ? `${(size / 1024 / 1024).toFixed(2)} MB` : '-';
                                },
                            },
                            {
                                title: '操作',
                                width: 220,
                                render: (_value: unknown, row: RuntimeArtifact) => {
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
        </div>
    );
};

export default ProjectLoopJobDetail;
