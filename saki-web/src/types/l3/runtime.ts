export type LoopState = 'draft' | 'running' | 'paused' | 'stopping' | 'stopped' | 'completed' | 'failed';
export type LoopMode = 'active_learning' | 'simulation' | 'manual';
export type LoopStage =
    | 'snapshot_required'
    | 'label_gap_required'
    | 'ready_to_start'
    | 'running_round'
    | 'waiting_round_label'
    | 'ready_to_confirm'
    | 'ready_next_round'
    | 'failed_retryable'
    | 'completed'
    | 'stopped'
    | 'failed';
export type LoopActionKey =
    | 'start'
    | 'pause'
    | 'resume'
    | 'stop'
    | 'confirm'
    | 'start_next_round'
    | 'retry_round'
    | 'snapshot_init'
    | 'snapshot_update'
    | 'selection_adjust'
    | 'read'
    | 'observe'
    | 'view_annotation_gaps'
    | 'annotate';

export type SnapshotUpdateMode = 'init' | 'append_all_to_pool' | 'append_split';
export type SnapshotValPolicy = 'anchor_only' | 'expand_with_batch_val';
export type SnapshotPartition = 'train_seed' | 'train_pool' | 'val_anchor' | 'val_batch' | 'test_anchor' | 'test_batch';

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
    stage?: LoopStage;
    phaseMeta: Record<string, any>;
    stageMeta?: Record<string, any>;
    modelArch: string;
    config: LoopRuntimeConfig;
    activeSnapshotVersionId?: string | null;
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

export type RuntimeRoundState = 'pending' | 'running' | 'completed' | 'cancelled' | 'failed';

export interface RuntimeRound {
    id: string;
    projectId: string;
    loopId: string;
    roundIndex: number;
    attemptIndex: number;
    mode: LoopMode;
    state: RuntimeRoundState;
    awaitingConfirm?: boolean;
    stepCounts: Record<string, number>;
    roundType: string;
    pluginId: string;
    inputCommitId?: string | null;
    outputCommitId?: string | null;
    retryOfRoundId?: string | null;
    retryReason?: string | null;
    assignedExecutorId?: string | null;
    startedAt?: string | null;
    endedAt?: string | null;
    retryCount: number;
    confirmedAt?: string | null;
    confirmedCommitId?: string | null;
    confirmedRevealedCount?: number;
    confirmedSelectedCount?: number;
    confirmedEffectiveMinRequired?: number;
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

export interface RoundSelectionOverrideRead {
    sampleId: string;
    op: 'include' | 'exclude';
    reason?: string | null;
}

export interface RoundSelectionRead {
    roundId: string;
    loopId: string;
    roundIndex: number;
    attemptIndex: number;
    topk: number;
    reviewPoolSize: number;
    autoSelected: RuntimeStepCandidate[];
    scorePool: RuntimeStepCandidate[];
    overrides: RoundSelectionOverrideRead[];
    effectiveSelected: RuntimeStepCandidate[];
    selectedCount: number;
    includeCount: number;
    excludeCount: number;
}

export interface RoundSelectionApplyRequest {
    includeSampleIds?: string[];
    excludeSampleIds?: string[];
    reason?: string;
}

export interface RoundSelectionApplyResponse {
    roundId: string;
    selectedCount: number;
    includeCount: number;
    excludeCount: number;
    effectiveSelected: RuntimeStepCandidate[];
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
    attemptsTotal: number;
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

export interface LoopActionSpec {
    key: LoopActionKey;
    label: string;
    runnable: boolean;
    requiresConfirm: boolean;
    payload: Record<string, any>;
}

export interface LoopActionRequest {
    action?: LoopActionKey;
    force?: boolean;
    decisionToken?: string;
    payload?: Record<string, any>;
}

export interface LoopActionResponse {
    loopId: string;
    executedAction?: LoopActionKey | null;
    commandId?: string | null;
    message: string;
    stage: LoopStage;
    stageMeta: Record<string, any>;
    primaryAction?: LoopActionSpec | null;
    actions: LoopActionSpec[];
    decisionToken: string;
    blockingReasons: string[];
    phase: LoopPhase;
    state: LoopState;
}

export interface SnapshotInitRequest {
    seed?: string;
    trainSeedRatio?: number;
    valRatio?: number;
    testRatio?: number;
    valPolicy?: SnapshotValPolicy;
    sampleIds?: string[];
}

export interface SnapshotUpdateRequest {
    mode?: Exclude<SnapshotUpdateMode, 'init'>;
    seed?: string;
    sampleIds?: string[];
    batchTestRatio?: number;
    batchValRatio?: number;
    valPolicy?: SnapshotValPolicy;
}

export interface SnapshotVersionRead {
    id: string;
    loopId: string;
    versionIndex: number;
    parentVersionId?: string | null;
    updateMode: SnapshotUpdateMode;
    valPolicy: SnapshotValPolicy;
    seed: string;
    ruleJson: Record<string, any>;
    manifestHash: string;
    sampleCount: number;
    createdBy?: string | null;
    createdAt: string;
    updatedAt: string;
}

export interface SnapshotVersionSummaryRead {
    id: string;
    versionIndex: number;
    updateMode: SnapshotUpdateMode;
    valPolicy: SnapshotValPolicy;
    sampleCount: number;
    manifestHash: string;
    createdAt: string;
}

export interface LoopSnapshotRead {
    loopId: string;
    activeSnapshotVersionId?: string | null;
    active?: SnapshotVersionRead | null;
    history: SnapshotVersionSummaryRead[];
    frozenPartitionCounts: Record<string, number>;
    virtualVisibilityCounts: Record<string, number>;
    effectiveSplitCounts: Record<string, number>;
}

export interface SnapshotMutationResponse {
    loopId: string;
    stage: LoopStage;
    activeSnapshotVersionId: string;
    versionIndex: number;
    created: boolean;
    sampleCount: number;
}

export interface LoopStageResponse {
    loopId: string;
    stage: LoopStage;
    stageMeta: Record<string, any>;
    primaryAction?: LoopActionSpec | null;
    actions: LoopActionSpec[];
    decisionToken: string;
    blockingReasons: string[];
}

export interface AnnotationGapBucket {
    partition: SnapshotPartition;
    total: number;
    missingCount: number;
    sampleIds: string[];
}

export interface LoopAnnotationGapsResponse {
    loopId: string;
    commitId?: string | null;
    buckets: AnnotationGapBucket[];
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

export interface RuntimeRequestConfigFieldOption {
    label: string;
    value: string | number | boolean;
    visible?: string; // 可见性表达式
}

export interface RuntimeRequestConfigField {
    key: string;
    label: string;
    type: 'integer' | 'number' | 'string' | 'boolean' | 'select';
    required?: boolean;
    min?: number;
    max?: number;
    options?: RuntimeRequestConfigFieldOption[];
    default?: any;
    // 新增可选字段（用于增强配置表单）
    description?: string;
    group?: string;
    depends_on?: string[];
    visible?: string; // 字段级可见性表达式
    ui?: {
        placeholder?: string;
        step?: number;
        rows?: number;
        min?: number;
        max?: number;
    };
    props?: {
        min?: number;
        max?: number;
        step?: number;
        placeholder?: string;
        rows?: number;
    };
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
