export type ImportFormat = 'coco' | 'voc' | 'yolo' | 'yolo_obb' | 'dota';

export type ConflictStrategy = 'replace' | 'merge';
export type PathFlattenMode = 'basename' | 'preserve_path';
export type NameCollisionPolicy = 'abort' | 'auto_rename' | 'overwrite';

export type AssociatedDatasetMode = 'existing' | 'new';
export type ImportUploadStrategy = 'single_put' | 'multipart';
export type ImportUploadSessionStatus = 'initiated' | 'uploading' | 'uploaded' | 'aborted' | 'expired' | 'consumed';

export type ImportProgressEventType = 'start' | 'phase' | 'item' | 'annotation' | 'warning' | 'error' | 'complete';

export interface ImportIssue {
    code: string;
    message: string;
    path?: string | null;
    detail?: Record<string, unknown> | null;
}

export interface ImportDryRunResponse {
    previewToken: string;
    expiresAt: string;
    summary: Record<string, unknown>;
    plannedNewLabels: string[];
    warnings: ImportIssue[];
    errors: ImportIssue[];
}

export interface ImportExecuteRequest {
    previewToken: string;
    conflictStrategy?: ConflictStrategy;
    confirmCreateLabels?: boolean;
}

export interface ImportProgressEvent {
    seq?: number;
    ts?: string;
    event: ImportProgressEventType;
    eventSubtype?: string;
    phase?: string;
    message?: string;
    current?: number;
    total?: number;
    itemKey?: string;
    status?: string;
    detail?: Record<string, unknown>;
    receivedAt?: string;
}

export interface ImportTaskCreateResponse {
    taskId: string;
    status: string;
    streamUrl: string;
    statusUrl: string;
}

export interface ImportTaskStatusResponse {
    taskId: string;
    status: string;
    progress: {
        current: number;
        total: number;
    };
    summary: Record<string, unknown>;
    error?: string | null;
    startedAt?: string | null;
    finishedAt?: string | null;
}

export interface ImportTaskResultResponse {
    taskId: string;
    status: string;
    result: Record<string, unknown>;
    error?: string | null;
}

export interface ImportUploadInitRequest {
    mode: 'dataset_images' | 'project_annotations' | 'project_associated';
    resourceType: 'dataset' | 'project';
    resourceId: string;
    filename: string;
    size: number;
    contentType: string;
}

export interface ImportUploadInitResponse {
    sessionId: string;
    strategy: ImportUploadStrategy;
    objectKey: string;
    expiresAt: string;
    partSize: number;
    uploadId?: string | null;
    url?: string | null;
    headers?: Record<string, string>;
}

export interface ImportUploadPartSignRequest {
    partNumbers: number[];
}

export interface ImportUploadPartSignedItem {
    partNumber: number;
    url: string;
    headers: Record<string, string>;
}

export interface ImportUploadPartSignResponse {
    sessionId: string;
    uploadId: string;
    parts: ImportUploadPartSignedItem[];
}

export interface ImportUploadCompletedPart {
    partNumber: number;
    etag: string;
}

export interface ImportUploadCompleteRequest {
    size: number;
    parts?: ImportUploadCompletedPart[];
}

export interface ImportUploadSessionResponse {
    sessionId: string;
    mode: string;
    resourceType: string;
    resourceId: string;
    filename: string;
    size: number;
    uploadedSize: number;
    contentType: string;
    objectKey: string;
    strategy: ImportUploadStrategy;
    status: ImportUploadSessionStatus;
    uploadId?: string | null;
    expiresAt?: string | null;
    error?: string | null;
}

export interface ImportUploadAbortResponse {
    sessionId: string;
    status: ImportUploadSessionStatus;
}

export interface DatasetImportPrepareRequest {
    uploadSessionId: string;
    pathFlattenMode?: PathFlattenMode;
    nameCollisionPolicy?: NameCollisionPolicy;
}

export interface ProjectAnnotationImportPrepareRequest {
    uploadSessionId: string;
    formatProfile: ImportFormat;
    datasetId: string;
    branchName: string;
    pathFlattenMode?: PathFlattenMode;
    nameCollisionPolicy?: NameCollisionPolicy;
}

export interface ProjectAssociatedImportPrepareRequest {
    uploadSessionId: string;
    formatProfile: ImportFormat;
    branchName: string;
    pathFlattenMode?: PathFlattenMode;
    nameCollisionPolicy?: NameCollisionPolicy;
    targetDatasetMode: AssociatedDatasetMode;
    targetDatasetId?: string;
    newDatasetName?: string;
    newDatasetDescription?: string;
}

export interface ImportImageEntry {
    zipEntryPath: string;
    resolvedSampleName: string;
    originalRelativePath: string;
    collisionAction?: string;
}

export interface SampleBulkImportRequest {
    previewToken?: string;
    zipAssetId?: string;
    imageEntries?: ImportImageEntry[];
}

export type AnnotationBulkSource = 'direct' | 'import_preview';

export interface AnnotationBulkRequest {
    source: AnnotationBulkSource;
    branchName?: string;
    commitMessage?: string;
    conflictStrategy?: ConflictStrategy;
    confirmCreateLabels?: boolean;
    annotations?: Record<string, unknown>[];
    previewToken?: string;
}

export interface ImportTaskState {
    taskId?: string;
    lastSeq?: number;
    status: 'idle' | 'running' | 'complete' | 'error';
    events: ImportProgressEvent[];
    phase?: string;
    progress: {
        current: number;
        total: number;
    };
    error?: string;
}
