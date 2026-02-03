// Dual-view annotation types
export interface DualViewAnnotation {
  id: string;
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
export type AnnotationSource = 'manual' | 'auto' | 'imported';

// ============================================================================
// Annotation - Core annotation model
// ============================================================================

export interface Annotation {
  id: string;
  sampleId?: string;
  labelId: string;
  labelName?: string;   // For display convenience
  labelColor?: string;  // For display convenience
  type: AnnotationType;
  source?: AnnotationSource;
  data: Record<string, any>;  // Geometry data (bbox, points, etc.)
  extra?: Record<string, any>;  // System-specific (e.g., parentId, view for FEDO)
  annotatorId?: string | null;  // ID of the user who created the annotation
}

// ============================================================================
// Annotation Sync API Types
// ============================================================================

export interface SyncAction {
  action: 'create' | 'update' | 'delete';
  annotationId: string;
  labelId?: string;
  type?: AnnotationType;
  data?: Record<string, any>;
  extra?: Record<string, any>;
}

export interface SyncResult {
  action: string;
  annotationId: string;
  success: boolean;
  error?: string;
  generated: Array<Record<string, any>>;  // Auto-generated annotations (e.g., FEDO mapped)
}

export interface SyncResponse {
  sampleId: string;
  results: SyncResult[];
  ready: boolean;
}

export interface BatchSaveResult {
  sampleId: string;
  savedCount: number;
  success: boolean;
  error?: string;
}

export interface SampleAnnotationsResponse {
  sampleId: string;
  datasetId: string;
  annotationSystem: string;
  annotations: Annotation[];
  // Access scope info for UI adaptation
  readScope: 'all' | 'assigned' | 'self' | 'none';
  modifyScope: 'all' | 'assigned' | 'self' | 'none';
}
