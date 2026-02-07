export interface ALLoop {
    id: string;
    projectId: string;
    branchId: string;
    name: string;
    queryStrategy: string;
    modelArch: string;
    globalConfig: Record<string, any>;
    currentIteration: number;
    isActive: boolean;
    createdAt: string;
    updatedAt: string;
}

export type RuntimeJobStatus = 'pending' | 'running' | 'success' | 'failed' | 'cancelled';

export interface RuntimeJob {
    id: string;
    projectId: string;
    loopId: string;
    iteration: number;
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
    createdAt: string;
    updatedAt: string;
}

export interface LoopCreateRequest {
    name: string;
    branchId: string;
    queryStrategy?: string;
    modelArch?: string;
    globalConfig?: Record<string, any>;
    isActive?: boolean;
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
    extra: Record<string, number>;
    predictionSnapshot: Record<string, number>;
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
