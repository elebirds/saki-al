// Dual-view annotation types
export interface DualViewAnnotation {
    id: string;
    groupId?: string;
    lineageId?: string;
    parentId?: string | null;
    sampleId: string;
    labelId: string;
    labelName: string;  // For display convenience
    labelColor: string; // For display convenience
    annotatorId?: string | null;  // ID of the user who created the annotation
    source?: AnnotationSource;
    confidence?: number;
    // Primary view (Time-Energy) - always a rect or OBB
    primary: {
        type: DetectionAnnotationType;
        bbox: BoundingBox;
    };
    // Secondary view (L-ωd) - can be multiple polygons due to non-monotonic mapping
    secondary: {
        regions: MappedRegion[];
    };
}

export interface BoundingBox {
    x: number;
    y: number;
    width: number;
    height: number;
    rotation?: number;
}

export interface MappedRegion {
    timeRange: [number, number];
    polygonPoints: [number, number][];  // [L, Wd] points
    isPrimary: boolean;  // First region is primary
}

// ============================================================================
// Annotation Types - matches backend enums
// ============================================================================

export type AnnotationType = 'rect' | 'obb' | 'polygon' | 'polyline' | 'point' | 'keypoints';
export type AnnotationSource =
    | 'manual'
    | 'auto'
    | 'model'
    | 'confirmed_model'
    | 'system'
    | 'imported'
    | 'fedo_mapping';

export const ANNOTATION_TYPE_RECT = 'rect' as const;
export const ANNOTATION_TYPE_OBB = 'obb' as const;

export const DETECTION_ANNOTATION_TYPES = [ANNOTATION_TYPE_RECT, ANNOTATION_TYPE_OBB] as const;
export type DetectionAnnotationType = (typeof DETECTION_ANNOTATION_TYPES)[number];

export const DEFAULT_DETECTION_ANNOTATION_TYPES: DetectionAnnotationType[] = [...DETECTION_ANNOTATION_TYPES];

export const ANNOTATION_TOOL_SELECT = 'select' as const;
export type AnnotationToolType = typeof ANNOTATION_TOOL_SELECT | DetectionAnnotationType;

export function isDetectionAnnotationType(value: unknown): value is DetectionAnnotationType {
    return value === ANNOTATION_TYPE_RECT || value === ANNOTATION_TYPE_OBB;
}

export interface RectGeometry {
    x: number;
    y: number;
    width: number;
    height: number;
}

export interface ObbGeometry {
    cx: number;
    cy: number;
    width: number;
    height: number;
    angleDegCcw?: number;
    angle_deg_ccw?: number;
}

export interface AnnotationGeometry {
    rect?: RectGeometry;
    obb?: ObbGeometry;
}

// ============================================================================
// Annotation - Core annotation model
// ============================================================================

export interface Annotation {
    id: string;
    projectId?: string;
    sampleId?: string;
    labelId: string;
    labelName?: string;   // For display convenience
    labelColor?: string;  // For display convenience
    groupId?: string;
    lineageId?: string;
    parentId?: string | null;
    viewRole?: string;
    type: AnnotationType;
    source?: AnnotationSource;
    geometry: AnnotationGeometry;
    attrs?: Record<string, any>;
    confidence?: number;
    annotatorId?: string | null;  // ID of the user who created the annotation
}

// ============================================================================
// Annotation API Types (L2)
// ============================================================================

export interface AnnotationRead {
    id: string;
    projectId: string;
    sampleId: string;
    labelId: string;
    groupId: string;
    lineageId: string;
    parentId?: string | null;
    viewRole: string;
    type: AnnotationType;
    source: AnnotationSource;
    geometry: AnnotationGeometry;
    attrs?: Record<string, any>;
    confidence: number;
    annotatorId?: string | null;
    createdAt: string;
    updatedAt: string;
}

export interface AnnotationDraftItem {
    id?: string;
    projectId?: string;
    sampleId?: string;
    labelId: string;
    groupId: string;
    lineageId: string;
    parentId?: string | null;
    viewRole?: string;
    type: AnnotationType;
    source?: AnnotationSource;
    geometry: AnnotationGeometry;
    attrs?: Record<string, any>;
    confidence?: number;
    annotatorId?: string | null;
}

export interface AnnotationDraftPayload {
    annotations: AnnotationDraftItem[];
    meta?: Record<string, any>;
}

export interface AnnotationDraftRead {
    id: string;
    projectId: string;
    sampleId: string;
    userId: string;
    branchName: string;
    payload: AnnotationDraftPayload;
    createdAt: string;
    updatedAt: string;
}

export interface AnnotationDraftCommitRequest {
    branchName: string;
    commitMessage: string;
    sampleIds?: string[];
}

export interface CommitResult {
    commitId: string;
    message: string;
    parentId?: string | null;
    stats?: Record<string, any>;
    createdAt: string;
}

export type AnnotationSyncActionType = 'add' | 'update' | 'delete';

export interface AnnotationSyncActionItem {
    type: AnnotationSyncActionType;
    groupId: string;
    data?: AnnotationDraftItem;
}

export interface AnnotationSyncRequest {
    baseCommitId?: string | null;
    lastSeqId: number;
    branchName: string;
    actions: AnnotationSyncActionItem[];
    meta?: Record<string, any>;
}

export interface AnnotationSyncResponse {
    status: 'success' | 'conflict';
    currentSeqId: number;
    baseCommitId?: string | null;
    payload: AnnotationDraftPayload;
}
