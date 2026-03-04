import {
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
    samplingStrategy?: string;
    queryBatchSize?: number;
    pluginConfig?: Record<string, any>;
    simulationConfig?: {
        oracleInputMode?: OracleInputMode;
        oracleCommitId?: string;
        oracleCommitIdManual?: string;
        seedRatio?: number;
        stepRatio?: number;
        maxRounds?: number;
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
            seedRatio: clampRatio(values.simulationConfig?.seedRatio, 0.05),
            stepRatio: clampRatio(values.simulationConfig?.stepRatio, 0.05),
            maxRounds: normalizePositiveInt(values.simulationConfig?.maxRounds, 20),
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
