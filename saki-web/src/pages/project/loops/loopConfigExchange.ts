import {
    DeterministicLevel,
    LoopMode,
    RuntimePluginCatalogItem,
    RuntimeRequestConfigField,
} from '../../../types';
import {buildLoopRuntimeConfig, LoopEditorFormValues} from './loopPayloadBuilder';

type ExchangeVersion = 1;
type ImportFormat = 'v1' | 'legacy_plugin_config';

type SnapshotValPolicy = 'anchor_only' | 'expand_with_batch_val';

type LoopConfigExchangeObject = {
    version?: unknown;
    exportedAt?: unknown;
    name?: unknown;
    branchId?: unknown;
    modelArch?: unknown;
    mode?: unknown;
    globalSeed?: unknown;
    deterministicLevel?: unknown;
    samplingStrategy?: unknown;
    queryBatchSize?: unknown;
    preferredExecutorId?: unknown;
    trainingLabelIds?: unknown;
    negativeSampleRatio?: unknown;
    simulationConfig?: unknown;
    pluginConfig?: unknown;
    [key: string]: unknown;
};

export interface LoopConfigExchangeV1 {
    version: ExchangeVersion;
    exportedAt: string;
    name?: string;
    branchId?: string;
    modelArch: string;
    mode: LoopMode;
    globalSeed: string;
    deterministicLevel: DeterministicLevel;
    samplingStrategy?: string;
    queryBatchSize?: number;
    preferredExecutorId?: string;
    trainingLabelIds?: string[];
    negativeSampleRatio?: number | null;
    simulationConfig?: {
        oracleInputMode?: 'select' | 'manual';
        oracleCommitId?: string;
        oracleCommitIdManual?: string;
        maxRounds?: number;
        snapshotInit?: {
            trainSeedRatio?: number;
            valRatio?: number;
            testRatio?: number;
            valPolicy?: SnapshotValPolicy;
        };
    };
    pluginConfig?: Record<string, unknown>;
}

export interface ImportLoopFormValuesContext {
    plugins: RuntimePluginCatalogItem[];
    currentModelArch?: string;
    allowBranchId: boolean;
}

export interface ImportLoopFormValuesResult {
    values: Partial<LoopEditorFormValues>;
    meta: {
        format: ImportFormat;
        appliedFieldCount: number;
        ignoredFieldCount: number;
        ignoredTopLevelKeys: string[];
        ignoredPluginConfigKeys: string[];
        ignoredByContextKeys: string[];
    };
}

const EXCHANGE_TOP_LEVEL_KEYS = new Set<string>([
    'version',
    'exportedAt',
    'name',
    'branchId',
    'modelArch',
    'mode',
    'globalSeed',
    'deterministicLevel',
    'samplingStrategy',
    'queryBatchSize',
    'preferredExecutorId',
    'trainingLabelIds',
    'negativeSampleRatio',
    'simulationConfig',
    'pluginConfig',
]);

const LOOP_MODES = new Set<LoopMode>(['active_learning', 'simulation', 'manual']);
const DETERMINISTIC_LEVELS = new Set<DeterministicLevel>(['off', 'deterministic', 'strong_deterministic']);

const isRecord = (value: unknown): value is Record<string, unknown> => (
    typeof value === 'object' && value !== null && !Array.isArray(value)
);

const normalizeText = (value: unknown): string => String(value ?? '').trim();

const normalizeMode = (value: unknown, fallback: LoopMode = 'active_learning'): LoopMode => {
    const text = normalizeText(value) as LoopMode;
    return LOOP_MODES.has(text) ? text : fallback;
};

const normalizeDeterministicLevel = (
    value: unknown,
    fallback: DeterministicLevel = 'off',
): DeterministicLevel => {
    const text = normalizeText(value).toLowerCase() as DeterministicLevel;
    return DETERMINISTIC_LEVELS.has(text) ? text : fallback;
};

const normalizePositiveInt = (value: unknown, fallback: number): number => {
    const parsed = Number(value);
    if (!Number.isFinite(parsed)) return fallback;
    return Math.max(1, Math.trunc(parsed));
};

const normalizeNonNegativeNumber = (value: unknown, fallback: number): number => {
    const parsed = Number(value);
    if (!Number.isFinite(parsed)) return fallback;
    return Math.max(0, parsed);
};

const clampRatio = (value: unknown, fallback: number): number => {
    const parsed = Number(value);
    if (!Number.isFinite(parsed)) return fallback;
    return Math.min(1, Math.max(0, parsed));
};

const normalizeSnapshotValPolicy = (value: unknown): SnapshotValPolicy => {
    const text = normalizeText(value).toLowerCase();
    return text === 'expand_with_batch_val' ? 'expand_with_batch_val' : 'anchor_only';
};

const toStringArray = (value: unknown): string[] => {
    if (!Array.isArray(value)) return [];
    const dedupe = new Set<string>();
    for (const item of value) {
        const text = normalizeText(item);
        if (text) dedupe.add(text);
    }
    return Array.from(dedupe);
};

const getPluginById = (
    plugins: RuntimePluginCatalogItem[],
    pluginId: string,
): RuntimePluginCatalogItem | undefined => (
    plugins.find((item) => item.pluginId === pluginId)
);

const coerceByOptions = (
    rawValue: unknown,
    options: RuntimeRequestConfigField['options'],
): unknown => {
    if (!Array.isArray(options) || options.length === 0) {
        return rawValue;
    }
    const exact = options.find((option) => option.value === rawValue);
    if (exact) {
        return exact.value;
    }
    const normalizedRaw = normalizeText(rawValue).toLowerCase();
    if (!normalizedRaw) {
        return rawValue;
    }
    const loose = options.find((option) => normalizeText(option.value).toLowerCase() === normalizedRaw);
    return loose ? loose.value : rawValue;
};

const normalizePluginFieldValue = (
    field: RuntimeRequestConfigField,
    value: unknown,
): unknown => {
    switch (field.type) {
    case 'boolean':
        return Boolean(value);
    case 'integer': {
        const parsed = Number(value);
        return Number.isFinite(parsed) ? Math.trunc(parsed) : Number(field.default ?? 0);
    }
    case 'number': {
        const parsed = Number(value);
        return Number.isFinite(parsed) ? parsed : Number(field.default ?? 0);
    }
    case 'multi_select': {
        const source = Array.isArray(value)
            ? value
            : (value === undefined || value === null || value === '' ? [] : [value]);
        const dedupe = new Set<string>();
        const result: Array<string | number | boolean> = [];
        for (const item of source) {
            if (item === undefined || item === null) {
                continue;
            }
            const coerced = coerceByOptions(item, field.options) as string | number | boolean;
            const dedupeKey = `${typeof coerced}:${String(coerced).toLowerCase()}`;
            if (dedupe.has(dedupeKey)) {
                continue;
            }
            dedupe.add(dedupeKey);
            result.push(coerced);
        }
        return result;
    }
    case 'integer_array': {
        const source = Array.isArray(value)
            ? value
            : (typeof value === 'string' ? value.split(',') : [value]);
        const dedupe = new Set<number>();
        const result: string[] = [];
        for (const item of source) {
            const parsed = Number(String(item ?? '').trim());
            if (!Number.isInteger(parsed) || dedupe.has(parsed)) {
                continue;
            }
            dedupe.add(parsed);
            result.push(String(parsed));
        }
        return result;
    }
    case 'select': {
        if (value === undefined || value === null || value === '') {
            return undefined;
        }
        return coerceByOptions(value, field.options);
    }
    case 'string':
    case 'textarea':
        return value === undefined || value === null ? '' : String(value);
    default:
        return value;
    }
};

const normalizePluginConfig = (
    rawPluginConfig: unknown,
    plugin: RuntimePluginCatalogItem | undefined,
): {
    values: Record<string, any>;
    ignoredKeys: string[];
    appliedCount: number;
} => {
    if (!isRecord(rawPluginConfig)) {
        return {values: {}, ignoredKeys: [], appliedCount: 0};
    }
    const fields = plugin?.requestConfigSchema?.fields || [];
    const fieldMap = new Map<string, RuntimeRequestConfigField>();
    for (const field of fields) {
        const key = normalizeText(field.key);
        if (key) {
            fieldMap.set(key, field);
        }
    }

    const values: Record<string, any> = {};
    const ignoredKeys: string[] = [];
    for (const [rawKey, rawValue] of Object.entries(rawPluginConfig)) {
        const key = normalizeText(rawKey);
        if (!key) {
            continue;
        }
        const schemaField = fieldMap.get(key);
        if (!schemaField) {
            ignoredKeys.push(key);
            continue;
        }
        values[key] = normalizePluginFieldValue(schemaField, rawValue);
    }

    return {
        values,
        ignoredKeys,
        appliedCount: Object.keys(values).length,
    };
};

const normalizeSimulationConfig = (
    value: unknown,
    fallback?: LoopConfigExchangeV1['simulationConfig'],
): LoopConfigExchangeV1['simulationConfig'] | undefined => {
    const source = isRecord(value) ? value : {};
    const hasSource = Object.keys(source).length > 0 || Boolean(fallback);
    if (!hasSource) {
        return undefined;
    }

    const snapshotSource = isRecord(source.snapshotInit) ? source.snapshotInit : {};
    return {
        oracleInputMode: normalizeText(source.oracleInputMode || fallback?.oracleInputMode) === 'manual' ? 'manual' : 'select',
        oracleCommitId: normalizeText(source.oracleCommitId || fallback?.oracleCommitId),
        oracleCommitIdManual: normalizeText(source.oracleCommitIdManual || fallback?.oracleCommitIdManual),
        maxRounds: normalizePositiveInt(source.maxRounds ?? fallback?.maxRounds, 20),
        snapshotInit: {
            trainSeedRatio: clampRatio(
                snapshotSource.trainSeedRatio ?? fallback?.snapshotInit?.trainSeedRatio,
                0.05,
            ),
            valRatio: clampRatio(
                snapshotSource.valRatio ?? fallback?.snapshotInit?.valRatio,
                0.1,
            ),
            testRatio: clampRatio(
                snapshotSource.testRatio ?? fallback?.snapshotInit?.testRatio,
                0.1,
            ),
            valPolicy: normalizeSnapshotValPolicy(
                snapshotSource.valPolicy ?? fallback?.snapshotInit?.valPolicy,
            ),
        },
    };
};

const compactTopLevel = <T extends Record<string, unknown>>(input: T): T => {
    const output: Record<string, unknown> = {};
    for (const [key, value] of Object.entries(input)) {
        if (value === undefined) {
            continue;
        }
        output[key] = value;
    }
    return output as T;
};

const parseRawObject = (raw: string): LoopConfigExchangeObject => {
    const text = String(raw || '').trim();
    if (!text) {
        throw new Error('empty_json');
    }
    let parsed: unknown;
    try {
        parsed = JSON.parse(text);
    } catch {
        throw new Error('invalid_json');
    }
    if (!isRecord(parsed)) {
        throw new Error('invalid_root_type');
    }
    return parsed as LoopConfigExchangeObject;
};

const toLegacyV1 = (
    rawObject: LoopConfigExchangeObject,
    currentModelArch: string,
): LoopConfigExchangeObject => ({
    version: 1,
    modelArch: currentModelArch,
    pluginConfig: rawObject.pluginConfig,
});

export const exportLoopFormValues = (
    values: LoopEditorFormValues,
    plugin: RuntimePluginCatalogItem | undefined,
): string => {
    const runtimeConfig = buildLoopRuntimeConfig(values, plugin);
    const mode = normalizeMode(values.mode);
    const simulationConfig = normalizeSimulationConfig(values.simulationConfig, {
        oracleCommitId: normalizeText(runtimeConfig.mode?.oracleCommitId),
        maxRounds: runtimeConfig.mode?.maxRounds,
        snapshotInit: {
            trainSeedRatio: runtimeConfig.mode?.snapshotInit?.trainSeedRatio,
            valRatio: runtimeConfig.mode?.snapshotInit?.valRatio,
            testRatio: runtimeConfig.mode?.snapshotInit?.testRatio,
            valPolicy: runtimeConfig.mode?.snapshotInit?.valPolicy,
        },
    });

    const payload: LoopConfigExchangeV1 = compactTopLevel({
        version: 1 as const,
        exportedAt: new Date().toISOString(),
        name: normalizeText(values.name) || undefined,
        branchId: normalizeText(values.branchId) || undefined,
        modelArch: normalizeText(values.modelArch),
        mode,
        globalSeed: normalizeText(runtimeConfig.reproducibility.globalSeed),
        deterministicLevel: normalizeDeterministicLevel(runtimeConfig.reproducibility.deterministicLevel),
        samplingStrategy: normalizeText(values.samplingStrategy) || undefined,
        queryBatchSize: values.queryBatchSize == null
            ? undefined
            : normalizePositiveInt(values.queryBatchSize, 200),
        preferredExecutorId: normalizeText(values.preferredExecutorId) || undefined,
        trainingLabelIds: toStringArray(values.trainingLabelIds),
        negativeSampleRatio: values.negativeSampleRatio === null
            ? null
            : (values.negativeSampleRatio == null
                ? undefined
                : normalizeNonNegativeNumber(values.negativeSampleRatio, 0)),
        simulationConfig,
        pluginConfig: (runtimeConfig.plugin || {}) as Record<string, unknown>,
    });
    return JSON.stringify(payload, null, 2);
};

export const importLoopFormValues = (
    raw: string,
    context: ImportLoopFormValuesContext,
): ImportLoopFormValuesResult => {
    const rawObject = parseRawObject(raw);

    const currentModelArch = normalizeText(context.currentModelArch);
    const isLegacyPluginConfigOnly = (
        rawObject.version === undefined
        && isRecord(rawObject.pluginConfig)
    );

    const normalizedRaw = isLegacyPluginConfigOnly
        ? toLegacyV1(rawObject, currentModelArch)
        : rawObject;

    const format: ImportFormat = isLegacyPluginConfigOnly ? 'legacy_plugin_config' : 'v1';
    const version = Number(normalizedRaw.version);
    if (version !== 1) {
        throw new Error('unsupported_version');
    }

    const ignoredTopLevelKeys = Object.keys(rawObject)
        .filter((key) => !EXCHANGE_TOP_LEVEL_KEYS.has(key));
    const ignoredByContextKeys: string[] = [];

    const hasModelArchInInput = normalizeText(rawObject.modelArch).length > 0;
    const targetModelArch = normalizeText(normalizedRaw.modelArch) || currentModelArch;
    if (!targetModelArch) {
        throw new Error('missing_model_arch');
    }
    const targetPlugin = getPluginById(context.plugins, targetModelArch);
    if (!targetPlugin) {
        throw new Error(`unknown_model_arch:${targetModelArch}`);
    }

    const nextValues: Partial<LoopEditorFormValues> = {};
    let appliedTopLevelCount = 0;

    if (hasModelArchInInput) {
        nextValues.modelArch = targetModelArch;
        appliedTopLevelCount += 1;
    }

    if (normalizedRaw.name !== undefined) {
        nextValues.name = normalizeText(normalizedRaw.name);
        appliedTopLevelCount += 1;
    }

    if (normalizedRaw.branchId !== undefined) {
        if (context.allowBranchId) {
            nextValues.branchId = normalizeText(normalizedRaw.branchId);
            appliedTopLevelCount += 1;
        } else {
            ignoredByContextKeys.push('branchId');
        }
    }

    if (normalizedRaw.mode !== undefined) {
        nextValues.mode = normalizeMode(normalizedRaw.mode);
        appliedTopLevelCount += 1;
    }

    if (normalizedRaw.globalSeed !== undefined) {
        nextValues.globalSeed = normalizeText(normalizedRaw.globalSeed);
        appliedTopLevelCount += 1;
    }

    if (normalizedRaw.deterministicLevel !== undefined) {
        nextValues.deterministicLevel = normalizeDeterministicLevel(normalizedRaw.deterministicLevel);
        appliedTopLevelCount += 1;
    }

    if (normalizedRaw.samplingStrategy !== undefined) {
        nextValues.samplingStrategy = normalizeText(normalizedRaw.samplingStrategy);
        appliedTopLevelCount += 1;
    }

    if (normalizedRaw.queryBatchSize !== undefined) {
        nextValues.queryBatchSize = normalizePositiveInt(normalizedRaw.queryBatchSize, 200);
        appliedTopLevelCount += 1;
    }

    if (normalizedRaw.preferredExecutorId !== undefined) {
        const preferredExecutorId = normalizeText(normalizedRaw.preferredExecutorId);
        nextValues.preferredExecutorId = preferredExecutorId || undefined;
        appliedTopLevelCount += 1;
    }

    if (normalizedRaw.trainingLabelIds !== undefined) {
        nextValues.trainingLabelIds = toStringArray(normalizedRaw.trainingLabelIds);
        appliedTopLevelCount += 1;
    }

    if (normalizedRaw.negativeSampleRatio !== undefined) {
        nextValues.negativeSampleRatio = normalizedRaw.negativeSampleRatio === null
            ? null
            : normalizeNonNegativeNumber(normalizedRaw.negativeSampleRatio, 0);
        appliedTopLevelCount += 1;
    }

    if (normalizedRaw.simulationConfig !== undefined) {
        const normalizedSimulation = normalizeSimulationConfig(normalizedRaw.simulationConfig);
        if (normalizedSimulation) {
            nextValues.simulationConfig = normalizedSimulation;
            appliedTopLevelCount += 1;
        }
    }

    let pluginAppliedCount = 0;
    const pluginIgnoredKeys: string[] = [];
    if (normalizedRaw.pluginConfig !== undefined) {
        const normalizedPluginConfig = normalizePluginConfig(normalizedRaw.pluginConfig, targetPlugin);
        nextValues.pluginConfig = normalizedPluginConfig.values;
        pluginAppliedCount = normalizedPluginConfig.appliedCount;
        pluginIgnoredKeys.push(...normalizedPluginConfig.ignoredKeys);
        appliedTopLevelCount += 1;
    }

    const ignoredFieldCount = ignoredTopLevelKeys.length + ignoredByContextKeys.length + pluginIgnoredKeys.length;
    return {
        values: nextValues,
        meta: {
            format,
            appliedFieldCount: appliedTopLevelCount + pluginAppliedCount,
            ignoredFieldCount,
            ignoredTopLevelKeys,
            ignoredPluginConfigKeys: pluginIgnoredKeys,
            ignoredByContextKeys,
        },
    };
};
