// Dual-view annotation types
export interface DualViewAnnotation {
  id: string;
  syncId?: string;
  parentId?: string | null;
  sampleId: string;
  labelId: string;
  labelName: string;  // For display convenience
  labelColor: string; // For display convenience
  annotatorId?: string | null;  // ID of the user who created the annotation
  // Primary view (Time-Energy) - always a rect or OBB
  primary: {
    type: 'rect' | 'obb';
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
export type AnnotationSource = 'manual' | 'auto' | 'model' | 'system' | 'imported';

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
  syncId?: string;
  parentId?: string | null;
  viewRole?: string;
  type: AnnotationType;
  source?: AnnotationSource;
  data: Record<string, any>;  // Geometry data (bbox, points, etc.)
  extra?: Record<string, any>;  // System-specific (e.g., parentId, view for FEDO)
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
  syncId: string;
  parentId?: string | null;
  viewRole: string;
  type: AnnotationType;
  source: AnnotationSource;
  data: Record<string, any>;
  extra?: Record<string, any>;
  confidence: number;
  annotatorId?: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface AnnotationDraftItem {
  projectId?: string;
  sampleId?: string;
  labelId: string;
  syncId: string;
  parentId?: string | null;
  viewRole?: string;
  type: AnnotationType;
  source?: AnnotationSource;
  data: Record<string, any>;
  extra?: Record<string, any>;
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

export type AnnotationSyncAction = 'create' | 'update' | 'delete';

export interface AnnotationSyncRequest {
  action: AnnotationSyncAction;
  annotationId: string;
  labelId?: string;
  type?: AnnotationType;
  data?: Record<string, any>;
  extra?: Record<string, any>;
}

export interface AnnotationSyncResponse {
  success: boolean;
  annotationId: string;
  action: AnnotationSyncAction;
  error?: string;
  generated: Record<string, any>[];
}
