import {
    RuntimeRoundArtifact,
    RuntimeRoundEvent,
    RuntimeStep,
    RuntimeTaskMetricPoint,
} from '../../../../types';
import {computeDurationMs} from '../runtimeTime';
import {
    LOSS_METRIC_NAME_RE,
    MODE_STAGE_ORDER,
    STAGE_LABEL,
    TERMINAL_STEP_STATES,
} from './constants';
import {RoundStageKey, RoundStageSnapshot} from './types';

export const resolveModeStageOrder = (mode?: string | null): RoundStageKey[] => {
    const key = String(mode || '');
    if (MODE_STAGE_ORDER[key]) return MODE_STAGE_ORDER[key];
    return ['train', 'eval', 'score', 'select', 'custom'];
};

const normalizeStepTypeText = (stepType: string): string => String(stepType || '').trim().toLowerCase();

export const mapStepTypeToStage = (stepType: string): RoundStageKey => {
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

export const buildArtifactKey = (ownerId: string, artifactName: string): string => `${ownerId}:${artifactName}`;

export const formatArtifactSize = (sizeRaw: unknown): string => {
    const size = Number(sizeRaw || 0);
    if (!Number.isFinite(size) || size <= 0) return '-';
    if (size >= 1024 * 1024) return `${(size / 1024 / 1024).toFixed(2)} MB`;
    return `${(size / 1024).toFixed(1)} KB`;
};

export const isLossMetricName = (metricName: string): boolean => LOSS_METRIC_NAME_RE.test(String(metricName || ''));

export const extractMetricPointsFromEvent = (event: RuntimeRoundEvent): RuntimeTaskMetricPoint[] => {
    if (event.eventType !== 'metric') return [];
    if (event.stage !== 'train') return [];
    const payload = event.payload && typeof event.payload === 'object' ? event.payload : {};
    const points: RuntimeTaskMetricPoint[] = [];
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

export const mergeMetricPoints = (
    previous: RuntimeTaskMetricPoint[],
    incoming: RuntimeTaskMetricPoint[],
): RuntimeTaskMetricPoint[] => {
    if (incoming.length === 0) return previous;
    const merged = new Map<string, RuntimeTaskMetricPoint>();
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

export const normalizeIncomingStepState = (raw: unknown): RuntimeStep['state'] | null => {
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
        return state as RuntimeStep['state'];
    }
    return null;
};

export const isTerminalStepState = (state?: string | null): boolean => TERMINAL_STEP_STATES.has(String(state || '').toLowerCase());

const deriveArtifactClass = (stage: RoundStageKey, kindRaw: string): string => {
    const kind = String(kindRaw || '').toLowerCase();
    if (kind.includes('model')) return 'model_artifact';
    if (kind.includes('eval')) return 'eval_artifact';
    if (kind.includes('selection') || stage === 'select') return 'selection_artifact';
    if (kind.includes('predict')) return 'prediction_artifact';
    return 'generic_artifact';
};

export const buildArtifactFromRoundEvent = (
    event: RuntimeRoundEvent,
    options?: {
        stepId?: string;
        stepIndex?: number;
    },
): RuntimeRoundArtifact | null => {
    if (event.eventType !== 'artifact') return null;
    const payload = event.payload && typeof event.payload === 'object' ? event.payload : {};
    const name = String(payload.name || '').trim();
    if (!name) return null;
    const kind = String(payload.kind || 'artifact').trim() || 'artifact';
    const uri = String(payload.uri || '').trim();
    const sizeRaw = payload.size ?? (payload.meta && typeof payload.meta === 'object' ? (payload.meta as Record<string, any>).size : null);
    const sizeValue = Number(sizeRaw);
    const taskId = String(event.taskId || '').trim();
    if (!taskId) return null;
    const stepId = String(options?.stepId || '').trim();
    const stepIndex = Number(options?.stepIndex ?? event.taskIndex ?? 0);
    return {
        stepId,
        taskId,
        stepIndex: Number.isFinite(stepIndex) ? stepIndex : 0,
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

export const getStepFlowStatus = (state: string): 'wait' | 'process' | 'finish' | 'error' => {
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

export const buildStageSnapshots = (steps: RuntimeStep[], nowMs: number): Record<RoundStageKey, RoundStageSnapshot> => {
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

export const pickTimelineCurrentStep = (steps: RuntimeStep[]): RuntimeStep | null => {
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
