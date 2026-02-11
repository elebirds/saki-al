export type ALLoopStatus = 'draft' | 'running' | 'paused' | 'stopped' | 'completed' | 'failed';
export type ALLoopMode = 'active_learning' | 'simulation' | 'manual';

export type LoopPhase =
    | 'al_bootstrap'
    | 'al_train'
    | 'al_score'
    | 'al_wait_annotation'
    | 'al_merge'
    | 'al_eval'
    | 'sim_bootstrap'
    | 'sim_train'
    | 'sim_score'
    | 'sim_auto_label'
    | 'sim_eval'
    | 'manual_idle'
    | 'manual_task_running'
    | 'manual_wait_confirm'
    | 'manual_finalize';

export interface LoopSimulationConfig {
    oracleCommitId?: string | null;
    seedRatio: number;
    stepRatio: number;
    maxRounds: number;
    randomBaselineEnabled?: boolean;
    seeds: number[];
}

export interface ALLoop {
    id: string;
    projectId: string;
    branchId: string;
    name: string;
    mode: ALLoopMode;
    phase: LoopPhase;
    phaseMeta: Record<string, any>;
    queryStrategy: string;
    modelArch: string;
    globalConfig: Record<string, any>;
    modelRequestConfig: Record<string, any>;
    simulationConfig: LoopSimulationConfig;
    experimentGroupId?: string | null;
    currentIteration: number;
    status: ALLoopStatus;
    maxRounds: number;
    queryBatchSize: number;
    minSeedLabeled: number;
    minNewLabelsPerRound: number;
    stopPatienceRounds: number;
    stopMinGain: number;
    autoRegisterModel: boolean;
    lastJobId?: string | null;
    latestModelId?: string | null;
    lastError?: string | null;
    createdAt: string;
    updatedAt: string;
}

export type RuntimeJobStatus =
    | 'job_pending'
    | 'job_running'
    | 'job_partial_failed'
    | 'job_failed'
    | 'job_succeeded'
    | 'job_cancelled';

export interface RuntimeJob {
    id: string;
    projectId: string;
    loopId: string;
    roundIndex: number;
    mode: ALLoopMode;
    summaryStatus: RuntimeJobStatus;
    taskCounts: Record<string, number>;
    jobType: string;
    pluginId: string;
    queryStrategy: string;
    sourceCommitId?: string | null;
    resultCommitId?: string | null;
    assignedExecutorId?: string | null;
    startedAt?: string | null;
    endedAt?: string | null;
    retryCount: number;
    lastError?: string | null;
    finalMetrics: Record<string, any>;
    finalArtifacts: Record<string, any>;
    params: Record<string, any>;
    resources: Record<string, any>;
    strategyParams: Record<string, any>;
    modelId?: string | null;
    createdAt: string;
    updatedAt: string;
}

export type RuntimeTaskStatus =
    | 'pending'
    | 'dispatching'
    | 'running'
    | 'retrying'
    | 'succeeded'
    | 'failed'
    | 'cancelled'
    | 'skipped';

export type RuntimeTaskType =
    | 'train'
    | 'score'
    | 'select'
    | 'auto_label'
    | 'wait_annotation'
    | 'merge'
    | 'eval'
    | 'upload_artifact'
    | 'manual_review';

export interface RuntimeJobTask {
    id: string;
    jobId: string;
    taskType: RuntimeTaskType;
    status: RuntimeTaskStatus;
    roundIndex: number;
    taskIndex: number;
    dependsOn: string[];
    params: Record<string, any>;
    metrics: Record<string, any>;
    artifacts: Record<string, any>;
    sourceCommitId?: string | null;
    resultCommitId?: string | null;
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
    mode?: ALLoopMode;
    queryStrategy: string;
    modelArch: string;
    globalConfig?: Record<string, any>;
    modelRequestConfig?: Record<string, any>;
    simulationConfig?: LoopSimulationConfig;
    experimentGroupId?: string;
    status?: ALLoopStatus;
    maxRounds?: number;
    queryBatchSize?: number;
    minSeedLabeled?: number;
    minNewLabelsPerRound?: number;
    stopPatienceRounds?: number;
    stopMinGain?: number;
    autoRegisterModel?: boolean;
}

export interface LoopUpdateRequest {
    name?: string;
    mode?: ALLoopMode;
    queryStrategy?: string;
    modelArch?: string;
    globalConfig?: Record<string, any>;
    modelRequestConfig?: Record<string, any>;
    simulationConfig?: LoopSimulationConfig;
    experimentGroupId?: string;
    maxRounds?: number;
    queryBatchSize?: number;
    minSeedLabeled?: number;
    minNewLabelsPerRound?: number;
    stopPatienceRounds?: number;
    stopMinGain?: number;
    autoRegisterModel?: boolean;
}

export interface RuntimeJobCreateRequest {
    projectId: string;
    sourceCommitId?: string;
    pluginId: string;
    jobType?: string;
    mode?: ALLoopMode;
    queryStrategy: string;
    params?: Record<string, any>;
    resources?: Record<string, any>;
    strategyParams?: Record<string, any>;
}

export interface RuntimeJobCommandResponse {
    requestId: string;
    jobId: string;
    status: string;
}

export interface RuntimeTaskCommandResponse {
    requestId: string;
    taskId: string;
    status: string;
}

export interface RuntimeTaskEvent {
    seq: number;
    ts: string;
    eventType: string;
    payload: Record<string, any>;
}

export interface RuntimeTaskMetricPoint {
    step: number;
    epoch?: number | null;
    metricName: string;
    metricValue: number;
    ts: string;
}

export interface RuntimeTaskCandidate {
    sampleId: string;
    rank: number;
    score: number;
    reason: Record<string, any>;
    predictionSnapshot: Record<string, any>;
}

export interface RuntimeTaskArtifact {
    name: string;
    kind: string;
    uri: string;
    meta: Record<string, any>;
}

export interface RuntimeTaskArtifactsResponse {
    taskId: string;
    artifacts: RuntimeTaskArtifact[];
}

export interface TaskArtifactDownload {
    taskId: string;
    artifactName: string;
    downloadUrl: string;
    expiresInHours: number;
}

export interface LoopSummary {
    loopId: string;
    status: ALLoopStatus;
    phase: LoopPhase;
    jobsTotal: number;
    jobsSucceeded: number;
    tasksTotal: number;
    tasksSucceeded: number;
    metricsLatest: Record<string, any>;
}

export interface SimulationExperimentCreateRequest {
    branchId: string;
    experimentName?: string;
    modelArch: string;
    strategies: string[];
    globalConfig?: Record<string, any>;
    modelRequestConfig?: Record<string, any>;
    simulationConfig: LoopSimulationConfig;
    status?: ALLoopStatus;
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
    loops: ALLoop[];
}

export interface LoopConfirmResponse {
    loopId: string;
    phase: LoopPhase;
    status: ALLoopStatus;
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
    jobId?: string | null;
    sourceCommitId?: string | null;
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

export interface RuntimeRequestConfigField {
    key: string;
    label: string;
    type: 'integer' | 'number' | 'string' | 'boolean' | 'select';
    required?: boolean;
    min?: number;
    max?: number;
    options?: Array<{ label: string; value: string | number | boolean }>;
}

export interface RuntimeRequestConfigSchema {
    title?: string;
    fields?: RuntimeRequestConfigField[];
}

export interface RuntimePluginCatalogItem {
    pluginId: string;
    displayName: string;
    version: string;
    supportedTaskTypes: string[];
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
    supportedTaskTypes: string[];
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
    currentTaskId?: string | null;
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
