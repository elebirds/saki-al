import React, {useCallback, useEffect, useMemo, useRef, useState} from 'react';
import {
    App,
    Alert,
    Button,
    Card,
    Descriptions,
    Drawer,
    Empty,
    Image,
    Input,
    Progress,
    Select,
    Space,
    Spin,
    Steps,
    Switch,
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
    StepEventFacets,
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
const ERROR_LEVELS = new Set(['ERROR', 'CRITICAL', 'FATAL']);
const MAX_EVENT_BUFFER = 20000;
const DEFAULT_LOG_TAIL = 500;

const EVENT_TYPE_COLOR: Record<string, string> = {
    log: 'default',
    status: 'blue',
    progress: 'cyan',
    metric: 'green',
    artifact: 'purple',
    worker: 'gold',
};

const LEVEL_COLOR_CLASS: Record<string, string> = {
    TRACE: 'text-slate-400',
    DEBUG: 'text-slate-300',
    INFO: 'text-blue-300',
    WARNING: 'text-amber-300',
    WARN: 'text-amber-300',
    ERROR: 'text-red-300',
    CRITICAL: 'text-fuchsia-300',
    FATAL: 'text-fuchsia-300',
};

const formatDateTime = (value?: string | null) => {
    if (!value) return '-';
    try {
        return new Date(value).toLocaleString();
    } catch {
        return value;
    }
};

const computeDurationMs = (startedAt?: string | null, endedAt?: string | null): number => {
    if (!startedAt) return 0;
    const start = new Date(startedAt).getTime();
    if (!Number.isFinite(start) || start <= 0) return 0;
    const end = endedAt ? new Date(endedAt).getTime() : Date.now();
    if (!Number.isFinite(end) || end <= 0) return 0;
    return Math.max(0, end - start);
};

const formatDuration = (durationMs: number): string => {
    if (!Number.isFinite(durationMs) || durationMs <= 0) return '-';
    const totalSec = Math.floor(durationMs / 1000);
    const hours = Math.floor(totalSec / 3600);
    const mins = Math.floor((totalSec % 3600) / 60);
    const secs = totalSec % 60;
    if (hours > 0) return `${hours}h ${mins}m ${secs}s`;
    if (mins > 0) return `${mins}m ${secs}s`;
    return `${secs}s`;
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
    level?: unknown;
    status?: unknown;
    kind?: unknown;
    tags?: unknown;
    messageText?: unknown;
    message_text?: unknown;
    payload?: unknown;
};

const deriveEventMessage = (eventType: string, payload: Record<string, any>): string => {
    if (eventType === 'log') return String(payload.message || '');
    if (eventType === 'status') {
        return `${String(payload.status || '').trim()} ${String(payload.reason || '').trim()}`.trim();
    }
    if (eventType === 'progress') {
        return `progress epoch=${payload.epoch ?? '-'} step=${payload.step ?? '-'} total=${payload.total_steps ?? payload.totalSteps ?? '-'}`;
    }
    if (eventType === 'metric') {
        const metrics = payload.metrics && typeof payload.metrics === 'object' ? payload.metrics : {};
        return `metric keys=${Object.keys(metrics).join(',')}`;
    }
    if (eventType === 'artifact') {
        return `${String(payload.name || '').trim()} ${String(payload.uri || '').trim()}`.trim();
    }
    try {
        return JSON.stringify(payload || {});
    } catch {
        return String(payload || '');
    }
};

const deriveEventTags = (
    eventType: string,
    payload: Record<string, any>,
    level?: string | null,
    status?: string | null,
    kind?: string | null,
    rawTags?: unknown,
): string[] => {
    const tags: string[] = [];
    const pushTag = (value: unknown) => {
        const text = String(value || '').trim();
        if (!text || tags.includes(text)) return;
        tags.push(text);
    };
    pushTag(`event:${eventType}`);
    if (level) pushTag(`level:${level.toUpperCase()}`);
    if (status) pushTag(`status:${status.toLowerCase()}`);
    if (kind) pushTag(`kind:${kind.toLowerCase()}`);
    if (payload.tag != null) pushTag(payload.tag);
    if (Array.isArray(payload.tags)) {
        payload.tags.forEach((item) => pushTag(item));
    }
    if (Array.isArray(rawTags)) {
        rawTags.forEach((item) => pushTag(item));
    }
    return tags;
};

const normalizeRuntimeEvent = (raw: RawRuntimeStepEvent): RuntimeStepEvent | null => {
    const seq = Number(raw.seq);
    if (!Number.isFinite(seq)) return null;
    const eventTypeRaw = raw.eventType ?? raw.event_type;
    const eventType = String(eventTypeRaw || 'unknown_event').trim().toLowerCase();
    const ts = typeof raw.ts === 'string' ? raw.ts : new Date().toISOString();
    const payload = raw.payload && typeof raw.payload === 'object' ? (raw.payload as Record<string, any>) : {};
    const levelRaw = raw.level ?? payload.level;
    const statusRaw = raw.status ?? payload.status;
    const kindRaw = raw.kind ?? payload.kind;
    const level = levelRaw ? String(levelRaw).trim().toUpperCase() : null;
    const status = statusRaw ? String(statusRaw).trim() : null;
    const kind = kindRaw ? String(kindRaw).trim() : null;
    const messageTextRaw = raw.messageText ?? raw.message_text;
    const messageText = String(messageTextRaw || deriveEventMessage(eventType, payload)).trim();
    const tags = deriveEventTags(eventType, payload, level, status, kind, raw.tags);
    return {
        seq,
        ts,
        eventType,
        payload,
        level,
        status,
        kind,
        tags,
        messageText,
    };
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

const mergeEventBuffer = (previous: RuntimeStepEvent[], incoming: RuntimeStepEvent[]): RuntimeStepEvent[] => {
    const merged = [...previous, ...incoming];
    const dedup = new Map<number, RuntimeStepEvent>();
    merged.forEach((item) => {
        dedup.set(Number(item.seq || 0), item);
    });
    const rows = Array.from(dedup.values()).sort((a, b) => a.seq - b.seq);
    if (rows.length <= MAX_EVENT_BUFFER) return rows;
    return rows.slice(rows.length - MAX_EVENT_BUFFER);
};

const getStepFlowStatus = (state: string): 'wait' | 'process' | 'finish' | 'error' => {
    if (state === 'succeeded' || state === 'skipped') return 'finish';
    if (state === 'failed' || state === 'cancelled') return 'error';
    if (state === 'running' || state === 'dispatching' || state === 'retrying' || state === 'ready') return 'process';
    return 'wait';
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
    const [eventFacets, setEventFacets] = useState<StepEventFacets>({eventTypes: {}, levels: {}, tags: {}});
    const [eventTypeFilter, setEventTypeFilter] = useState<string[]>([]);
    const [eventLevelFilter, setEventLevelFilter] = useState<string[]>([]);
    const [eventTagFilter, setEventTagFilter] = useState<string[]>([]);
    const [eventQueryText, setEventQueryText] = useState<string>('');
    const [onlyErrors, setOnlyErrors] = useState<boolean>(false);
    const [autoScrollLogs, setAutoScrollLogs] = useState<boolean>(true);
    const [logTailLimit, setLogTailLimit] = useState<number>(DEFAULT_LOG_TAIL);
    const [stepDrawerOpen, setStepDrawerOpen] = useState<boolean>(false);
    const [roundOverviewOpen, setRoundOverviewOpen] = useState<boolean>(false);
    const [artifacts, setArtifacts] = useState<RuntimeStepArtifact[]>([]);
    const [wsConnected, setWsConnected] = useState(false);
    const [artifactUrls, setArtifactUrls] = useState<Record<string, string>>({});

    const eventCursorRef = useRef<number>(0);
    const logScrollRef = useRef<HTMLDivElement | null>(null);

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
    const roundDurationText = useMemo(
        () => formatDuration(computeDurationMs(round?.startedAt, round?.endedAt)),
        [round?.startedAt, round?.endedAt],
    );
    const roundProgressPercent = useMemo(() => {
        const stepCounts = round?.stepCounts || {};
        const total = steps.length || Object.values(stepCounts).reduce((sum, item) => sum + Number(item || 0), 0);
        if (!total) return 0;
        const done = ['succeeded', 'failed', 'cancelled', 'skipped']
            .reduce((sum, key) => sum + Number((stepCounts as Record<string, number>)[key] || 0), 0);
        return Math.max(0, Math.min(100, Number(((done / total) * 100).toFixed(2))));
    }, [round?.stepCounts, steps]);
    const finalMetricPairs = useMemo(
        () => Object.entries(round?.finalMetrics || {}).slice(0, 8),
        [round?.finalMetrics],
    );
    const finalArtifactNames = useMemo(
        () => Object.keys(round?.finalArtifacts || {}).slice(0, 8),
        [round?.finalArtifacts],
    );
    const sortedSteps = useMemo(
        () => [...steps].sort((left, right) => Number(left.stepIndex || 0) - Number(right.stepIndex || 0)),
        [steps],
    );
    const selectedStepOrderIndex = useMemo(
        () => sortedSteps.findIndex((item) => item.id === selectedStepId),
        [sortedSteps, selectedStepId],
    );
    const visibleEvents = useMemo(() => {
        const eventTypeSet = new Set((eventTypeFilter || []).map((item) => String(item).toLowerCase()));
        const levelSet = new Set((eventLevelFilter || []).map((item) => String(item).toUpperCase()));
        const tagSet = new Set((eventTagFilter || []).map((item) => String(item).toLowerCase()));
        const query = eventQueryText.trim().toLowerCase();
        let rows = events.filter((item) => {
            if (eventTypeSet.size > 0 && !eventTypeSet.has(String(item.eventType || '').toLowerCase())) {
                return false;
            }
            if (levelSet.size > 0 && !levelSet.has(String(item.level || '').toUpperCase())) {
                return false;
            }
            if (tagSet.size > 0) {
                const rowTags = (item.tags || []).map((tag) => String(tag).toLowerCase());
                if (!rowTags.some((tag) => tagSet.has(tag))) return false;
            }
            if (query) {
                const haystack = `${item.messageText || ''} ${JSON.stringify(item.payload || {})}`.toLowerCase();
                if (!haystack.includes(query)) return false;
            }
            if (onlyErrors) {
                const level = String(item.level || '').toUpperCase();
                const status = String(item.status || '').toLowerCase();
                if (!ERROR_LEVELS.has(level) && !['failed', 'error', 'cancelled'].includes(status)) {
                    return false;
                }
            }
            return true;
        });
        if (logTailLimit > 0 && rows.length > logTailLimit) {
            rows = rows.slice(rows.length - logTailLimit);
        }
        return rows;
    }, [events, eventTypeFilter, eventLevelFilter, eventTagFilter, eventQueryText, onlyErrors, logTailLimit]);

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
        const [stepRow, points, topk, artifactsResp, initialEventsResp] = await Promise.all([
            api.getStep(stepId),
            api.getStepMetricSeries(stepId, 5000),
            api.getStepCandidates(stepId, 200),
            api.getStepArtifacts(stepId),
            api.getStepEvents(stepId, {
                afterSeq: 0,
                limit: 5000,
                includeFacets: true,
            }),
        ]);
        setSelectedStep(stepRow);
        setMetricPoints(points);
        setCandidates(topk);
        setArtifacts(artifactsResp.artifacts || []);
        setEvents(initialEventsResp.items || []);
        setEventFacets(initialEventsResp.facets || {eventTypes: {}, levels: {}, tags: {}});
        eventCursorRef.current = Number(
            initialEventsResp.nextAfterSeq
            ?? (initialEventsResp.items || []).reduce((max, item) => Math.max(max, Number(item.seq || 0)), 0),
        );
        await ensureArtifactUrls(stepId, artifactsResp.artifacts || []);
    }, [ensureArtifactUrls]);

    const reloadFilteredEvents = useCallback(async (stepId: string) => {
        const response = await api.getStepEvents(stepId, {
            afterSeq: 0,
            limit: 5000,
            eventTypes: eventTypeFilter,
            levels: eventLevelFilter,
            tags: eventTagFilter,
            q: eventQueryText.trim() || undefined,
            includeFacets: true,
        });
        setEvents(response.items || []);
        setEventFacets(response.facets || {eventTypes: {}, levels: {}, tags: {}});
        eventCursorRef.current = Number(
            response.nextAfterSeq
            ?? (response.items || []).reduce((max, item) => Math.max(max, Number(item.seq || 0)), 0),
        );
    }, [eventTypeFilter, eventLevelFilter, eventTagFilter, eventQueryText]);

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

    const handleExportLogs = useCallback(() => {
        if (!selectedStep) return;
        const lines = visibleEvents.map((item) => {
            const level = String(item.level || item.status || item.eventType || '').trim();
            const tagText = (item.tags || []).join(',');
            return `[${item.ts}] #${item.seq} [${level}] [${tagText}] ${item.messageText || ''}`;
        });
        const content = lines.join('\n');
        const blob = new Blob([content], {type: 'text/plain;charset=utf-8'});
        const url = window.URL.createObjectURL(blob);
        const anchor = document.createElement('a');
        anchor.href = url;
        anchor.download = `step-${selectedStep.stepIndex}-logs.txt`;
        anchor.click();
        window.URL.revokeObjectURL(url);
    }, [selectedStep, visibleEvents]);

    const handleClearLogs = useCallback(() => {
        setEvents([]);
    }, []);

    useEffect(() => {
        if (!canManageLoops) return;
        void loadData(false);
    }, [canManageLoops, loadData]);

    useEffect(() => {
        if (!autoScrollLogs) return;
        const container = logScrollRef.current;
        if (!container) return;
        container.scrollTop = container.scrollHeight;
    }, [visibleEvents.length, autoScrollLogs]);

    useEffect(() => {
        if (!canManageLoops || !selectedStepId) return;
        const timer = window.setTimeout(() => {
            void reloadFilteredEvents(selectedStepId).catch(() => undefined);
        }, 250);
        return () => window.clearTimeout(timer);
    }, [canManageLoops, selectedStepId, reloadFilteredEvents]);

    useEffect(() => {
        if (!canManageLoops || !selectedStepId) return;
        const timer = window.setInterval(async () => {
            try {
                const [latestRound, latestSteps, newEvents, latestStep] = await Promise.all([
                    api.getRound(roundId as string),
                    api.getRoundSteps(roundId as string, 2000),
                    api.getStepEvents(selectedStepId, {
                        afterSeq: eventCursorRef.current,
                        limit: 5000,
                        includeFacets: false,
                    }),
                    api.getStep(selectedStepId),
                ]);

                setRound(latestRound);
                setSteps(latestSteps);
                setSelectedStep(latestStep);

                const incoming = newEvents.items || [];
                if (incoming.length > 0) {
                    setEvents((prev) => mergeEventBuffer(prev, incoming));
                    eventCursorRef.current = Math.max(
                        eventCursorRef.current,
                        ...incoming.map((item) => Number(item.seq || 0)),
                    );
                }

                const shouldRefreshMetrics =
                    latestStep.state === 'running' ||
                    latestStep.state === 'dispatching' ||
                    incoming.some((item) => item.eventType === 'metric');
                const shouldRefreshArtifacts =
                    incoming.some((item) => item.eventType === 'artifact') ||
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
                const payload = normalizeRuntimeEvent(raw);
                if (!payload) return;
                setEvents((prev) => mergeEventBuffer(prev, [payload]));
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
                        <Button onClick={() => setRoundOverviewOpen(true)}>Round 概览</Button>
                        <Button loading={refreshing} onClick={() => loadData(true)}>刷新</Button>
                    </div>
                </div>
                <div className="mt-4 border-t border-github-border pt-4">
                    <div className="mb-3 flex items-center justify-end gap-2">
                        {selectedStep ? (
                            <Button size="small" onClick={() => setStepDrawerOpen(true)}>
                                打开 Step 详情
                            </Button>
                        ) : null}
                    </div>
                    {sortedSteps.length === 0 ? (
                        <Empty description="当前 Round 没有 Step"/>
                    ) : (
                        <Steps
                            current={Math.max(0, selectedStepOrderIndex)}
                            onChange={(index) => {
                                const target = sortedSteps[index];
                                if (!target) return;
                                setSelectedStepId(target.id);
                                void loadStepDashboard(target.id);
                            }}
                            items={sortedSteps.map((item) => ({
                                title: `#${item.stepIndex} ${item.stepType}`,
                                description: (
                                    <div className="flex flex-col gap-0.5">
                                        <span className="text-xs text-github-muted">
                                            {`${formatDuration(computeDurationMs(item.startedAt, item.endedAt))} · A${item.attempt || 1}`}
                                        </span>
                                        <span className="text-xs text-github-muted">
                                            {`executor: ${item.assignedExecutorId || '-'}`}
                                        </span>
                                        {(['failed', 'cancelled'].includes(item.state) && item.lastError) ? (
                                            <span className="truncate text-xs text-red-400" title={item.lastError}>
                                                {`error: ${item.lastError}`}
                                            </span>
                                        ) : null}
                                    </div>
                                ),
                                status: getStepFlowStatus(item.state),
                            }))}
                            size="small"
                        />
                    )}
                </div>
            </Card>

            <div className="flex min-w-0 flex-col gap-4">
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
                            {(['train', 'eval', 'custom'].includes(selectedStep.stepType)) ? (
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
                            ) : (
                                <Card className="!border-github-border !bg-github-panel" title="Step 指标摘要">
                                    {Object.keys(selectedStep.metrics || {}).length === 0 ? (
                                        <Empty description="暂无指标"/>
                                    ) : (
                                        <Descriptions size="small" column={2}>
                                            {Object.entries(selectedStep.metrics || {}).map(([key, value]) => (
                                                <Descriptions.Item key={key} label={key}>{String(value)}</Descriptions.Item>
                                            ))}
                                        </Descriptions>
                                    )}
                                </Card>
                            )}

                            {selectedStep.stepType === 'eval' ? (
                                <Card className="!border-github-border !bg-github-panel" title="评估图像制品（混淆矩阵等）">
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
                            ) : null}

                            {(['score', 'custom'].includes(selectedStep.stepType)) ? (
                                <Card className="!border-github-border !bg-github-panel" title="候选样本/TopK（Step 级）">
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
                            ) : null}

                            <Card
                                className="!border-github-border !bg-github-panel"
                                title={['export', 'upload_artifact'].includes(selectedStep.stepType) ? '导出/上传制品' : 'Step 制品'}
                            >
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

            <Card
                className="!border-github-border !bg-github-panel"
                title={selectedStep ? `Step 控制台日志 · #${selectedStep.stepIndex} ${selectedStep.stepType}` : 'Step 控制台日志'}
                extra={(
                    <Space size={8}>
                        <Tag color={wsConnected ? 'success' : 'default'}>{wsConnected ? 'WS 实时' : 'WS 断开'}</Tag>
                        <Button size="small" onClick={handleClearLogs}>清屏</Button>
                        <Button size="small" onClick={handleExportLogs} disabled={!selectedStep || visibleEvents.length === 0}>
                            导出
                        </Button>
                    </Space>
                )}
            >
                {!selectedStep ? (
                    <Empty description="请先选择 Step"/>
                ) : (
                    <div className="flex flex-col gap-3">
                        <div className="flex flex-wrap items-center gap-2">
                            <Select
                                mode="multiple"
                                allowClear
                                className="min-w-[180px]"
                                placeholder="事件类型"
                                value={eventTypeFilter}
                                options={Object.entries(eventFacets.eventTypes || {}).map(([name, count]) => ({
                                    label: `${name} (${count})`,
                                    value: name,
                                }))}
                                onChange={(values) => setEventTypeFilter(values)}
                            />
                            <Select
                                mode="multiple"
                                allowClear
                                className="min-w-[160px]"
                                placeholder="日志级别"
                                value={eventLevelFilter}
                                options={Object.entries(eventFacets.levels || {}).map(([name, count]) => ({
                                    label: `${name} (${count})`,
                                    value: name,
                                }))}
                                onChange={(values) => setEventLevelFilter(values)}
                            />
                            <Select
                                mode="multiple"
                                allowClear
                                className="min-w-[240px]"
                                placeholder="Tag"
                                value={eventTagFilter}
                                options={Object.entries(eventFacets.tags || {})
                                    .sort((left, right) => Number(right[1]) - Number(left[1]))
                                    .slice(0, 200)
                                    .map(([name, count]) => ({
                                        label: `${name} (${count})`,
                                        value: name,
                                    }))}
                                onChange={(values) => setEventTagFilter(values)}
                            />
                            <Input.Search
                                allowClear
                                className="min-w-[280px]"
                                placeholder="搜索 message/payload"
                                value={eventQueryText}
                                onChange={(event) => setEventQueryText(String(event.target.value || ''))}
                            />
                            <Select
                                value={logTailLimit}
                                className="w-[120px]"
                                options={[
                                    {label: '尾部 200', value: 200},
                                    {label: '尾部 500', value: 500},
                                    {label: '尾部 1000', value: 1000},
                                    {label: '全部', value: 0},
                                ]}
                                onChange={(value) => setLogTailLimit(Number(value || 0))}
                            />
                            <span className="inline-flex items-center gap-1 rounded border border-github-border px-2 py-1">
                                <Switch size="small" checked={onlyErrors} onChange={setOnlyErrors}/>
                                <span className="text-xs text-github-muted">仅错误</span>
                            </span>
                            <span className="inline-flex items-center gap-1 rounded border border-github-border px-2 py-1">
                                <Switch size="small" checked={autoScrollLogs} onChange={setAutoScrollLogs}/>
                                <span className="text-xs text-github-muted">自动滚动</span>
                            </span>
                            <Tag>{`显示 ${visibleEvents.length} / 缓冲 ${events.length}`}</Tag>
                        </div>
                        <div
                            ref={logScrollRef}
                            className="max-h-[560px] overflow-auto rounded border border-github-border bg-slate-950 p-2"
                        >
                            {visibleEvents.length === 0 ? (
                                <div className="py-8 text-center text-xs text-slate-400">暂无命中日志</div>
                            ) : (
                                <div className="space-y-1 font-mono text-xs">
                                    {visibleEvents.map((item) => {
                                        const levelKey = String(item.level || '').toUpperCase();
                                        const lineClass = LEVEL_COLOR_CLASS[levelKey] || 'text-slate-200';
                                        return (
                                            <div key={`${item.seq}-${item.eventType}`} className={`rounded px-2 py-1 ${lineClass} hover:bg-slate-900`}>
                                                <div className="flex flex-wrap items-center gap-2">
                                                    <span className="text-slate-400">{formatDateTime(item.ts)}</span>
                                                    <span className="text-slate-500">#{item.seq}</span>
                                                    <Tag color={EVENT_TYPE_COLOR[item.eventType] || 'default'} className="!m-0">{item.eventType}</Tag>
                                                    {item.level ? <Tag color={ERROR_LEVELS.has(String(item.level).toUpperCase()) ? 'error' : 'blue'} className="!m-0">{item.level}</Tag> : null}
                                                    {(item.tags || []).slice(0, 4).map((tag) => (
                                                        <Tag key={`${item.seq}-${tag}`} className="!m-0">{tag}</Tag>
                                                    ))}
                                                </div>
                                                <div className="mt-1 whitespace-pre-wrap break-all">{item.messageText || '-'}</div>
                                            </div>
                                        );
                                    })}
                                </div>
                            )}
                        </div>
                    </div>
                )}
            </Card>

            <Drawer
                open={roundOverviewOpen}
                onClose={() => setRoundOverviewOpen(false)}
                width={560}
                title={`Round 概览 · #${round.roundIndex} / Attempt ${round.attemptIndex || 1}`}
            >
                <Descriptions size="small" column={1}>
                    <Descriptions.Item label="插件">{round.pluginId}</Descriptions.Item>
                    <Descriptions.Item label="采样策略">{round.resolvedParams?.sampling?.strategy || '-'}</Descriptions.Item>
                    <Descriptions.Item label="模式">{round.mode}</Descriptions.Item>
                    <Descriptions.Item label="Attempt">{round.attemptIndex || 1}</Descriptions.Item>
                    <Descriptions.Item label="开始时间">{formatDateTime(round.startedAt)}</Descriptions.Item>
                    <Descriptions.Item label="结束时间">{formatDateTime(round.endedAt)}</Descriptions.Item>
                    <Descriptions.Item label="耗时">{roundDurationText}</Descriptions.Item>
                    <Descriptions.Item label="Step 数量">{steps.length}</Descriptions.Item>
                    <Descriptions.Item label="Retry From">{round.retryOfRoundId || '-'}</Descriptions.Item>
                    <Descriptions.Item label="Retry Reason">{round.retryReason || '-'}</Descriptions.Item>
                    <Descriptions.Item label="Final Metrics">
                        {finalMetricPairs.length === 0
                            ? '-'
                            : finalMetricPairs.map(([key, value]) => (
                                <Text key={key} className="mr-2 block">{`${key}: ${String(value)}`}</Text>
                            ))}
                    </Descriptions.Item>
                    <Descriptions.Item label="Final Artifacts">
                        {finalArtifactNames.length === 0
                            ? '-'
                            : finalArtifactNames.map((name) => <Tag key={name}>{name}</Tag>)}
                    </Descriptions.Item>
                </Descriptions>
                <div className="mt-3">
                    <Text type="secondary">Round 进度</Text>
                    <Progress percent={roundProgressPercent}/>
                </div>
                <div className="mt-2">
                    <Text type="secondary">Step 聚合</Text>
                    <div className="mt-1">
                        {(Object.entries(round.stepCounts || {}) as Array<[string, number]>).map(([key, value]) => (
                            <Tag key={key}>{`${key}:${value}`}</Tag>
                        ))}
                    </div>
                </div>
                {round.lastError ? (
                    <Alert className="!mt-3" type="error" showIcon message={round.lastError}/>
                ) : null}
            </Drawer>

            <Drawer
                open={stepDrawerOpen}
                onClose={() => setStepDrawerOpen(false)}
                width={560}
                title={selectedStep ? `Step #${selectedStep.stepIndex} · ${selectedStep.stepType}` : 'Step 详情'}
            >
                {!selectedStep ? (
                    <Empty description="暂无选中 Step"/>
                ) : (
                    <Descriptions size="small" column={1}>
                        <Descriptions.Item label="Step ID">{selectedStep.id}</Descriptions.Item>
                        <Descriptions.Item label="状态">
                            <Tag color={STEP_STATE_COLOR[selectedStep.state] || 'default'}>{selectedStep.state}</Tag>
                        </Descriptions.Item>
                        <Descriptions.Item label="执行器">{selectedStep.assignedExecutorId || '-'}</Descriptions.Item>
                        <Descriptions.Item label="Attempt">{`${selectedStep.attempt || 1}/${selectedStep.maxAttempts || 1}`}</Descriptions.Item>
                        <Descriptions.Item label="开始时间">{formatDateTime(selectedStep.startedAt)}</Descriptions.Item>
                        <Descriptions.Item label="结束时间">{formatDateTime(selectedStep.endedAt)}</Descriptions.Item>
                        <Descriptions.Item label="依赖 Step">
                            {(selectedStep.dependsOnStepIds || []).length > 0
                                ? (selectedStep.dependsOnStepIds || []).map((item) => <Tag key={item}>{item}</Tag>)
                                : '-'}
                        </Descriptions.Item>
                        <Descriptions.Item label="错误信息">{selectedStep.lastError || '-'}</Descriptions.Item>
                    </Descriptions>
                )}
            </Drawer>
        </div>
    );
};

export default ProjectLoopRoundDetail;
