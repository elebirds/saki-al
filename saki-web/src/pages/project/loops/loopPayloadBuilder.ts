import {
    DeterministicLevel,
    LoopCreateRequest,
    LoopMode,
    LoopUpdateRequest,
    RuntimePluginCatalogItem,
    LoopRuntimeConfig,
} from '../../../types';

export const RANDOM_BASELINE_STRATEGY = 'random_baseline';

export type OracleInputMode = 'select' | 'manual';

export type LoopEditorFormValues = {
    name: string;
    branchId?: string;
    mode?: LoopMode;
    modelArch: string;
    globalSeed: string;
    deterministicLevel?: DeterministicLevel;
    samplingStrategy?: string;
    queryBatchSize?: number;
    pluginConfig?: Record<string, any>;
    simulationConfig?: {
        oracleInputMode?: OracleInputMode;
        oracleCommitId?: string;
        oracleCommitIdManual?: string;
        maxRounds?: number;
        snapshotInit?: {
            trainSeedRatio?: number;
            valRatio?: number;
            testRatio?: number;
            valPolicy?: string;
        };
    };
};

const clampRatio = (value: unknown, fallback: number): number => {
    const parsed = Number(value);
    if (!Number.isFinite(parsed)) return fallback;
    return Math.min(1, Math.max(0, parsed));
};

const normalizePositiveInt = (value: unknown, fallback: number): number => {
    const parsed = Number(value);
    if (!Number.isFinite(parsed)) return fallback;
    return Math.max(1, Math.trunc(parsed));
};

const normalizeText = (value: unknown): string => String(value ?? '').trim();
const normalizeDeterministicLevel = (value: unknown): DeterministicLevel => {
    const text = normalizeText(value).toLowerCase();
    if (text === 'deterministic') return 'deterministic';
    if (text === 'strong_deterministic') return 'strong_deterministic';
    return 'off';
};
const normalizeSnapshotValPolicy = (value: unknown): 'anchor_only' | 'expand_with_batch_val' => {
    const text = normalizeText(value).toLowerCase();
    if (text === 'expand_with_batch_val') return 'expand_with_batch_val';
    return 'anchor_only';
};

export const pickDefaultSamplingStrategy = (
    plugin: RuntimePluginCatalogItem | undefined,
): string => plugin?.supportedStrategies?.[0] || RANDOM_BASELINE_STRATEGY;

export const mergePluginConfigWithDefaults = (
    plugin: RuntimePluginCatalogItem | undefined,
    pluginConfig: Record<string, any> | undefined,
): Record<string, any> => ({
    ...(plugin?.defaultRequestConfig || {}),
    ...(pluginConfig || {}),
});

export const resolveOracleCommitId = (
    simulationConfig: LoopEditorFormValues['simulationConfig'] | undefined,
): string => {
    const mode = simulationConfig?.oracleInputMode || 'select';
    if (mode === 'manual') {
        return normalizeText(simulationConfig?.oracleCommitIdManual);
    }
    return normalizeText(simulationConfig?.oracleCommitId);
};

export const buildLoopRuntimeConfig = (
    values: LoopEditorFormValues,
    plugin: RuntimePluginCatalogItem | undefined,
): LoopRuntimeConfig => {
    const mode = values.mode || 'active_learning';
    const config: LoopRuntimeConfig = {
        plugin: mergePluginConfigWithDefaults(plugin, values.pluginConfig),
        reproducibility: {
            globalSeed: normalizeText(values.globalSeed),
            deterministicLevel: normalizeDeterministicLevel(values.deterministicLevel),
        },
    };

    if (mode !== 'manual') {
        config.sampling = {
            strategy: normalizeText(values.samplingStrategy) || pickDefaultSamplingStrategy(plugin),
            topk: normalizePositiveInt(values.queryBatchSize, 200),
        };
    }

    if (mode === 'simulation') {
        config.mode = {
            oracleCommitId: resolveOracleCommitId(values.simulationConfig),
            maxRounds: normalizePositiveInt(values.simulationConfig?.maxRounds, 20),
            snapshotInit: {
                trainSeedRatio: clampRatio(values.simulationConfig?.snapshotInit?.trainSeedRatio, 0.05),
                valRatio: clampRatio(values.simulationConfig?.snapshotInit?.valRatio, 0.1),
                testRatio: clampRatio(values.simulationConfig?.snapshotInit?.testRatio, 0.1),
                valPolicy: normalizeSnapshotValPolicy(values.simulationConfig?.snapshotInit?.valPolicy),
            },
        };
    }

    return config;
};

export const buildLoopCreatePayload = (
    values: LoopEditorFormValues,
    plugin: RuntimePluginCatalogItem | undefined,
): LoopCreateRequest => ({
    name: normalizeText(values.name),
    branchId: normalizeText(values.branchId),
    mode: values.mode || 'active_learning',
    modelArch: normalizeText(values.modelArch),
    config: buildLoopRuntimeConfig(values, plugin),
});

export const buildLoopUpdatePayload = (
    values: LoopEditorFormValues,
    plugin: RuntimePluginCatalogItem | undefined,
): LoopUpdateRequest => ({
    name: normalizeText(values.name),
    mode: values.mode || 'active_learning',
    modelArch: normalizeText(values.modelArch),
    config: buildLoopRuntimeConfig(values, plugin),
});
