export type FormatProfileId = 'coco' | 'voc' | 'yolo' | 'yolo_obb' | 'dota';
export type SampleScope = 'all' | 'labeled' | 'unlabeled';
export type ExportBundleLayout = 'merged_zip' | 'per_dataset_zip';

export interface FormatProfileCapability {
    id: FormatProfileId;
    family: string;
    supportsImport: boolean;
    supportsExport: boolean;
    supportedAnnotationTypes: string[];
    yoloLabelOptions: string[];
    available: boolean;
    reason?: string | null;
}

export interface ProjectIOCapabilities {
    enabledAnnotationTypes: string[];
    exportProfiles: FormatProfileCapability[];
    importProfiles: FormatProfileCapability[];
}

export type ProjectExportSnapshot =
    | { type: 'branch_head'; branchName: string }
    | { type: 'commit'; commitId: string };

export interface ProjectExportResolveRequest {
    datasetIds: string[];
    snapshot: ProjectExportSnapshot;
    sampleScope: SampleScope;
    formatProfile: FormatProfileId;
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
