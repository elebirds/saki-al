import React, {useCallback, useEffect, useMemo, useRef, useState} from 'react';
import {
    App,
    Alert,
    Button,
    Card,
    Descriptions,
    Drawer,
    Empty,
    Progress,
    Spin,
    Steps,
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
import RoundConsolePanel from './components/RoundConsolePanel';
import {
    RuntimeRound,
    RuntimeRoundEvent,
    RuntimeRoundArtifact,
    RuntimeStep,
    RuntimeStepCandidate,
    RuntimeStepMetricPoint,
} from '../../../types';
import {mergeRuntimeRoundEvents, normalizeRuntimeRoundEvent} from './runtimeEventFormatter';
import {
    formatMetricValue,
    normalizeFinalMetricSource,
    orderMetricEntries,
} from './runtimeMetricView';

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
    syncing_env: 'processing',
    probing_runtime: 'processing',
    binding_device: 'processing',
    running: 'processing',
    retrying: 'warning',
    succeeded: 'success',
    failed: 'error',
    cancelled: 'warning',
    skipped: 'default',
};

const MAX_EVENT_BUFFER = 20000;
const ROUND_EVENT_SYNC_LIMIT = 5000;
const ROUND_META_REFRESH_THROTTLE_MS = 2000;
const ROUND_WS_RECONNECT_DELAYS = [1000, 2000, 5000, 10000];
const TERMINAL_STEP_STATES = new Set(['succeeded', 'failed', 'cancelled', 'skipped']);

type RoundStageKey =
    | 'train'
    | 'eval'
    | 'score'
    | 'select'
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

interface RoundArtifactTableRow {
    key: string;
    stage: string;
    stageLabel: string;
    artifactClass: string;
    artifactClassLabel: string;
    stepId: string;
    stepIndex: number;
    name: string;
    kind: string;
    size?: number | null;
    createdAt?: string | null;
}

const STAGE_LABEL: Record<RoundStageKey, string> = {
    train: '训练',
    eval: '评估',
    score: '评分',
    select: '选样',
    custom: '自定义',
};

const FINAL_METRIC_SOURCE_LABEL: Record<'eval' | 'train' | 'other' | 'none', string> = {
    eval: 'Eval(Test)',
    train: 'Train',
    other: 'Other Step',
    none: 'None',
};

const ARTIFACT_CLASS_LABEL: Record<string, string> = {
    model_artifact: '模型',
    eval_artifact: '评估',
    selection_artifact: '选样',
    prediction_artifact: '预测',
    generic_artifact: '通用',
};

const TRAIN_METRIC_COLORS = ['#1677ff', '#52c41a', '#faad14', '#13c2c2', '#eb2f96'];
const LOSS_METRIC_NAME_RE = /loss/i;

const MODE_STAGE_ORDER: Record<string, RoundStageKey[]> = {
    active_learning: ['train', 'eval', 'score', 'select', 'custom'],
    simulation: ['train', 'eval', 'score', 'select', 'custom'],
    manual: ['train', 'eval', 'custom'],
};

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

const buildRoundEventsWsUrl = (
    roundId: string,
    token: string,
    afterCursor?: string | null,
    stages?: string[],
): string => {
    const apiBaseUrlRaw = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api/v1';
    const apiBaseUrl = apiBaseUrlRaw.endsWith('/') ? apiBaseUrlRaw.slice(0, -1) : apiBaseUrlRaw;
    const query = new URLSearchParams();
    query.set('token', token);
    if (afterCursor) query.set('after_cursor', afterCursor);
    if (stages && stages.length > 0) query.set('stages', stages.join(','));
    const suffix = `/rounds/${roundId}/events/ws?${query.toString()}`;
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
    return ['train', 'eval', 'score', 'select', 'custom'];
};

const normalizeStepTypeText = (stepType: string): string => String(stepType || '').trim().toLowerCase();

const mapStepTypeToStage = (stepType: string): RoundStageKey => {
    switch (normalizeStepTypeText(stepType)) {
        case 'train':
            return 'train';
        case 'eval':
        case 'evaluate':
        case 'evaluation':
            return 'eval';
        case 'score':
            return 'score';
        case 'select':
            return 'select';
        default:
            return 'custom';
    }
};

const buildArtifactKey = (stepId: string, artifactName: string): string => `${stepId}:${artifactName}`;
const isLossMetricName = (metricName: string): boolean => LOSS_METRIC_NAME_RE.test(String(metricName || ''));

const extractMetricPointsFromEvent = (event: RuntimeRoundEvent): RuntimeStepMetricPoint[] => {
    if (event.eventType !== 'metric') return [];
    if (event.stage !== 'train') return [];
    const payload = event.payload && typeof event.payload === 'object' ? event.payload : {};
    const points: RuntimeStepMetricPoint[] = [];
    const stepValue = Number(payload.step ?? payload.globalStep ?? payload.iteration ?? event.seq ?? 0);
    const epochRaw = payload.epoch;
    const epoch = epochRaw == null ? null : Number(epochRaw);
    const pushPoint = (metricName: string, metricValue: unknown) => {
        const value = Number(metricValue);
        if (!metricName || !Number.isFinite(value)) return;
        points.push({
            step: Number.isFinite(stepValue) ? stepValue : 0,
            epoch: Number.isFinite(Number(epoch)) ? Number(epoch) : null,
            metricName,
            metricValue: value,
            ts: String(event.ts || new Date().toISOString()),
        });
    };
    const directMetricName = String(payload.metricName ?? payload.metric_name ?? '').trim();
    if (directMetricName) {
        pushPoint(directMetricName, payload.metricValue ?? payload.metric_value);
    }
    if (payload.metrics && typeof payload.metrics === 'object') {
        Object.entries(payload.metrics as Record<string, unknown>).forEach(([name, value]) => {
            pushPoint(String(name || '').trim(), value);
        });
    }
    return points;
};

const mergeMetricPoints = (
    previous: RuntimeStepMetricPoint[],
    incoming: RuntimeStepMetricPoint[],
): RuntimeStepMetricPoint[] => {
    if (incoming.length === 0) return previous;
    const merged = new Map<string, RuntimeStepMetricPoint>();
    [...previous, ...incoming].forEach((item) => {
        const key = `${item.step}|${item.epoch ?? ''}|${item.metricName}|${item.ts}`;
        merged.set(key, item);
    });
    return Array.from(merged.values()).sort((left, right) => {
        if (Number(left.step || 0) !== Number(right.step || 0)) return Number(left.step || 0) - Number(right.step || 0);
        const leftTs = Date.parse(String(left.ts || ''));
        const rightTs = Date.parse(String(right.ts || ''));
        if (Number.isFinite(leftTs) && Number.isFinite(rightTs) && leftTs !== rightTs) return leftTs - rightTs;
        return String(left.metricName || '').localeCompare(String(right.metricName || ''));
    });
};

const normalizeIncomingStepState = (raw: unknown): string | null => {
    const state = String(raw || '').trim().toLowerCase();
    if (!state) return null;
    if (
        [
            'pending',
            'ready',
            'dispatching',
            'syncing_env',
            'probing_runtime',
            'binding_device',
            'running',
            'retrying',
            'succeeded',
            'failed',
            'cancelled',
            'skipped',
        ]
            .includes(state)
    ) {
        return state;
    }
    return null;
};

const isTerminalStepState = (state?: string | null): boolean => TERMINAL_STEP_STATES.has(String(state || '').toLowerCase());

const deriveArtifactClass = (stage: RoundStageKey, kindRaw: string): string => {
    const kind = String(kindRaw || '').toLowerCase();
    if (kind.includes('model')) return 'model_artifact';
    if (kind.includes('eval')) return 'eval_artifact';
    if (kind.includes('selection') || stage === 'select') return 'selection_artifact';
    if (kind.includes('predict')) return 'prediction_artifact';
    return 'generic_artifact';
};

const buildArtifactFromRoundEvent = (event: RuntimeRoundEvent): RuntimeRoundArtifact | null => {
    if (event.eventType !== 'artifact') return null;
    const payload = event.payload && typeof event.payload === 'object' ? event.payload : {};
    const name = String(payload.name || '').trim();
    if (!name) return null;
    const kind = String(payload.kind || 'artifact').trim() || 'artifact';
    const uri = String(payload.uri || '').trim();
    const sizeRaw = payload.size ?? (payload.meta && typeof payload.meta === 'object' ? (payload.meta as Record<string, any>).size : null);
    const sizeValue = Number(sizeRaw);
    return {
        stepId: event.stepId,
        stepIndex: Number(event.stepIndex || 0),
        stage: event.stage,
        artifactClass: deriveArtifactClass(event.stage, kind),
        name,
        kind,
        uri,
        size: Number.isFinite(sizeValue) && sizeValue > 0 ? sizeValue : null,
        createdAt: typeof payload.createdAt === 'string'
            ? payload.createdAt
            : (typeof payload.created_at === 'string' ? payload.created_at : event.ts),
    };
};

const getStepFlowStatus = (state: string): 'wait' | 'process' | 'finish' | 'error' => {
    if (state === 'succeeded' || state === 'skipped') return 'finish';
    if (state === 'failed' || state === 'cancelled') return 'error';
    if (
        state === 'running'
        || state === 'binding_device'
        || state === 'probing_runtime'
        || state === 'syncing_env'
        || state === 'dispatching'
        || state === 'retrying'
        || state === 'ready'
    ) {
        return 'process';
    }
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
    const running = sortedDesc.find((item) => [
        'running',
        'binding_device',
        'probing_runtime',
        'syncing_env',
        'dispatching',
        'retrying',
    ].includes(item.state));
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
    const [roundArtifacts, setRoundArtifacts] = useState<RuntimeRoundArtifact[]>([]);
    const [artifactUrls, setArtifactUrls] = useState<Record<string, string>>({});

    const [consoleStage, setConsoleStage] = useState<ConsoleStageFilter>('all');
    const [events, setEvents] = useState<RuntimeRoundEvent[]>([]);
    const [wsConnected, setWsConnected] = useState<boolean>(false);
    const eventsRef = useRef<RuntimeRoundEvent[]>([]);
    const roundEventCursorRef = useRef<string | null>(null);
    const wsRef = useRef<WebSocket | null>(null);
    const wsRetryTimerRef = useRef<number | null>(null);
    const wsRetryCountRef = useRef<number>(0);
    const wsClosedRef = useRef<boolean>(false);
    const metaRefreshTimerRef = useRef<number | null>(null);
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
    const evalStep = stageSnapshots.eval.representativeStep;
    const scoreStep = stageSnapshots.score.representativeStep;
    const selectStep = stageSnapshots.select.representativeStep;

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
    const activeConsoleStages = useMemo(
        () => (consoleStage === 'all' ? [] : [consoleStage]),
        [consoleStage],
    );

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
        if (steps.length > 0) {
            const done = steps.filter((item) => isTerminalStepState(item.state)).length;
            return Math.max(0, Math.min(100, Number(((done / steps.length) * 100).toFixed(2))));
        }
        const stepCounts = round?.stepCounts || {};
        const total = Object.values(stepCounts).reduce((sum, item) => sum + Number(item || 0), 0);
        if (!total) return 0;
        const done = ['succeeded', 'failed', 'cancelled', 'skipped']
            .reduce((sum, key) => sum + Number((stepCounts as Record<string, number>)[key] || 0), 0);
        return Math.max(0, Math.min(100, Number(((done / total) * 100).toFixed(2))));
    }, [round?.stepCounts, steps]);

    const trainFinalMetricPairs = useMemo(
        () => orderMetricEntries(round?.trainFinalMetrics || trainStep?.metrics || {}),
        [round?.trainFinalMetrics, trainStep?.id, trainStep?.metrics],
    );

    const evalFinalMetricPairs = useMemo(
        () => orderMetricEntries(round?.evalFinalMetrics || stageSnapshots.eval.metricSummary || evalStep?.metrics || {}),
        [round?.evalFinalMetrics, stageSnapshots.eval.metricSummary, evalStep?.id, evalStep?.metrics],
    );

    const finalMetricPairs = useMemo(
        () => orderMetricEntries(round?.finalMetrics || {}),
        [round?.finalMetrics],
    );

    const finalMetricsSource = useMemo(
        () => normalizeFinalMetricSource(round?.finalMetricsSource),
        [round?.finalMetricsSource],
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

    const trainScoreAxisUpperBound = useMemo(() => {
        let maxValue = 0;
        trainMetricPoints.forEach((point) => {
            if (isLossMetricName(point.metricName)) return;
            const value = Number(point.metricValue);
            if (!Number.isFinite(value)) return;
            maxValue = Math.max(maxValue, value);
        });
        if (maxValue <= 0) return 1;
        const padded = Math.min(1, maxValue * 1.1);
        return Math.max(0.05, Number(padded.toFixed(4)));
    }, [trainMetricPoints]);

    const roundArtifactRows = useMemo<RoundArtifactTableRow[]>(() => {
        return (roundArtifacts || []).map((item) => {
            const stageKey = String(item.stage || '').trim().toLowerCase() as RoundStageKey;
            const stageLabel = STAGE_LABEL[stageKey] || String(item.stage || '-');
            const artifactClass = String(item.artifactClass || '').trim().toLowerCase();
            return {
                key: buildArtifactKey(item.stepId, item.name),
                stage: String(item.stage || ''),
                stageLabel,
                artifactClass,
                artifactClassLabel: ARTIFACT_CLASS_LABEL[artifactClass] || artifactClass || '-',
                stepId: item.stepId,
                stepIndex: Number(item.stepIndex || 0),
                name: item.name,
                kind: item.kind,
                size: item.size,
                createdAt: item.createdAt,
            };
        });
    }, [roundArtifacts]);

    const ensureArtifactUrls = useCallback(async (items: RuntimeRoundArtifact[]) => {
        if (!items || items.length === 0) return;
        const currentMap = artifactUrlsRef.current;
        const missing = items.filter((item) => !currentMap[buildArtifactKey(item.stepId, item.name)]);
        if (missing.length === 0) return;

        const updates: Record<string, string> = {};
        for (const artifact of missing) {
            const key = buildArtifactKey(artifact.stepId, artifact.name);
            const uri = String(artifact.uri || '');
            if (uri.startsWith('http://') || uri.startsWith('https://')) {
                updates[key] = uri;
                continue;
            }
            if (!uri.startsWith('s3://')) continue;
            try {
                const row = await api.getStepArtifactDownloadUrl(artifact.stepId, artifact.name, 2);
                updates[key] = row.downloadUrl;
            } catch {
                // ignore unavailable artifacts
            }
        }

        if (Object.keys(updates).length > 0) {
            setArtifactUrls((prev) => ({...prev, ...updates}));
        }
    }, []);

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

    const scheduleRoundMetaRefresh = useCallback(() => {
        if (metaRefreshTimerRef.current != null) return;
        metaRefreshTimerRef.current = window.setTimeout(() => {
            metaRefreshTimerRef.current = null;
            void loadRoundData(true);
        }, ROUND_META_REFRESH_THROTTLE_MS);
    }, [loadRoundData]);

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

    const handleClearLogs = useCallback(() => {
        eventsRef.current = [];
        setEvents([]);
    }, []);

    useEffect(() => {
        if (!canManageLoops) return;
        void loadRoundData(false);
    }, [canManageLoops, loadRoundData]);

    useEffect(() => {
        if (!canManageLoops || !round) return;
        let cancelled = false;

        const run = async () => {
            const trainPromise = trainStep?.id
                ? api.getStepMetricSeries(trainStep.id, 5000).catch(() => [])
                : Promise.resolve([]);

            const roundArtifactsPromise = api.getRoundArtifacts(round.id, 2000).catch(() => ({
                roundId: round.id,
                items: [] as RuntimeRoundArtifact[],
            }));

            const [trainPoints, roundArtifactsResp] = await Promise.all([trainPromise, roundArtifactsPromise]);

            if (cancelled) return;

            const roundArtifactItems = [...(roundArtifactsResp.items || [])].sort(
                (left, right) => Number(left.stepIndex || 0) - Number(right.stepIndex || 0),
            );

            setTrainMetricPoints(trainPoints);
            setRoundArtifacts(roundArtifactItems);
            void ensureArtifactUrls(roundArtifactItems);

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
        selectStep?.id,
        selectStep?.updatedAt,
        selectStep?.state,
        scoreStep?.id,
        scoreStep?.updatedAt,
        scoreStep?.state,
        ensureArtifactUrls,
    ]);

    useEffect(() => {
        return () => {
            if (metaRefreshTimerRef.current != null) {
                window.clearTimeout(metaRefreshTimerRef.current);
                metaRefreshTimerRef.current = null;
            }
            if (wsRetryTimerRef.current != null) {
                window.clearTimeout(wsRetryTimerRef.current);
                wsRetryTimerRef.current = null;
            }
            if (wsRef.current) {
                wsRef.current.close();
                wsRef.current = null;
            }
        };
    }, []);

    useEffect(() => {
        if (!canManageLoops || !round?.id || !token) {
            eventsRef.current = [];
            setEvents([]);
            setWsConnected(false);
            roundEventCursorRef.current = null;
            wsRetryCountRef.current = 0;
            return;
        }

        let cancelled = false;
        wsClosedRef.current = false;
        wsRetryCountRef.current = 0;
        roundEventCursorRef.current = null;
        eventsRef.current = [];
        setEvents([]);

        const closeSocket = () => {
            if (wsRetryTimerRef.current != null) {
                window.clearTimeout(wsRetryTimerRef.current);
                wsRetryTimerRef.current = null;
            }
            if (wsRef.current) {
                wsRef.current.close();
                wsRef.current = null;
            }
        };

        const applyIncomingEvents = (incoming: RuntimeRoundEvent[]) => {
            if (incoming.length === 0 || cancelled) return;
            const merged = mergeRuntimeRoundEvents(eventsRef.current, incoming, MAX_EVENT_BUFFER);
            eventsRef.current = merged;
            setEvents(merged);

            const metricPoints = incoming.flatMap((item) => extractMetricPointsFromEvent(item));
            if (metricPoints.length > 0) {
                setTrainMetricPoints((prev) => mergeMetricPoints(prev, metricPoints));
            }

            const artifactRows = incoming
                .map((item) => buildArtifactFromRoundEvent(item))
                .filter((item): item is RuntimeRoundArtifact => Boolean(item));
            if (artifactRows.length > 0) {
                setRoundArtifacts((prev) => {
                    const rowMap = new Map<string, RuntimeRoundArtifact>();
                    prev.forEach((item) => rowMap.set(buildArtifactKey(item.stepId, item.name), item));
                    artifactRows.forEach((item) => rowMap.set(buildArtifactKey(item.stepId, item.name), item));
                    return Array.from(rowMap.values()).sort(
                        (left, right) => Number(left.stepIndex || 0) - Number(right.stepIndex || 0),
                    );
                });
                void ensureArtifactUrls(artifactRows);
            }

            const statusRows = incoming.filter((item) => item.eventType === 'status');
            let shouldRefreshRoundMeta = false;
            if (statusRows.length > 0) {
                setSteps((prev) => {
                    if (!prev || prev.length === 0) return prev;
                    const indexMap = new Map(prev.map((item, idx) => [item.id, idx]));
                    const next = [...prev];
                    let changed = false;
                    statusRows.forEach((row) => {
                        const idx = indexMap.get(row.stepId);
                        if (idx == null) return;
                        const current = next[idx];
                        if (!current) return;
                        const payload = row.payload && typeof row.payload === 'object' ? row.payload : {};
                        const normalizedState = normalizeIncomingStepState(payload.status ?? row.status);
                        if (!normalizedState) return;
                        const nextStartedAt = current.startedAt
                            || ([
                                'ready',
                                'dispatching',
                                'syncing_env',
                                'probing_runtime',
                                'binding_device',
                                'running',
                                'retrying',
                            ].includes(normalizedState)
                                ? String(payload.startedAt ?? payload.started_at ?? row.ts)
                                : current.startedAt);
                        const nextEndedAt = isTerminalStepState(normalizedState)
                            ? String(payload.endedAt ?? payload.ended_at ?? row.ts)
                            : current.endedAt;
                        const nextLastError = normalizedState === 'failed'
                            ? (String(payload.reason ?? payload.error ?? current.lastError ?? '').trim() || current.lastError)
                            : current.lastError;
                        if (
                            normalizedState === current.state
                            && nextStartedAt === current.startedAt
                            && nextEndedAt === current.endedAt
                            && nextLastError === current.lastError
                        ) {
                            return;
                        }
                        changed = true;
                        next[idx] = {
                            ...current,
                            state: normalizedState as RuntimeStep['state'],
                            startedAt: nextStartedAt,
                            endedAt: nextEndedAt,
                            lastError: nextLastError,
                        };
                    });
                    if (!changed) return prev;
                    if (next.length > 0 && next.every((item) => isTerminalStepState(item.state))) {
                        shouldRefreshRoundMeta = true;
                    }
                    return next;
                });
            }

            if (shouldRefreshRoundMeta || statusRows.some((row) => {
                const payload = row.payload && typeof row.payload === 'object' ? row.payload : {};
                const state = normalizeIncomingStepState(payload.status ?? row.status);
                return state === 'failed' || state === 'cancelled';
            })) {
                scheduleRoundMetaRefresh();
            }
        };

        const syncRoundEvents = async () => {
            let afterCursor = roundEventCursorRef.current || undefined;
            let hasMore = true;
            let pageCount = 0;
            let nextCursor = roundEventCursorRef.current;
            const incoming: RuntimeRoundEvent[] = [];
            while (hasMore && pageCount < 20) {
                const response = await api.getRoundEvents(round.id, {
                    afterCursor,
                    limit: ROUND_EVENT_SYNC_LIMIT,
                    stages: activeConsoleStages.length > 0 ? activeConsoleStages : undefined,
                });
                const items = (response.items || []).filter((item) => Boolean(item.stepId));
                if (items.length > 0) {
                    incoming.push(...items);
                }
                nextCursor = response.nextAfterCursor ?? nextCursor ?? null;
                hasMore = Boolean(response.hasMore);
                afterCursor = response.nextAfterCursor || undefined;
                pageCount += 1;
            }
            if (cancelled) return;
            roundEventCursorRef.current = nextCursor ?? roundEventCursorRef.current;
            applyIncomingEvents(incoming);
        };

        const scheduleReconnect = () => {
            if (cancelled || wsClosedRef.current) return;
            const nextRetry = wsRetryCountRef.current + 1;
            wsRetryCountRef.current = nextRetry;
            const delay = ROUND_WS_RECONNECT_DELAYS[Math.min(nextRetry - 1, ROUND_WS_RECONNECT_DELAYS.length - 1)];
            wsRetryTimerRef.current = window.setTimeout(async () => {
                wsRetryTimerRef.current = null;
                if (cancelled || wsClosedRef.current) return;
                if (nextRetry >= 3) {
                    try {
                        await syncRoundEvents();
                    } catch {
                        // ignore catch-up failure and keep retrying ws
                    }
                }
                if (!cancelled && !wsClosedRef.current) {
                    connectSocket();
                }
            }, delay);
        };

        const connectSocket = () => {
            if (cancelled || wsClosedRef.current) return;
            closeSocket();
            const ws = new WebSocket(
                buildRoundEventsWsUrl(
                    round.id,
                    token,
                    roundEventCursorRef.current || undefined,
                    activeConsoleStages.length > 0 ? activeConsoleStages : undefined,
                ),
            );
            wsRef.current = ws;
            ws.onopen = () => {
                if (cancelled) return;
                wsRetryCountRef.current = 0;
                setWsConnected(true);
            };
            ws.onclose = () => {
                if (cancelled || wsClosedRef.current) return;
                setWsConnected(false);
                wsRef.current = null;
                scheduleReconnect();
            };
            ws.onerror = () => {
                if (cancelled) return;
                setWsConnected(false);
            };
            ws.onmessage = (messageEvent: MessageEvent<string>) => {
                try {
                    const raw = JSON.parse(messageEvent.data || '{}');
                    const item = normalizeRuntimeRoundEvent(raw);
                    if (!item) return;
                    applyIncomingEvents([item]);
                } catch {
                    // ignore malformed ws payload
                }
            };
        };

        const start = async () => {
            try {
                await syncRoundEvents();
            } catch {
                // ignore initial history sync failure and rely on ws reconnect
            }
            if (!cancelled && !wsClosedRef.current) {
                connectSocket();
            }
        };

        void start();
        return () => {
            cancelled = true;
            wsClosedRef.current = true;
            setWsConnected(false);
            closeSocket();
        };
    }, [canManageLoops, round?.id, token, activeConsoleStages, scheduleRoundMetaRefresh, ensureArtifactUrls]);

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
                        <Button
                            onClick={() => navigate(
                                `/projects/${projectId}/models?roundId=${round.id}`,
                            )}
                        >
                            发布模型
                        </Button>
                        <Button
                            onClick={() => navigate(
                                `/projects/${projectId}/prediction-tasks?targetRoundId=${round.id}&artifactName=best.pt`,
                            )}
                        >
                            预测任务快捷入口
                        </Button>
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
                                <YAxis yAxisId="metric" domain={[0, trainScoreAxisUpperBound]}/>
                                <YAxis yAxisId="loss" orientation="right"/>
                                <Tooltip/>
                                {trainMetricNames.map((name, idx) => (
                                    <Line
                                        key={name}
                                        type="monotone"
                                        dataKey={name}
                                        yAxisId={isLossMetricName(name) ? 'loss' : 'metric'}
                                        dot={false}
                                        stroke={TRAIN_METRIC_COLORS[idx % TRAIN_METRIC_COLORS.length]}
                                        strokeWidth={2}
                                    />
                                ))}
                            </LineChart>
                        </ResponsiveContainer>
                    </div>
                )}
            </Card>

            <Card className="!border-github-border !bg-github-panel" title="制品">
                {roundArtifactRows.length === 0 ? (
                    <Empty description="当前 Round 暂无制品"/>
                ) : (
                    <Table<RoundArtifactTableRow>
                        size="small"
                        rowKey={(row) => row.key}
                        dataSource={roundArtifactRows}
                        pagination={{pageSize: 10, showSizeChanger: false}}
                        columns={[
                            {
                                title: '来源阶段',
                                dataIndex: 'stageLabel',
                                width: 120,
                                render: (_value: unknown, row: RoundArtifactTableRow) => (
                                    <Tag>{row.stageLabel}</Tag>
                                ),
                            },
                            {
                                title: '类别',
                                dataIndex: 'artifactClassLabel',
                                width: 120,
                                render: (_value: unknown, row: RoundArtifactTableRow) => <Tag>{row.artifactClassLabel}</Tag>,
                            },
                            {title: '名称', dataIndex: 'name'},
                            {title: '类型', dataIndex: 'kind', width: 180, render: (value: string) => <Tag>{value}</Tag>},
                            {
                                title: '大小',
                                width: 120,
                                render: (_value: unknown, row: RoundArtifactTableRow) => formatArtifactSize(row.size),
                            },
                            {
                                title: 'Step',
                                width: 100,
                                render: (_value: unknown, row: RoundArtifactTableRow) => `#${row.stepIndex}`,
                            },
                            {
                                title: '时间',
                                width: 180,
                                render: (_value: unknown, row: RoundArtifactTableRow) => formatDateTime(row.createdAt),
                            },
                            {
                                title: '操作',
                                width: 220,
                                render: (_value: unknown, row: RoundArtifactTableRow) => {
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

            <Card className="!border-github-border !bg-github-panel" title="指标总览">
                <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
                    <div>
                        <Text strong>Train 终态</Text>
                        {trainFinalMetricPairs.length === 0 ? (
                            <Empty description="暂无指标"/>
                        ) : (
                            <Descriptions size="small" column={1} className="!mt-2">
                                {trainFinalMetricPairs.map(([key, value]) => (
                                    <Descriptions.Item key={key} label={key}>{formatMetricValue(value)}</Descriptions.Item>
                                ))}
                            </Descriptions>
                        )}
                    </div>
                    <div>
                        <Text strong>Eval(Test) 终态</Text>
                        {evalFinalMetricPairs.length === 0 ? (
                            <Empty description="暂无指标"/>
                        ) : (
                            <Descriptions size="small" column={1} className="!mt-2">
                                {evalFinalMetricPairs.map(([key, value]) => (
                                    <Descriptions.Item key={key} label={key}>{formatMetricValue(value)}</Descriptions.Item>
                                ))}
                            </Descriptions>
                        )}
                    </div>
                    <div>
                        <div className="flex items-center gap-2">
                            <Text strong>Round Final(对外口径)</Text>
                            <Tag color={finalMetricsSource === 'eval' ? 'blue' : (finalMetricsSource === 'train' ? 'green' : 'default')}>
                                {`source: ${FINAL_METRIC_SOURCE_LABEL[finalMetricsSource]}`}
                            </Tag>
                        </div>
                        {finalMetricPairs.length === 0 ? (
                            <Empty description="暂无指标"/>
                        ) : (
                            <Descriptions size="small" column={1} className="!mt-2">
                                {finalMetricPairs.map(([key, value]) => (
                                    <Descriptions.Item key={key} label={key}>{formatMetricValue(value)}</Descriptions.Item>
                                ))}
                            </Descriptions>
                        )}
                    </div>
                </div>
            </Card>

            <RoundConsolePanel
                className="!border-github-border !bg-github-panel"
                title={
                    consoleStage === 'all'
                        ? 'Round 控制台日志 · 全部阶段'
                        : (consoleStep
                            ? `Round 控制台日志 · ${STAGE_LABEL[consoleStage]} (#${consoleStep.stepIndex} ${consoleStep.stepType})`
                            : 'Round 控制台日志')
                }
                wsConnected={wsConnected}
                events={events}
                stageValue={consoleStage}
                stageOptions={consoleStageOptions.map((item) => ({
                    label: String(item.label),
                    value: String(item.value),
                }))}
                onStageChange={(value) => setConsoleStage(value as ConsoleStageFilter)}
                onClearBuffer={handleClearLogs}
                emptyDescription={consoleTargetSteps.length === 0 ? '当前 Round 暂无可用日志阶段' : '暂无命中日志'}
                exportFilePrefix={`round-${round.roundIndex}-${consoleStage}`}
            />

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
                    <Descriptions.Item label="Train 终态">
                        {trainFinalMetricPairs.length === 0
                            ? '-'
                            : trainFinalMetricPairs.map(([key, value]) => (
                                <Text key={key} className="mr-2 block">{`${key}: ${formatMetricValue(value)}`}</Text>
                            ))}
                    </Descriptions.Item>
                    <Descriptions.Item label="Eval(Test) 终态">
                        {evalFinalMetricPairs.length === 0
                            ? '-'
                            : evalFinalMetricPairs.map(([key, value]) => (
                                <Text key={key} className="mr-2 block">{`${key}: ${formatMetricValue(value)}`}</Text>
                            ))}
                    </Descriptions.Item>
                    <Descriptions.Item label="Final Metrics">
                        <Tag color={finalMetricsSource === 'eval' ? 'blue' : (finalMetricsSource === 'train' ? 'green' : 'default')}>
                            {`source: ${FINAL_METRIC_SOURCE_LABEL[finalMetricsSource]}`}
                        </Tag>
                        {finalMetricPairs.length === 0
                            ? <Text className="ml-2">-</Text>
                            : finalMetricPairs.map(([key, value]) => (
                                <Text key={key} className="mr-2 block">{`${key}: ${formatMetricValue(value)}`}</Text>
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
