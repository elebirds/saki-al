export type LoopState = 'draft' | 'running' | 'paused' | 'stopping' | 'stopped' | 'completed' | 'failed';
export type LoopMode = 'active_learning' | 'simulation' | 'manual';

export type LoopPhase =
    | 'al_bootstrap'
    | 'al_train'
    | 'al_score'
    | 'al_select'
    | 'al_wait_user'
    | 'al_eval'
    | 'al_finalize'
    | 'sim_bootstrap'
    | 'sim_train'
    | 'sim_score'
    | 'sim_select'
    | 'sim_activate'
    | 'sim_eval'
    | 'sim_finalize'
    | 'manual_bootstrap'
    | 'manual_train'
    | 'manual_eval'
    | 'manual_export'
    | 'manual_finalize';

export interface LoopSamplingConfig {
    strategy: string;
    topk: number;
    unlabeledPageSize?: number;
    minCandidatesRequired?: number;
}

export interface LoopModeConfig {
    confirmRequired?: boolean;
    oracleCommitId?: string | null;
    seedRatio?: number;
    stepRatio?: number;
    seeds?: number[];
    singleSeed?: number;
    randomBaselineEnabled?: boolean;
    roundCooldownSec?: number;
    singleRound?: boolean;
}

export interface LoopReproducibilityConfig {
    globalSeed?: string;
    splitSeedPolicy?: string;
    trainSeedPolicy?: string;
    samplingSeedPolicy?: string;
    deterministicLevel?: string;
}

export interface LoopExecutionConfig {
    preferredAccelerator?: string;
    allowFallback?: boolean;
    roundResourcesDefault?: Record<string, any>;
    retryMaxAttempts?: number;
}

export interface LoopRuntimeConfig {
    plugin: Record<string, any>;
    sampling?: LoopSamplingConfig;
    mode?: LoopModeConfig;
    reproducibility?: LoopReproducibilityConfig;
    execution?: LoopExecutionConfig;
}

export interface Loop {
    id: string;
    projectId: string;
    branchId: string;
    name: string;
    mode: LoopMode;
    phase: LoopPhase;
    phaseMeta: Record<string, any>;
    modelArch: string;
    config: LoopRuntimeConfig;
    experimentGroupId?: string | null;
    currentIteration: number;
    state: LoopState;
    maxRounds: number;
    queryBatchSize: number;
    minSeedLabeled: number;
    minNewLabelsPerRound: number;
    stopPatienceRounds: number;
    stopMinGain: number;
    autoRegisterModel: boolean;
    lastRoundId?: string | null;
    latestModelId?: string | null;
    lastError?: string | null;
    createdAt: string;
    updatedAt: string;
}

export type RuntimeRoundState = 'pending' | 'running' | 'wait_user' | 'completed' | 'cancelled' | 'failed';

export interface RuntimeRound {
    id: string;
    projectId: string;
    loopId: string;
    roundIndex: number;
    mode: LoopMode;
    state: RuntimeRoundState;
    stepCounts: Record<string, number>;
    roundType: string;
    pluginId: string;
    inputCommitId?: string | null;
    outputCommitId?: string | null;
    assignedExecutorId?: string | null;
    startedAt?: string | null;
    endedAt?: string | null;
    retryCount: number;
    lastError?: string | null;
    finalMetrics: Record<string, any>;
    finalArtifacts: Record<string, any>;
    resolvedParams: Record<string, any>;
    resources: Record<string, any>;
    strategyParams: Record<string, any>;
    modelId?: string | null;
    createdAt: string;
    updatedAt: string;
}

export type RuntimeStepState =
    | 'pending'
    | 'ready'
    | 'dispatching'
    | 'running'
    | 'retrying'
    | 'succeeded'
    | 'failed'
    | 'cancelled'
    | 'skipped';

export type RuntimeStepType =
    | 'train'
    | 'score'
    | 'select'
    | 'activate_samples'
    | 'advance_branch'
    | 'eval'
    | 'upload_artifact'
    | 'export'
    | 'custom';

export type RuntimeStepDispatchKind = 'dispatchable' | 'orchestrator';

export interface RuntimeStep {
    id: string;
    roundId: string;
    stepType: RuntimeStepType;
    dispatchKind: RuntimeStepDispatchKind;
    state: RuntimeStepState;
    roundIndex: number;
    stepIndex: number;
    dependsOnStepIds: string[];
    resolvedParams: Record<string, any>;
    metrics: Record<string, any>;
    artifacts: Record<string, any>;
    inputCommitId?: string | null;
    outputCommitId?: string | null;
    assignedExecutorId?: string | null;
    attempt: number;
    maxAttempts: number;
    startedAt?: string | null;
    endedAt?: string | null;
    lastError?: string | null;
    createdAt: string;
    updatedAt: string;
}

export interface LoopCreateRequest {
    name: string;
    branchId: string;
    mode?: LoopMode;
    modelArch: string;
    config?: LoopRuntimeConfig;
    experimentGroupId?: string;
    state?: LoopState;
}

export interface LoopUpdateRequest {
    name?: string;
    mode?: LoopMode;
    modelArch?: string;
    config?: LoopRuntimeConfig;
    experimentGroupId?: string;
    state?: LoopState;
}

export interface RuntimeRoundCommandResponse {
    requestId: string;
    roundId: string;
    status: string;
}

export interface RuntimeStepCommandResponse {
    requestId: string;
    stepId: string;
    status: string;
}

export interface RuntimeStepEvent {
    seq: number;
    ts: string;
    eventType: string;
    payload: Record<string, any>;
}

export interface RuntimeStepMetricPoint {
    step: number;
    epoch?: number | null;
    metricName: string;
    metricValue: number;
    ts: string;
}

export interface RuntimeStepCandidate {
    sampleId: string;
    rank: number;
    score: number;
    reason: Record<string, any>;
    predictionSnapshot: Record<string, any>;
}

export interface RuntimeStepArtifact {
    name: string;
    kind: string;
    uri: string;
    meta: Record<string, any>;
}

export interface RuntimeStepArtifactsResponse {
    stepId: string;
    artifacts: RuntimeStepArtifact[];
}

export interface StepArtifactDownload {
    stepId: string;
    artifactName: string;
    downloadUrl: string;
    expiresInHours: number;
}

export interface LoopSummary {
    loopId: string;
    state: LoopState;
    phase: LoopPhase;
    roundsTotal: number;
    roundsSucceeded: number;
    stepsTotal: number;
    stepsSucceeded: number;
    metricsLatest: Record<string, any>;
}

export interface SimulationExperimentCreateRequest {
    branchId: string;
    experimentName?: string;
    modelArch: string;
    strategies: string[];
    config?: LoopRuntimeConfig;
    state?: LoopState;
}

export interface SimulationCurvePoint {
    strategy: string;
    roundIndex: number;
    targetRatio: number;
    meanMetric: number;
    stdMetric: number;
}

export interface SimulationStrategySummary {
    strategy: string;
    seeds: number[];
    finalMean: number;
    finalStd: number;
    aulcMean: number;
}

export interface SimulationComparison {
    experimentGroupId: string;
    metricName: string;
    curves: SimulationCurvePoint[];
    strategies: SimulationStrategySummary[];
    baselineStrategy: string;
    deltaVsBaseline: Record<string, number>;
}

export interface SimulationExperimentCreateResponse {
    experimentGroupId: string;
    loops: Loop[];
}

export interface LoopConfirmResponse {
    loopId: string;
    phase: LoopPhase;
    state: LoopState;
}

export interface RoundPredictionCleanupResponse {
    loopId: string;
    roundIndex: number;
    scoreSteps: number;
    candidateRowsDeleted: number;
    eventRowsDeleted: number;
    metricRowsDeleted: number;
}

export interface ModelArtifact {
    name: string;
    kind: string;
    uri: string;
    meta: Record<string, any>;
}

export interface ProjectModel {
    id: string;
    projectId: string;
    roundId?: string | null;
    inputCommitId?: string | null;
    parentModelId?: string | null;
    pluginId: string;
    modelArch: string;
    name: string;
    versionTag: string;
    weightsPath: string;
    status: string;
    metrics: Record<string, any>;
    artifacts: Record<string, any>;
    promotedAt?: string | null;
    createdBy?: string | null;
    createdAt: string;
    updatedAt: string;
}

export interface RuntimeRequestConfigFieldOptionCond {
    annotation_types?: { subset_of: string[] };
    when_field?: Record<string, string>;
}

export interface RuntimeRequestConfigFieldOption {
    label: string;
    value: string | number | boolean;
    cond?: RuntimeRequestConfigFieldOptionCond;
}

export interface RuntimeRequestConfigField {
    key: string;
    label: string;
    type: 'integer' | 'number' | 'string' | 'boolean' | 'select';
    required?: boolean;
    min?: number;
    max?: number;
    options?: RuntimeRequestConfigFieldOption[];
}

export interface RuntimeRequestConfigSchema {
    title?: string;
    fields?: RuntimeRequestConfigField[];
}

export interface RuntimePluginCatalogItem {
    pluginId: string;
    displayName: string;
    version: string;
    supportedStepTypes: string[];
    supportedStrategies: string[];
    supportedAccelerators: ('cpu' | 'cuda' | 'mps')[];
    supportsAutoFallback: boolean;
    requestConfigSchema: RuntimeRequestConfigSchema;
    defaultRequestConfig: Record<string, any>;
    executorsTotal: number;
    executorsOnline: number;
    executorsAvailable: number;
    availabilityRate: number;
    hasConflict: boolean;
    conflictFields: string[];
}

export interface RuntimePluginCatalogResponse {
    items: RuntimePluginCatalogItem[];
}

export interface RuntimeExecutorPluginCapability {
    pluginId: string;
    displayName: string;
    version: string;
    supportedStepTypes: string[];
    supportedStrategies: string[];
    supportedAccelerators: ('cpu' | 'cuda' | 'mps')[];
    supportsAutoFallback: boolean;
    requestConfigSchema: RuntimeRequestConfigSchema;
    defaultRequestConfig: Record<string, any>;
}

export interface RuntimeAcceleratorCapability {
    type: 'cpu' | 'cuda' | 'mps';
    available: boolean;
    deviceCount: number;
    deviceIds: string[];
}

export interface RuntimeExecutorRead {
    id: string;
    executorId: string;
    version: string;
    status: string;
    isOnline: boolean;
    currentStepId?: string | null;
    pluginIds: {
        plugins?: RuntimeExecutorPluginCapability[];
        ids?: string[];
    } & Record<string, any>;
    resources: {
        accelerators?: RuntimeAcceleratorCapability[];
    } & Record<string, any>;
    lastSeenAt?: string | null;
    lastError?: string | null;
    pendingAssignCount: number;
    pendingStopCount: number;
}

export interface RuntimeExecutorSummary {
    totalCount: number;
    onlineCount: number;
    busyCount: number;
    availableCount: number;
    availabilityRate: number;
    pendingAssignCount: number;
    pendingStopCount: number;
    latestHeartbeatAt?: string | null;
}

export interface RuntimeExecutorListResponse {
    summary: RuntimeExecutorSummary;
    items: RuntimeExecutorRead[];
}

export type RuntimeExecutorStatsRange = '30m' | '1h' | '6h' | '24h' | '7d';

export interface RuntimeExecutorStatsPoint {
    ts: string;
    totalCount: number;
    onlineCount: number;
    busyCount: number;
    availableCount: number;
    availabilityRate: number;
    pendingAssignCount: number;
    pendingStopCount: number;
}

export interface RuntimeExecutorStatsResponse {
    range: RuntimeExecutorStatsRange;
    bucketSeconds: number;
    points: RuntimeExecutorStatsPoint[];
}

export interface ModelArtifactDownload {
    modelId: string;
    artifactName: string;
    downloadUrl: string;
    expiresInHours: number;
}
