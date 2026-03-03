import {LoopSummary, RuntimeRound} from '../../../types';

export type RoundMetricSource = 'train' | 'eval' | 'final';
export type FinalMetricSource = 'eval' | 'train' | 'other' | 'none';

const METRIC_ORDER = ['map50', 'map50_95', 'precision', 'recall', 'loss'] as const;
const METRIC_ORDER_INDEX = new Map<string, number>(METRIC_ORDER.map((key, idx) => [key, idx]));

const isRecord = (value: unknown): value is Record<string, any> => (
    Boolean(value)
    && typeof value === 'object'
    && !Array.isArray(value)
);

const trimFixedNumber = (value: number, fractionDigits: number): string => {
    const text = value.toFixed(fractionDigits);
    return text
        .replace(/(\.\d*?[1-9])0+$/g, '$1')
        .replace(/\.0+$/g, '');
};

const ensureMetrics = (value: unknown): Record<string, any> => (isRecord(value) ? value : {});

export const normalizeFinalMetricSource = (raw: unknown): FinalMetricSource => {
    const text = String(raw || '').trim().toLowerCase();
    if (text === 'eval' || text === 'train' || text === 'other' || text === 'none') {
        return text;
    }
    return 'none';
};

export const orderMetricEntries = (metrics: Record<string, any> | undefined | null): Array<[string, any]> => {
    return Object.entries(ensureMetrics(metrics)).sort((left, right) => {
        const leftKey = String(left[0] || '');
        const rightKey = String(right[0] || '');
        const leftOrder = METRIC_ORDER_INDEX.has(leftKey) ? Number(METRIC_ORDER_INDEX.get(leftKey)) : 10_000;
        const rightOrder = METRIC_ORDER_INDEX.has(rightKey) ? Number(METRIC_ORDER_INDEX.get(rightKey)) : 10_000;
        if (leftOrder !== rightOrder) return leftOrder - rightOrder;
        return leftKey.localeCompare(rightKey);
    });
};

export const formatMetricValue = (value: unknown): string => {
    if (value == null) return '—';
    if (typeof value === 'number') {
        if (!Number.isFinite(value)) return '—';
        const absValue = Math.abs(value);
        return absValue >= 1
            ? trimFixedNumber(value, 4)
            : trimFixedNumber(value, 6);
    }
    if (typeof value === 'string') {
        const text = value.trim();
        return text || '—';
    }
    if (typeof value === 'boolean') {
        return value ? 'true' : 'false';
    }
    try {
        return JSON.stringify(value);
    } catch {
        return String(value);
    }
};

export const pickPreviewMetric = (metrics: Record<string, any> | undefined | null): string => {
    const entries = orderMetricEntries(metrics);
    if (entries.length === 0) return '—';
    const [key, value] = entries[0];
    return `${key}: ${formatMetricValue(value)}`;
};

export const getMetricBySource = (
    round: RuntimeRound,
    source: RoundMetricSource,
): Record<string, any> => {
    if (source === 'train') return ensureMetrics(round.trainFinalMetrics);
    if (source === 'eval') return ensureMetrics(round.evalFinalMetrics);
    return ensureMetrics(round.finalMetrics);
};

export const getSummaryMetricsBySource = (
    summary: LoopSummary | null | undefined,
    source: RoundMetricSource,
): Record<string, any> => {
    const row = summary || null;
    if (!row) return {};
    if (source === 'train') return ensureMetrics(row.metricsLatestTrain);
    if (source === 'eval') return ensureMetrics(row.metricsLatestEval);
    return ensureMetrics(row.metricsLatest);
};

export const collectMetricKeys = (
    rounds: RuntimeRound[],
    source: RoundMetricSource,
): string[] => {
    const set = new Set<string>();
    (rounds || []).forEach((round) => {
        Object.keys(getMetricBySource(round, source)).forEach((key) => {
            const text = String(key || '').trim();
            if (text) set.add(text);
        });
    });
    return orderMetricEntries(
        Array.from(set).reduce<Record<string, number>>((acc, key) => {
            acc[key] = 1;
            return acc;
        }, {}),
    ).map(([key]) => key);
};
