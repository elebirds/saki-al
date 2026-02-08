export type ALLoopStatus = 'draft' | 'running' | 'paused' | 'stopped' | 'completed' | 'failed';

export interface ALLoop {
    id: string;
    projectId: string;
    branchId: string;
    name: string;
    queryStrategy: string;
    modelArch: string;
    globalConfig: Record<string, any>;
    modelRequestConfig: Record<string, any>;
    currentIteration: number;
    isActive: boolean;
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

export type RuntimeJobStatus = 'pending' | 'running' | 'success' | 'failed' | 'cancelled';

export interface RuntimeJob {
    id: string;
    projectId: string;
    loopId: string;
    iteration: number;
    roundIndex: number;
    status: RuntimeJobStatus;
    jobType: string;
    pluginId: string;
    mode: string;
    queryStrategy: string;
    sourceCommitId: string;
    resultCommitId?: string | null;
    assignedExecutorId?: string | null;
    startedAt?: string | null;
    endedAt?: string | null;
    retryCount: number;
    lastError?: string | null;
    metrics: Record<string, any>;
    artifacts: Record<string, any>;
    params: Record<string, any>;
    resources: Record<string, any>;
    strategyParams: Record<string, any>;
    modelId?: string | null;
    createdAt: string;
    updatedAt: string;
}

export interface LoopCreateRequest {
    name: string;
    branchId: string;
    queryStrategy?: string;
    modelArch?: string;
    globalConfig?: Record<string, any>;
    modelRequestConfig?: Record<string, any>;
    isActive?: boolean;
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
    queryStrategy?: string;
    modelArch?: string;
    globalConfig?: Record<string, any>;
    modelRequestConfig?: Record<string, any>;
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
    sourceCommitId: string;
    pluginId: string;
    jobType?: string;
    mode?: string;
    queryStrategy?: string;
    params?: Record<string, any>;
    resources?: Record<string, any>;
    strategyParams?: Record<string, any>;
}

export interface RuntimeJobCommandResponse {
    requestId: string;
    jobId: string;
    status: string;
}

export interface RuntimeJobEvent {
    seq: number;
    ts: string;
    eventType: string;
    payload: Record<string, any>;
}

export interface RuntimeMetricPoint {
    step: number;
    epoch?: number | null;
    metricName: string;
    metricValue: number;
    ts: string;
}

export interface RuntimeTopKCandidate {
    sampleId: string;
    score: number;
    extra: Record<string, any>;
    predictionSnapshot: Record<string, any>;
}

export interface RuntimeArtifact {
    name: string;
    kind: string;
    uri: string;
    meta: Record<string, any>;
}

export interface RuntimeArtifactsResponse {
    jobId: string;
    artifacts: RuntimeArtifact[];
}

export interface LoopRound {
    id: string;
    loopId: string;
    roundIndex: number;
    sourceCommitId: string;
    jobId?: string | null;
    annotationBatchId?: string | null;
    status: 'training' | 'annotation' | 'completed' | 'completed_no_candidates' | 'failed';
    metrics: Record<string, any>;
    selectedCount: number;
    labeledCount: number;
    startedAt?: string | null;
    endedAt?: string | null;
    createdAt: string;
    updatedAt: string;
}

export interface LoopSummary {
    loopId: string;
    status: ALLoopStatus;
    roundsTotal: number;
    roundsCompleted: number;
    selectedTotal: number;
    labeledTotal: number;
    metricsLatest: Record<string, any>;
}

export interface AnnotationBatch {
    id: string;
    projectId: string;
    loopId: string;
    jobId: string;
    roundIndex: number;
    status: 'open' | 'closed';
    totalCount: number;
    annotatedCount: number;
    closedAt?: string | null;
    meta: Record<string, any>;
    createdAt: string;
    updatedAt: string;
}

export interface AnnotationBatchItem {
    id: string;
    batchId: string;
    sampleId: string;
    rank: number;
    score: number;
    reason: Record<string, any>;
    predictionSnapshot: Record<string, any>;
    isAnnotated: boolean;
    annotatedAt?: string | null;
    annotationCommitId?: string | null;
    createdAt: string;
    updatedAt: string;
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
    supportedJobTypes: string[];
    supportedStrategies: string[];
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
    supportedJobTypes: string[];
    supportedStrategies: string[];
    requestConfigSchema: RuntimeRequestConfigSchema;
    defaultRequestConfig: Record<string, any>;
}

export interface RuntimeExecutorRead {
    id: string;
    executorId: string;
    version: string;
    status: string;
    isOnline: boolean;
    currentJobId?: string | null;
    pluginIds: {
        plugins?: RuntimeExecutorPluginCapability[];
        ids?: string[];
    } & Record<string, any>;
    resources: Record<string, any>;
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

export interface JobArtifactDownload {
    jobId: string;
    artifactName: string;
    downloadUrl: string;
    expiresInHours: number;
}
