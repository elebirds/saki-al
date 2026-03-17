export type FormatProfileId = 'coco' | 'voc' | 'yolo' | 'yolo_obb' | 'dota' | 'predictions_json';
export type YoloLabelFormat = 'det' | 'obb_rbox' | 'obb_poly8';
export type SampleScope = 'all' | 'labeled' | 'unlabeled';
export type ExportBundleLayout = 'merged_zip' | 'per_dataset_zip';
export type PredictionsJSONEntryTraceField = 'sample_id' | 'dataset_id' | 'annotation_commit_id' | 'branch_name' | 'exported_at';
export type PredictionsJSONDetectionTraceField = 'annotation_id' | 'label_id' | 'source' | 'attrs';
export type PredictionsJSONRectCompatField = 'xyxy' | 'xywh';
export type PredictionsJSONObbCompatField = 'xyxyxyxy' | 'xywhr';
export type PredictionsJSONFilterGroupOp = 'and' | 'or';
export type PredictionsJSONFilterOperator = 'eq' | 'neq' | 'in' | 'not_in' | 'gt' | 'gte' | 'lt' | 'lte' | 'exists' | 'not_exists';

export interface FormatProfileCapability {
    id: FormatProfileId;
    family: string;
    supportsImport: boolean;
    supportsExport: boolean;
    supportedAnnotationTypes: string[];
    yoloLabelOptions: YoloLabelFormat[];
    available: boolean;
    reason?: string | null;
}

export interface ProjectIOCapabilities {
    enabledAnnotationTypes: string[];
    exportProfiles: FormatProfileCapability[];
    importProfiles: FormatProfileCapability[];
}

export interface PredictionsJSONFilterRule {
    field: string;
    operator: PredictionsJSONFilterOperator;
    value?: unknown;
}

export interface PredictionsJSONFilterGroup {
    op: PredictionsJSONFilterGroupOp;
    items: PredictionsJSONFilterNode[];
}

export type PredictionsJSONFilterNode = PredictionsJSONFilterGroup | PredictionsJSONFilterRule;

export interface PredictionsJSONGeometryCompatFields {
    rect: PredictionsJSONRectCompatField[];
    obb: PredictionsJSONObbCompatField[];
}

export interface PredictionsJSONOptions {
    includeEmptyEntries?: boolean;
    includeEntryTraceFields?: PredictionsJSONEntryTraceField[];
    includeDetectionTraceFields?: PredictionsJSONDetectionTraceField[];
    geometryCompatFields?: PredictionsJSONGeometryCompatFields;
    filter?: PredictionsJSONFilterNode | null;
}

export type ProjectExportSnapshot =
    | { type: 'branch_head'; branchName: string }
    | { type: 'commit'; commitId: string };

export interface ProjectExportResolveRequest {
    datasetIds: string[];
    snapshot: ProjectExportSnapshot;
    sampleScope: SampleScope;
    formatProfile: FormatProfileId;
    yoloLabelFormat?: YoloLabelFormat;
    predictionsJsonOptions?: PredictionsJSONOptions;
    includeAssets: boolean;
    bundleLayout: ExportBundleLayout;
}

export interface ProjectExportDatasetStat {
    datasetId: string;
    sampleCount: number;
    estimatedAssetBytes: number;
}

export interface ProjectExportResolveResponse {
    resolvedCommitId: string;
    datasetStats: ProjectExportDatasetStat[];
    estimatedTotalAssetBytes: number;
    formatCompatibility: 'ok' | 'incompatible';
    blocked: boolean;
    blockReason?: string | null;
    suggestions: string[];
    annotationTypeCounts: Record<string, number>;
}

export interface ProjectExportChunkRequest {
    resolvedCommitId: string;
    datasetIds: string[];
    sampleScope: SampleScope;
    formatProfile: FormatProfileId;
    yoloLabelFormat?: YoloLabelFormat;
    predictionsJsonOptions?: PredictionsJSONOptions;
    bundleLayout: ExportBundleLayout;
    includeAssets: boolean;
    cursor?: number | null;
    limit?: number;
}

export interface ProjectExportChunkFile {
    datasetId: string;
    sampleId?: string | null;
    path: string;
    sourceType: 'text' | 'url';
    textContent?: string | null;
    downloadUrl?: string | null;
    size?: number | null;
    role?: string | null;
}

export interface ProjectExportChunkResponse {
    nextCursor?: number | null;
    sampleCount: number;
    files: ProjectExportChunkFile[];
    issues: string[];
}
