import React, {useCallback, useEffect, useMemo, useRef, useState} from 'react';
import {
    App,
    Alert,
    Button,
    Card,
    Descriptions,
    Drawer,
    Empty,
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
    RuntimeRoundStepArtifacts,
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

type RoundStageKey =
    | 'train'
    | 'score'
    | 'select'
    | 'eval'
    | 'activate_samples'
    | 'advance_branch'
    | 'export'
    | 'custom';

type ConsoleStageFilter = 'all' | RoundStageKey;

interface RoundStageSnapshot {
    key: RoundStageKey;
    label: string;
    steps: RuntimeStep[];
    representativeStep: RuntimeStep | null;
    totalDurationSec: number;
    representativeDurationSec: number;
    stateSummary: string;
    metricSummary: Record<string, any>;
}

interface TrainEvalArtifactRow {
    key: string;
    stage: 'train' | 'eval';
    stageLabel: string;
    stepId: string;
    name: string;
    kind: string;
    meta: Record<string, any>;
}

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

const STAGE_LABEL: Record<RoundStageKey, string> = {
    train: '训练',
    score: '评分',
    select: '选样',
    eval: '评估',
    activate_samples: '激活样本',
    advance_branch: '推进分支',
    export: '导出/上传',
    custom: '自定义',
};

const MODE_STAGE_ORDER: Record<string, RoundStageKey[]> = {
    active_learning: ['train', 'score', 'select', 'eval', 'custom'],
    simulation: ['train', 'score', 'select', 'eval', 'activate_samples', 'advance_branch', 'custom'],
    manual: ['train', 'eval', 'export', 'custom'],
};

const EMPTY_FACETS: StepEventFacets = {eventTypes: {}, levels: {}, tags: {}};

const formatDateTime = (value?: string | null) => {
    if (!value) return '-';
    try {
        return new Date(value).toLocaleString();
    } catch {
        return value;
    }
};

const computeDurationMs = (startedAt?: string | null, endedAt?: string | null, nowMs: number = Date.now()): number => {
    if (!startedAt) return 0;
    const start = new Date(startedAt).getTime();
    if (!Number.isFinite(start) || start <= 0) return 0;
    const end = endedAt ? new Date(endedAt).getTime() : nowMs;
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

const formatArtifactSize = (sizeRaw: unknown): string => {
    const size = Number(sizeRaw || 0);
    if (!Number.isFinite(size) || size <= 0) return '-';
    if (size >= 1024 * 1024) return `${(size / 1024 / 1024).toFixed(2)} MB`;
    return `${(size / 1024).toFixed(1)} KB`;
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

const resolveModeStageOrder = (mode?: string | null): RoundStageKey[] => {
    const key = String(mode || '');
    if (MODE_STAGE_ORDER[key]) return MODE_STAGE_ORDER[key];
    return ['train', 'score', 'select', 'eval', 'activate_samples', 'advance_branch', 'export', 'custom'];
};

const normalizeStepTypeText = (stepType: string): string => String(stepType || '').trim().toLowerCase();

const mapStepTypeToStage = (stepType: string): RoundStageKey => {
    switch (normalizeStepTypeText(stepType)) {
        case 'train':
            return 'train';
        case 'score':
            return 'score';
        case 'select':
            return 'select';
        case 'eval':
        case 'evaluate':
        case 'evaluation':
            return 'eval';
        case 'activate_samples':
            return 'activate_samples';
        case 'advance_branch':
            return 'advance_branch';
        case 'export':
        case 'upload_artifact':
            return 'export';
        default:
            return 'custom';
    }
};

const buildArtifactKey = (stepId: string, artifactName: string): string => `${stepId}:${artifactName}`;

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
    if (Array.isArray(payload.tags)) payload.tags.forEach((item) => pushTag(item));
    if (Array.isArray(rawTags)) rawTags.forEach((item) => pushTag(item));
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

const buildEventFacetsFromItems = (items: RuntimeStepEvent[]): StepEventFacets => {
    const eventTypes: Record<string, number> = {};
    const levels: Record<string, number> = {};
    const tags: Record<string, number> = {};
    items.forEach((item) => {
        const eventType = String(item.eventType || '').trim();
        if (eventType) eventTypes[eventType] = Number(eventTypes[eventType] || 0) + 1;
        const level = String(item.level || '').trim();
        if (level) levels[level] = Number(levels[level] || 0) + 1;
        (item.tags || []).forEach((tag) => {
            const text = String(tag || '').trim();
            if (!text) return;
            tags[text] = Number(tags[text] || 0) + 1;
        });
    });
    return {eventTypes, levels, tags};
};

const getStepFlowStatus = (state: string): 'wait' | 'process' | 'finish' | 'error' => {
    if (state === 'succeeded' || state === 'skipped') return 'finish';
    if (state === 'failed' || state === 'cancelled') return 'error';
    if (state === 'running' || state === 'dispatching' || state === 'retrying' || state === 'ready') return 'process';
    return 'wait';
};

const summarizeStageState = (steps: RuntimeStep[]): string => {
    if (steps.length === 0) return '-';
    const counter: Record<string, number> = {};
    steps.forEach((item) => {
        const key = String(item.state || 'unknown');
        counter[key] = Number(counter[key] || 0) + 1;
    });
    return Object.entries(counter)
        .map(([key, value]) => `${key}:${value}`)
        .join(' · ');
};

const createInitialStageSnapshots = (): Record<RoundStageKey, RoundStageSnapshot> => ({
    train: {
        key: 'train',
        label: STAGE_LABEL.train,
        steps: [],
        representativeStep: null,
        totalDurationSec: 0,
        representativeDurationSec: 0,
        stateSummary: '-',
        metricSummary: {},
    },
    score: {
        key: 'score',
        label: STAGE_LABEL.score,
        steps: [],
        representativeStep: null,
        totalDurationSec: 0,
        representativeDurationSec: 0,
        stateSummary: '-',
        metricSummary: {},
    },
    select: {
        key: 'select',
        label: STAGE_LABEL.select,
        steps: [],
        representativeStep: null,
        totalDurationSec: 0,
        representativeDurationSec: 0,
        stateSummary: '-',
        metricSummary: {},
    },
    eval: {
        key: 'eval',
        label: STAGE_LABEL.eval,
        steps: [],
        representativeStep: null,
        totalDurationSec: 0,
        representativeDurationSec: 0,
        stateSummary: '-',
        metricSummary: {},
    },
    activate_samples: {
        key: 'activate_samples',
        label: STAGE_LABEL.activate_samples,
        steps: [],
        representativeStep: null,
        totalDurationSec: 0,
        representativeDurationSec: 0,
        stateSummary: '-',
        metricSummary: {},
    },
    advance_branch: {
        key: 'advance_branch',
        label: STAGE_LABEL.advance_branch,
        steps: [],
        representativeStep: null,
        totalDurationSec: 0,
        representativeDurationSec: 0,
        stateSummary: '-',
        metricSummary: {},
    },
    export: {
        key: 'export',
        label: STAGE_LABEL.export,
        steps: [],
        representativeStep: null,
        totalDurationSec: 0,
        representativeDurationSec: 0,
        stateSummary: '-',
        metricSummary: {},
    },
    custom: {
        key: 'custom',
        label: STAGE_LABEL.custom,
        steps: [],
        representativeStep: null,
        totalDurationSec: 0,
        representativeDurationSec: 0,
        stateSummary: '-',
        metricSummary: {},
    },
});

const buildStageSnapshots = (steps: RuntimeStep[], nowMs: number): Record<RoundStageKey, RoundStageSnapshot> => {
    const snapshots = createInitialStageSnapshots();
    const sorted = [...steps].sort((left, right) => Number(left.stepIndex || 0) - Number(right.stepIndex || 0));

    sorted.forEach((step) => {
        const key = mapStepTypeToStage(step.stepType);
        snapshots[key].steps.push(step);
    });

    (Object.keys(snapshots) as RoundStageKey[]).forEach((key) => {
        const stage = snapshots[key];
        const representativeStep = stage.steps.length > 0 ? stage.steps[stage.steps.length - 1] : null;
        const totalDurationSec = Math.floor(
            stage.steps.reduce((sum, item) => sum + computeDurationMs(item.startedAt, item.endedAt, nowMs), 0) / 1000,
        );
        const representativeDurationSec = representativeStep
            ? Math.floor(computeDurationMs(representativeStep.startedAt, representativeStep.endedAt, nowMs) / 1000)
            : 0;
        snapshots[key] = {
            ...stage,
            representativeStep,
            totalDurationSec,
            representativeDurationSec,
            stateSummary: summarizeStageState(stage.steps),
            metricSummary: representativeStep?.metrics || {},
        };
    });

    return snapshots;
};

const pickTimelineCurrentStep = (steps: RuntimeStep[]): RuntimeStep | null => {
    if (steps.length === 0) return null;
    const sortedDesc = [...steps].sort((left, right) => Number(right.stepIndex || 0) - Number(left.stepIndex || 0));
    const running = sortedDesc.find((item) => ['running', 'dispatching', 'retrying'].includes(item.state));
    if (running) return running;
    const failed = sortedDesc.find((item) => item.state === 'failed');
    if (failed) return failed;
    return sortedDesc[0];
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
    const [nowMs, setNowMs] = useState<number>(Date.now());

    const [roundOverviewOpen, setRoundOverviewOpen] = useState<boolean>(false);
    const [stepDrawerOpen, setStepDrawerOpen] = useState<boolean>(false);
    const [stepDrawerStepId, setStepDrawerStepId] = useState<string>('');

    const [trainMetricPoints, setTrainMetricPoints] = useState<RuntimeStepMetricPoint[]>([]);
    const [topkCandidates, setTopkCandidates] = useState<RuntimeStepCandidate[]>([]);
    const [topkSource, setTopkSource] = useState<string>('-');
    const [trainArtifacts, setTrainArtifacts] = useState<RuntimeStepArtifact[]>([]);
    const [trainArtifactSourceStepId, setTrainArtifactSourceStepId] = useState<string>('');
    const [evalArtifacts, setEvalArtifacts] = useState<RuntimeStepArtifact[]>([]);
    const [evalArtifactSourceStepId, setEvalArtifactSourceStepId] = useState<string>('');
    const [exportArtifacts, setExportArtifacts] = useState<RuntimeStepArtifact[]>([]);
    const [exportArtifactSourceStepId, setExportArtifactSourceStepId] = useState<string>('');
    const [artifactUrls, setArtifactUrls] = useState<Record<string, string>>({});

    const [consoleStage, setConsoleStage] = useState<ConsoleStageFilter>('all');
    const [events, setEvents] = useState<RuntimeStepEvent[]>([]);
    const [eventFacets, setEventFacets] = useState<StepEventFacets>(EMPTY_FACETS);
    const [eventTypeFilter, setEventTypeFilter] = useState<string[]>([]);
    const [eventLevelFilter, setEventLevelFilter] = useState<string[]>([]);
    const [eventTagFilter, setEventTagFilter] = useState<string[]>([]);
    const [eventQueryText, setEventQueryText] = useState<string>('');
    const [onlyErrors, setOnlyErrors] = useState<boolean>(false);
    const [autoScrollLogs, setAutoScrollLogs] = useState<boolean>(true);
    const [logTailLimit, setLogTailLimit] = useState<number>(DEFAULT_LOG_TAIL);
    const [wsConnected, setWsConnected] = useState<boolean>(false);

    const eventCursorRef = useRef<number>(0);
    const eventCursorByStepRef = useRef<Record<string, number>>({});
    const eventsRef = useRef<RuntimeStepEvent[]>([]);
    const logScrollRef = useRef<HTMLDivElement | null>(null);
    const artifactUrlsRef = useRef<Record<string, string>>({});

    useEffect(() => {
        artifactUrlsRef.current = artifactUrls;
    }, [artifactUrls]);

    useEffect(() => {
        eventsRef.current = events;
    }, [events]);

    const sortedSteps = useMemo(
        () => [...steps].sort((left, right) => Number(left.stepIndex || 0) - Number(right.stepIndex || 0)),
        [steps],
    );

    const currentTimelineStep = useMemo(() => pickTimelineCurrentStep(sortedSteps), [sortedSteps]);
    const currentTimelineIndex = useMemo(
        () => sortedSteps.findIndex((item) => item.id === currentTimelineStep?.id),
        [sortedSteps, currentTimelineStep?.id],
    );

    const stageSnapshots = useMemo(
        () => buildStageSnapshots(sortedSteps, nowMs),
        [sortedSteps, nowMs],
    );

    const trainStep = stageSnapshots.train.representativeStep;
    const scoreStep = stageSnapshots.score.representativeStep;
    const selectStep = stageSnapshots.select.representativeStep;
    const evalStep = stageSnapshots.eval.representativeStep;
    const exportStep = stageSnapshots.export.representativeStep;
    const evalArtifactStep = useMemo(() => {
        if (evalStep) return evalStep;
        return [...sortedSteps]
            .reverse()
            .find((item) => {
                const stepType = normalizeStepTypeText(item.stepType);
                return stepType === 'eval' || stepType.includes('eval');
            }) || null;
    }, [evalStep, sortedSteps]);

    const consoleStageOptions = useMemo(() => {
        if (!round) return [];
        const ordered = resolveModeStageOrder(round.mode);
        const stageOptions = ordered
            .filter((key) => Boolean(stageSnapshots[key].representativeStep))
            .map((key) => ({
                label: STAGE_LABEL[key],
                value: key,
            }));
        return [{label: '全部阶段', value: 'all' as const}, ...stageOptions];
    }, [round?.mode, stageSnapshots]);

    useEffect(() => {
        const timer = window.setInterval(() => setNowMs(Date.now()), 1000);
        return () => window.clearInterval(timer);
    }, []);

    useEffect(() => {
        if (!round) return;
        setConsoleStage((prev) => {
            if (prev === 'all') return 'all';
            if (prev && stageSnapshots[prev].representativeStep) return prev;
            return 'all';
        });
    }, [round?.id, round?.mode, stageSnapshots, currentTimelineStep]);

    const annotateEventWithStep = useCallback((item: RuntimeStepEvent, step: RuntimeStep): RuntimeStepEvent => {
        const stage = mapStepTypeToStage(step.stepType);
        const tags = Array.from(new Set([
            ...(item.tags || []),
            `step:${step.stepIndex}`,
            `step_type:${step.stepType}`,
            `stage:${stage}`,
        ]));
        const original = String(item.messageText || '').trim();
        const prefixed = `[step#${step.stepIndex} ${step.stepType}] ${original}`.trim();
        return {
            ...item,
            tags,
            messageText: prefixed,
        };
    }, []);

    const consoleStep = useMemo(() => {
        if (consoleStage === 'all') return currentTimelineStep || null;
        const stageStep = stageSnapshots[consoleStage]?.representativeStep;
        return stageStep || currentTimelineStep || null;
    }, [consoleStage, stageSnapshots, currentTimelineStep]);

    const consoleTargetSteps = useMemo(() => {
        if (consoleStage === 'all') return sortedSteps;
        const row = stageSnapshots[consoleStage]?.representativeStep;
        return row ? [row] : [];
    }, [consoleStage, sortedSteps, stageSnapshots]);

    useEffect(() => {
        if (!stepDrawerStepId) return;
        if (sortedSteps.some((item) => item.id === stepDrawerStepId)) return;
        setStepDrawerStepId('');
    }, [stepDrawerStepId, sortedSteps]);

    const stepDrawerStep = useMemo(
        () => sortedSteps.find((item) => item.id === stepDrawerStepId) || null,
        [sortedSteps, stepDrawerStepId],
    );

    const roundDurationText = useMemo(
        () => formatDuration(computeDurationMs(round?.startedAt, round?.endedAt, nowMs)),
        [round?.startedAt, round?.endedAt, nowMs],
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

    const trainMetricNames = useMemo(() => {
        const names = new Set<string>();
        trainMetricPoints.forEach((item) => names.add(item.metricName));
        return Array.from(names);
    }, [trainMetricPoints]);

    const trainMetricChartData = useMemo(() => {
        const rows = new Map<number, Record<string, number>>();
        trainMetricPoints.forEach((point) => {
            const stepKey = Number(point.step || 0);
            const current = rows.get(stepKey) || {step: stepKey};
            current[point.metricName] = Number(point.metricValue);
            rows.set(stepKey, current);
        });
        return Array.from(rows.values()).sort((a, b) => (a.step || 0) - (b.step || 0));
    }, [trainMetricPoints]);

    const trainEvalArtifactRows = useMemo(() => {
        const rows: TrainEvalArtifactRow[] = [];
        const pushRows = (
            stage: 'train' | 'eval',
            stageLabel: string,
            stepId: string,
            artifacts: RuntimeStepArtifact[],
        ) => {
            if (!stepId || artifacts.length === 0) return;
            artifacts.forEach((artifact) => {
                rows.push({
                    key: buildArtifactKey(stepId, artifact.name),
                    stage,
                    stageLabel,
                    stepId,
                    name: artifact.name,
                    kind: artifact.kind,
                    meta: artifact.meta || {},
                });
            });
        };
        const trainStepId = trainArtifactSourceStepId || trainStep?.id || '';
        const evalStepId = evalArtifactSourceStepId || evalArtifactStep?.id || '';
        pushRows('train', STAGE_LABEL.train, trainStepId, trainArtifacts);
        pushRows('eval', STAGE_LABEL.eval, evalStepId, evalArtifacts);
        return rows;
    }, [
        trainArtifacts,
        evalArtifacts,
        trainArtifactSourceStepId,
        evalArtifactSourceStepId,
        trainStep?.id,
        evalArtifactStep?.id,
    ]);

    const evalMetricSummary = useMemo(() => {
        const stageMetrics = stageSnapshots.eval.metricSummary || {};
        if (Object.keys(stageMetrics).length > 0) return stageMetrics;
        return evalArtifactStep?.metrics || {};
    }, [stageSnapshots.eval.metricSummary, evalArtifactStep?.id, evalArtifactStep?.metrics]);

    const visibleEvents = useMemo(() => {
        const eventTypeSet = new Set((eventTypeFilter || []).map((item) => String(item).toLowerCase()));
        const levelSet = new Set((eventLevelFilter || []).map((item) => String(item).toUpperCase()));
        const tagSet = new Set((eventTagFilter || []).map((item) => String(item).toLowerCase()));
        const query = eventQueryText.trim().toLowerCase();
        let rows = events.filter((item) => {
            if (eventTypeSet.size > 0 && !eventTypeSet.has(String(item.eventType || '').toLowerCase())) return false;
            if (levelSet.size > 0 && !levelSet.has(String(item.level || '').toUpperCase())) return false;
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
                if (!ERROR_LEVELS.has(level) && !['failed', 'error', 'cancelled'].includes(status)) return false;
            }
            return true;
        });
        if (logTailLimit > 0 && rows.length > logTailLimit) rows = rows.slice(rows.length - logTailLimit);
        return rows;
    }, [events, eventTypeFilter, eventLevelFilter, eventTagFilter, eventQueryText, onlyErrors, logTailLimit]);

    const ensureArtifactUrls = useCallback(async (stepId: string, items: RuntimeStepArtifact[]) => {
        if (!stepId || items.length === 0) return;
        const currentMap = artifactUrlsRef.current;
        const missing = items.filter((item) => !currentMap[buildArtifactKey(stepId, item.name)]);
        if (missing.length === 0) return;

        const updates: Record<string, string> = {};
        for (const artifact of missing) {
            const key = buildArtifactKey(stepId, artifact.name);
            const uri = String(artifact.uri || '');
            if (uri.startsWith('http://') || uri.startsWith('https://')) {
                updates[key] = uri;
                continue;
            }
            if (!uri.startsWith('s3://')) continue;
            try {
                const row = await api.getStepArtifactDownloadUrl(stepId, artifact.name, 2);
                updates[key] = row.downloadUrl;
            } catch {
                // ignore unavailable artifacts
            }
        }

        if (Object.keys(updates).length > 0) {
            setArtifactUrls((prev) => ({...prev, ...updates}));
        }
    }, []);

    const reloadFilteredEvents = useCallback(async (step: RuntimeStep) => {
        const response = await api.getStepEvents(step.id, {
            afterSeq: 0,
            limit: 5000,
            eventTypes: eventTypeFilter,
            levels: eventLevelFilter,
            tags: eventTagFilter,
            q: eventQueryText.trim() || undefined,
            includeFacets: true,
        });
        const annotated = (response.items || []).map((item) => annotateEventWithStep(item, step));
        setEvents(annotated);
        setEventFacets(buildEventFacetsFromItems(annotated));
        eventCursorRef.current = Number(
            response.nextAfterSeq
            ?? (response.items || []).reduce((max, item) => Math.max(max, Number(item.seq || 0)), 0),
        );
        eventCursorByStepRef.current[step.id] = eventCursorRef.current;
    }, [eventTypeFilter, eventLevelFilter, eventTagFilter, eventQueryText, annotateEventWithStep]);

    const loadRoundData = useCallback(async (silent: boolean = false) => {
        if (!roundId || !canManageLoops) return;
        if (!silent) setLoading(true);
        if (silent) setRefreshing(true);
        try {
            const [roundRow, stepRows] = await Promise.all([
                api.getRound(roundId),
                api.getRoundSteps(roundId, 2000),
            ]);
            setRound(roundRow);
            setSteps(stepRows);
        } catch (error: any) {
            messageApi.error(error?.message || '加载 Round 详情失败');
        } finally {
            setLoading(false);
            setRefreshing(false);
        }
    }, [roundId, canManageLoops, messageApi]);

    const handleRetryRound = useCallback(async () => {
        if (!round || !loopId) return;
        setRetrying(true);
        try {
            await api.actLoop(loopId, {
                action: 'retry_round',
                payload: {roundId: round.id, reason: 'round detail retry'},
            });
            messageApi.success('已触发重跑');
            await loadRoundData(false);
        } catch (error: any) {
            messageApi.error(error?.message || '重跑失败');
        } finally {
            setRetrying(false);
        }
    }, [round, loopId, messageApi, loadRoundData]);

    const handleExportLogs = useCallback(() => {
        if (visibleEvents.length === 0) return;
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
        anchor.download = `round-${round?.roundIndex ?? 'x'}-${consoleStage === 'all' ? 'all-stages' : consoleStage}-logs.txt`;
        anchor.click();
        window.URL.revokeObjectURL(url);
    }, [visibleEvents, round?.roundIndex, consoleStage]);

    const handleClearLogs = useCallback(() => {
        setEvents([]);
    }, []);

    useEffect(() => {
        if (!canManageLoops) return;
        void loadRoundData(false);
    }, [canManageLoops, loadRoundData]);

    useEffect(() => {
        if (!canManageLoops || !roundId) return;
        const timer = window.setInterval(async () => {
            try {
                const [latestRound, latestSteps] = await Promise.all([
                    api.getRound(roundId),
                    api.getRoundSteps(roundId, 2000),
                ]);
                setRound(latestRound);
                setSteps(latestSteps);
            } catch {
                // ignore polling errors
            }
        }, 3000);
        return () => window.clearInterval(timer);
    }, [canManageLoops, roundId]);

    useEffect(() => {
        if (!canManageLoops || !round) return;
        let cancelled = false;

        const run = async () => {
            const trainPromise = trainStep?.id
                ? api.getStepMetricSeries(trainStep.id, 5000).catch(() => [])
                : Promise.resolve([]);

            const roundArtifactsPromise = api.getRoundArtifacts(round.id, 2000).catch(() => ({
                roundId: round.id,
                items: [] as RuntimeRoundStepArtifacts[],
            }));

            const [trainPoints, roundArtifactsResp] = await Promise.all([trainPromise, roundArtifactsPromise]);

            if (cancelled) return;

            const roundArtifactItems = [...(roundArtifactsResp.items || [])].sort(
                (left, right) => Number(left.stepIndex || 0) - Number(right.stepIndex || 0),
            );
            const pickLatestArtifactsByType = (
                matcher: (normalizedStepType: string) => boolean,
                preferredStepId?: string,
            ): RuntimeRoundStepArtifacts | null => {
                const matches = roundArtifactItems.filter((item) => {
                    const artifacts = Array.isArray(item.artifacts) ? item.artifacts : [];
                    if (artifacts.length === 0) return false;
                    const normalizedType = normalizeStepTypeText(String(item.stepType || ''));
                    return matcher(normalizedType);
                });
                if (matches.length === 0) return null;
                if (preferredStepId) {
                    const preferred = matches.find((item) => item.stepId === preferredStepId);
                    if (preferred) return preferred;
                }
                return matches[matches.length - 1];
            };

            const trainArtifactItem = pickLatestArtifactsByType(
                (type) => type === 'train',
                trainStep?.id,
            );
            const evalArtifactItem = pickLatestArtifactsByType(
                (type) => type === 'eval' || type.includes('eval'),
                evalArtifactStep?.id,
            );
            const exportArtifactItem = pickLatestArtifactsByType(
                (type) => type === 'export' || type === 'upload_artifact',
                exportStep?.id,
            );

            setTrainMetricPoints(trainPoints);
            setTrainArtifacts(trainArtifactItem?.artifacts || []);
            setTrainArtifactSourceStepId(trainArtifactItem?.stepId || trainStep?.id || '');
            setEvalArtifacts(evalArtifactItem?.artifacts || []);
            setEvalArtifactSourceStepId(evalArtifactItem?.stepId || evalArtifactStep?.id || '');
            setExportArtifacts(exportArtifactItem?.artifacts || []);
            setExportArtifactSourceStepId(exportArtifactItem?.stepId || exportStep?.id || '');

            roundArtifactItems.forEach((item) => {
                const artifactRows = item.artifacts || [];
                if (!item.stepId || artifactRows.length === 0) return;
                void ensureArtifactUrls(item.stepId, artifactRows);
            });

            if (round.mode === 'manual') {
                setTopkCandidates([]);
                setTopkSource('-');
                return;
            }

            let rows: RuntimeStepCandidate[] = [];
            let source = '-';
            let selectionResolved = false;
            if (round.mode === 'active_learning') {
                try {
                    const selection = await api.getRoundSelection(round.id);
                    rows = selection.effectiveSelected || [];
                    source = 'Round Selection';
                    selectionResolved = true;
                } catch {
                    // latest round/phase constraints may reject history round, fallback below
                }
            }
            if (!selectionResolved && rows.length === 0 && selectStep?.id) {
                try {
                    rows = await api.getStepCandidates(selectStep.id, 500);
                    source = 'SELECT Step';
                } catch {
                    // ignore
                }
            }
            if (!selectionResolved && rows.length === 0 && scoreStep?.id) {
                try {
                    rows = await api.getStepCandidates(scoreStep.id, 500);
                    source = 'SCORE Step';
                } catch {
                    // ignore
                }
            }
            if (!cancelled) {
                setTopkCandidates(rows);
                setTopkSource(source);
            }
        };

        void run();
        return () => {
            cancelled = true;
        };
    }, [
        canManageLoops,
        round?.id,
        round?.mode,
        trainStep?.id,
        trainStep?.updatedAt,
        evalArtifactStep?.id,
        evalArtifactStep?.updatedAt,
        exportStep?.id,
        exportStep?.updatedAt,
        selectStep?.id,
        selectStep?.updatedAt,
        scoreStep?.id,
        scoreStep?.updatedAt,
        ensureArtifactUrls,
    ]);

    useEffect(() => {
        if (!canManageLoops || consoleTargetSteps.length === 0) {
            setEvents([]);
            setEventFacets(EMPTY_FACETS);
            eventCursorRef.current = 0;
            eventCursorByStepRef.current = {};
            setWsConnected(false);
            return;
        }
        let cancelled = false;

        const run = async () => {
            if (consoleStage === 'all') {
                const rows = await Promise.all(
                    consoleTargetSteps.map(async (step) => {
                        try {
                            const response = await api.getStepEvents(step.id, {
                                afterSeq: 0,
                                limit: 5000,
                                includeFacets: false,
                            });
                            const items = (response.items || []).map((item) => annotateEventWithStep(item, step));
                            const nextAfterSeq = Number(
                                response.nextAfterSeq
                                ?? (response.items || []).reduce((max, item) => Math.max(max, Number(item.seq || 0)), 0),
                            );
                            return {step, items, nextAfterSeq};
                        } catch {
                            return {step, items: [] as RuntimeStepEvent[], nextAfterSeq: 0};
                        }
                    }),
                );
                if (cancelled) return;

                const merged = rows
                    .flatMap((row) => row.items)
                    .sort((left, right) => {
                        const leftTs = Date.parse(String(left.ts || ''));
                        const rightTs = Date.parse(String(right.ts || ''));
                        if (Number.isFinite(leftTs) && Number.isFinite(rightTs) && leftTs !== rightTs) {
                            return leftTs - rightTs;
                        }
                        return Number(left.seq || 0) - Number(right.seq || 0);
                    });
                setEvents(mergeEventBuffer([], merged));
                setEventFacets(buildEventFacetsFromItems(merged));
                const nextMap: Record<string, number> = {};
                rows.forEach((row) => {
                    nextMap[row.step.id] = Number(row.nextAfterSeq || 0);
                });
                eventCursorByStepRef.current = nextMap;
                eventCursorRef.current = 0;
                setWsConnected(false);
                return;
            }

            const targetStep = consoleTargetSteps[0];
            try {
                const response = await api.getStepEvents(targetStep.id, {
                    afterSeq: 0,
                    limit: 5000,
                    includeFacets: true,
                });
                if (cancelled) return;
                const annotated = (response.items || []).map((item) => annotateEventWithStep(item, targetStep));
                setEvents(annotated);
                setEventFacets(buildEventFacetsFromItems(annotated));
                eventCursorRef.current = Number(
                    response.nextAfterSeq
                    ?? (response.items || []).reduce((max, item) => Math.max(max, Number(item.seq || 0)), 0),
                );
                eventCursorByStepRef.current = {[targetStep.id]: eventCursorRef.current};
            } catch {
                if (cancelled) return;
                setEvents([]);
                setEventFacets(EMPTY_FACETS);
                eventCursorRef.current = 0;
                eventCursorByStepRef.current = {};
            }
        };

        void run();
        return () => {
            cancelled = true;
            eventCursorRef.current = 0;
            eventCursorByStepRef.current = {};
            setWsConnected(false);
        };
    }, [canManageLoops, consoleStage, consoleTargetSteps, annotateEventWithStep]);

    useEffect(() => {
        if (!canManageLoops || consoleStage === 'all' || consoleTargetSteps.length === 0) return;
        const timer = window.setTimeout(() => {
            void reloadFilteredEvents(consoleTargetSteps[0]).catch(() => undefined);
        }, 250);
        return () => window.clearTimeout(timer);
    }, [canManageLoops, consoleStage, consoleTargetSteps, reloadFilteredEvents]);

    useEffect(() => {
        if (!canManageLoops || consoleTargetSteps.length === 0) return;
        const timer = window.setInterval(async () => {
            if (consoleStage === 'all') {
                try {
                    const cursorMap = {...eventCursorByStepRef.current};
                    const results = await Promise.all(
                        consoleTargetSteps.map(async (step) => {
                            try {
                                const response = await api.getStepEvents(step.id, {
                                    afterSeq: Number(cursorMap[step.id] || 0),
                                    limit: 5000,
                                    includeFacets: false,
                                });
                                return {step, response};
                            } catch {
                                return null;
                            }
                        }),
                    );
                    const incoming: RuntimeStepEvent[] = [];
                    results.forEach((item) => {
                        if (!item) return;
                        const rows = item.response.items || [];
                        if (rows.length > 0) {
                            incoming.push(...rows.map((row) => annotateEventWithStep(row, item.step)));
                        }
                        const nextAfterSeq = Number(
                            item.response.nextAfterSeq
                            ?? rows.reduce((max, row) => Math.max(max, Number(row.seq || 0)), 0),
                        );
                        cursorMap[item.step.id] = Math.max(Number(cursorMap[item.step.id] || 0), nextAfterSeq);
                    });
                    eventCursorByStepRef.current = cursorMap;
                    if (incoming.length > 0) {
                        const merged = mergeEventBuffer(eventsRef.current, incoming);
                        setEvents(merged);
                        setEventFacets(buildEventFacetsFromItems(merged));
                    }
                } catch {
                    // ignore polling errors
                }
                return;
            }

            const targetStep = consoleTargetSteps[0];
            try {
                const response = await api.getStepEvents(targetStep.id, {
                    afterSeq: eventCursorRef.current,
                    limit: 5000,
                    includeFacets: false,
                });
                const incoming = (response.items || []).map((item) => annotateEventWithStep(item, targetStep));
                if (incoming.length > 0) {
                    const merged = mergeEventBuffer(eventsRef.current, incoming);
                    setEvents(merged);
                    setEventFacets(buildEventFacetsFromItems(merged));
                    eventCursorRef.current = Math.max(
                        eventCursorRef.current,
                        ...incoming.map((item) => Number(item.seq || 0)),
                    );
                    eventCursorByStepRef.current[targetStep.id] = eventCursorRef.current;
                }
            } catch {
                // ignore polling errors
            }
        }, 3000);
        return () => window.clearInterval(timer);
    }, [canManageLoops, consoleStage, consoleTargetSteps, annotateEventWithStep]);

    useEffect(() => {
        if (!canManageLoops || consoleStage === 'all' || consoleTargetSteps.length === 0 || !token) {
            setWsConnected(false);
            return;
        }
        const targetStep = consoleTargetSteps[0];
        const ws = new WebSocket(buildWsUrl(targetStep.id, eventCursorRef.current, token));
        ws.onopen = () => setWsConnected(true);
        ws.onclose = () => setWsConnected(false);
        ws.onerror = () => setWsConnected(false);
        ws.onmessage = (event: MessageEvent<string>) => {
            try {
                const raw = JSON.parse(event.data || '{}') as RawRuntimeStepEvent;
                const payload = normalizeRuntimeEvent(raw);
                if (!payload) return;
                const incoming = annotateEventWithStep(payload, targetStep);
                const merged = mergeEventBuffer(eventsRef.current, [incoming]);
                setEvents(merged);
                setEventFacets(buildEventFacetsFromItems(merged));
                eventCursorRef.current = Math.max(eventCursorRef.current, incoming.seq);
                eventCursorByStepRef.current[targetStep.id] = eventCursorRef.current;
            } catch {
                // ignore malformed ws payload
            }
        };
        return () => {
            ws.close();
            setWsConnected(false);
        };
    }, [canManageLoops, consoleStage, consoleTargetSteps, token, annotateEventWithStep]);

    useEffect(() => {
        if (!autoScrollLogs) return;
        const container = logScrollRef.current;
        if (!container) return;
        container.scrollTop = container.scrollHeight;
    }, [visibleEvents.length, autoScrollLogs]);

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

    const exportStepId = exportArtifactSourceStepId || exportStep?.id || '';
    const simulationActionStages: RoundStageKey[] = ['activate_samples', 'advance_branch'];

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
                        <Button loading={refreshing} onClick={() => loadRoundData(true)}>刷新</Button>
                    </div>
                </div>
                <div className="mt-4 border-t border-github-border pt-4">
                    {sortedSteps.length === 0 ? (
                        <Empty description="当前 Round 没有 Step"/>
                    ) : (
                        <Steps
                            current={Math.max(0, currentTimelineIndex)}
                            onChange={(index) => {
                                const target = sortedSteps[index];
                                if (!target) return;
                                setStepDrawerStepId(target.id);
                                setStepDrawerOpen(true);
                                setConsoleStage(mapStepTypeToStage(target.stepType));
                            }}
                            items={sortedSteps.map((item) => ({
                                title: `#${item.stepIndex} ${item.stepType}`,
                                description: (
                                    <div className="flex flex-col gap-0.5">
                                        <span className="text-xs text-github-muted">{`state: ${item.state}`}</span>
                                        <span className="text-xs text-github-muted">
                                            {`elapsed: ${Math.floor(computeDurationMs(item.startedAt, item.endedAt, nowMs) / 1000)}s`}
                                        </span>
                                    </div>
                                ),
                                status: getStepFlowStatus(item.state),
                            }))}
                            size="small"
                        />
                    )}
                </div>
            </Card>

            <Card className="!border-github-border !bg-github-panel" title="训练曲线">
                {!trainStep ? (
                    <Empty description="当前 Round 无训练阶段"/>
                ) : trainMetricChartData.length === 0 ? (
                    <Empty description="训练阶段暂无指标曲线"/>
                ) : (
                    <div className="h-[320px]">
                        <ResponsiveContainer width="100%" height="100%">
                            <LineChart data={trainMetricChartData}>
                                <CartesianGrid strokeDasharray="3 3"/>
                                <XAxis dataKey="step"/>
                                <YAxis/>
                                <Tooltip/>
                                {trainMetricNames.map((name, idx) => (
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

            <Card className="!border-github-border !bg-github-panel" title="训练/评估制品">
                {trainEvalArtifactRows.length === 0 ? (
                    <Empty description="当前 Round 暂无训练/评估制品"/>
                ) : (
                    <Table<TrainEvalArtifactRow>
                        size="small"
                        rowKey={(row) => row.key}
                        dataSource={trainEvalArtifactRows}
                        pagination={{pageSize: 10, showSizeChanger: false}}
                        columns={[
                            {
                                title: '来源阶段',
                                dataIndex: 'stageLabel',
                                width: 120,
                                render: (_value: unknown, row: TrainEvalArtifactRow) => (
                                    <Tag color={row.stage === 'train' ? 'blue' : 'green'}>{row.stageLabel}</Tag>
                                ),
                            },
                            {title: '名称', dataIndex: 'name'},
                            {title: '类型', dataIndex: 'kind', width: 180, render: (v: string) => <Tag>{v}</Tag>},
                            {
                                title: '大小',
                                width: 120,
                                render: (_value: unknown, row: TrainEvalArtifactRow) => formatArtifactSize(row.meta?.size),
                            },
                            {
                                title: '操作',
                                width: 220,
                                render: (_value: unknown, row: TrainEvalArtifactRow) => {
                                    const url = artifactUrls[buildArtifactKey(row.stepId, row.name)];
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

            {round.mode !== 'manual' ? (
                    <Card
                        className="!border-github-border !bg-github-panel"
                        title="候选样本 / TopK"
                        extra={<Tag>{`来源: ${topkSource}`}</Tag>}
                    >
                    {topkCandidates.length === 0 ? (
                        <Empty description="当前 Round 暂无候选样本"/>
                    ) : (
                        <Table
                            size="small"
                            pagination={{pageSize: 10, showSizeChanger: false}}
                            dataSource={topkCandidates}
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
                                    render: (value: number) => {
                                        const percent = Math.max(0, Math.min(100, Number((Number(value || 0) * 100).toFixed(2))));
                                        return (
                                            <div className="flex w-full flex-col gap-0.5">
                                                <Progress percent={percent}/>
                                                <Text type="secondary">{Number(value || 0).toFixed(6)}</Text>
                                            </div>
                                        );
                                    },
                                },
                                {
                                    title: 'Reason',
                                    dataIndex: 'reason',
                                    render: (value: Record<string, any>) => <Text type="secondary">{JSON.stringify(value || {})}</Text>,
                                },
                            ]}
                        />
                    )}
                </Card>
            ) : null}

            <Card className="!border-github-border !bg-github-panel" title="评估结果">
                {!evalArtifactStep ? (
                    <Empty description="当前 Round 无评估阶段"/>
                ) : (
                    <div>
                        <Text strong>评估指标</Text>
                        {Object.keys(evalMetricSummary || {}).length === 0 ? (
                            <Empty description="评估阶段暂无指标"/>
                        ) : (
                            <Descriptions size="small" column={2} className="!mt-2">
                                {Object.entries(evalMetricSummary || {}).map(([key, value]) => (
                                    <Descriptions.Item key={key} label={key}>{String(value)}</Descriptions.Item>
                                ))}
                            </Descriptions>
                        )}
                    </div>
                )}
            </Card>

            {(exportStep || exportArtifacts.length > 0 || round.mode === 'manual') ? (
                <Card className="!border-github-border !bg-github-panel" title="导出/上传制品">
                    {!exportStep ? (
                        <Empty description="当前 Round 无导出/上传阶段"/>
                    ) : exportArtifacts.length === 0 ? (
                        <Empty description="导出阶段暂无制品"/>
                    ) : (
                        <Table
                            size="small"
                            rowKey={(item) => item.name}
                            dataSource={exportArtifacts}
                            pagination={{pageSize: 8}}
                            columns={[
                                {title: '名称', dataIndex: 'name'},
                                {title: '类型', dataIndex: 'kind', width: 180, render: (v: string) => <Tag>{v}</Tag>},
                                {
                                    title: '大小',
                                    width: 120,
                                    render: (_value: unknown, row: RuntimeStepArtifact) => formatArtifactSize(row.meta?.size),
                                },
                                {
                                    title: '操作',
                                    width: 220,
                                    render: (_value: unknown, row: RuntimeStepArtifact) => {
                                        const url = artifactUrls[buildArtifactKey(exportStepId, row.name)];
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
            ) : null}

            {round.mode === 'simulation' ? (
                <Card className="!border-github-border !bg-github-panel" title="模拟推进阶段">
                    <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
                        {simulationActionStages.map((key) => {
                            const stage = stageSnapshots[key];
                            const step = stage.representativeStep;
                            return (
                                <div key={key} className="rounded border border-github-border p-3">
                                    <div className="mb-1 flex items-center justify-between gap-2">
                                        <Text strong>{stage.label}</Text>
                                        <Tag color={step ? (STEP_STATE_COLOR[step.state] || 'default') : 'default'}>
                                            {step?.state || 'pending'}
                                        </Tag>
                                    </div>
                                    <div className="text-xs text-github-muted">
                                        <div>{`Step: ${step ? `#${step.stepIndex}` : '-'}`}</div>
                                        <div>{`耗时: ${stage.representativeDurationSec}s`}</div>
                                    </div>
                                </div>
                            );
                        })}
                    </div>
                </Card>
            ) : null}

            <Card
                className="!border-github-border !bg-github-panel"
                title={
                    consoleStage === 'all'
                        ? 'Round 控制台日志 · 全部阶段'
                        : (consoleStep
                            ? `Round 控制台日志 · ${STAGE_LABEL[consoleStage]} (#${consoleStep.stepIndex} ${consoleStep.stepType})`
                            : 'Round 控制台日志')
                }
                extra={(
                    <Space size={8}>
                        <Tag color={wsConnected ? 'success' : 'default'}>{wsConnected ? 'WS 实时' : 'WS 断开'}</Tag>
                        <Button size="small" onClick={handleClearLogs}>清屏</Button>
                        <Button size="small" onClick={handleExportLogs} disabled={visibleEvents.length === 0}>
                            导出
                        </Button>
                    </Space>
                )}
            >
                {consoleTargetSteps.length === 0 ? (
                    <Empty description="当前 Round 暂无可用日志阶段"/>
                ) : (
                    <div className="flex flex-col gap-3">
                        <div className="flex flex-wrap items-center gap-2">
                            <Select
                                className="w-[180px]"
                                value={consoleStage}
                                options={consoleStageOptions}
                                onChange={(value) => setConsoleStage(value as ConsoleStageFilter)}
                            />
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
                                    {visibleEvents.map((item, idx) => {
                                        const levelKey = String(item.level || '').toUpperCase();
                                        const lineClass = LEVEL_COLOR_CLASS[levelKey] || 'text-slate-200';
                                        return (
                                            <div key={`${item.ts}-${item.seq}-${item.eventType}-${idx}`} className={`rounded px-2 py-1 ${lineClass} hover:bg-slate-900`}>
                                                <div className="flex flex-wrap items-center gap-2">
                                                    <span className="text-slate-400">{formatDateTime(item.ts)}</span>
                                                    <span className="text-slate-500">#{item.seq}</span>
                                                    <Tag color={EVENT_TYPE_COLOR[item.eventType] || 'default'} className="!m-0">{item.eventType}</Tag>
                                                    {item.level ? <Tag color={ERROR_LEVELS.has(String(item.level).toUpperCase()) ? 'error' : 'blue'} className="!m-0">{item.level}</Tag> : null}
                                                    {(item.tags || []).slice(0, 4).map((tag, tagIdx) => (
                                                        <Tag key={`${item.ts}-${item.seq}-${tag}-${tagIdx}`} className="!m-0">{tag}</Tag>
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
                title={stepDrawerStep ? `Step #${stepDrawerStep.stepIndex} · ${stepDrawerStep.stepType}` : 'Step 详情'}
            >
                {!stepDrawerStep ? (
                    <Empty description="暂无选中 Step"/>
                ) : (
                    <Descriptions size="small" column={1}>
                        <Descriptions.Item label="Step ID">{stepDrawerStep.id}</Descriptions.Item>
                        <Descriptions.Item label="类型">{stepDrawerStep.stepType}</Descriptions.Item>
                        <Descriptions.Item label="状态">
                            <Tag color={STEP_STATE_COLOR[stepDrawerStep.state] || 'default'}>{stepDrawerStep.state}</Tag>
                        </Descriptions.Item>
                        <Descriptions.Item label="执行器">{stepDrawerStep.assignedExecutorId || '-'}</Descriptions.Item>
                        <Descriptions.Item label="Attempt">{`${stepDrawerStep.attempt || 1}/${stepDrawerStep.maxAttempts || 1}`}</Descriptions.Item>
                        <Descriptions.Item label="开始时间">{formatDateTime(stepDrawerStep.startedAt)}</Descriptions.Item>
                        <Descriptions.Item label="结束时间">{formatDateTime(stepDrawerStep.endedAt)}</Descriptions.Item>
                        <Descriptions.Item label="运行时长">
                            {formatDuration(computeDurationMs(stepDrawerStep.startedAt, stepDrawerStep.endedAt, nowMs))}
                        </Descriptions.Item>
                        <Descriptions.Item label="依赖 Step">
                            {(stepDrawerStep.dependsOnStepIds || []).length > 0
                                ? (stepDrawerStep.dependsOnStepIds || []).map((item) => <Tag key={item}>{item}</Tag>)
                                : '-'}
                        </Descriptions.Item>
                        <Descriptions.Item label="错误信息">{stepDrawerStep.lastError || '-'}</Descriptions.Item>
                    </Descriptions>
                )}
            </Drawer>
        </div>
    );
};

export default ProjectLoopRoundDetail;
