// ============================================================================
// Label - Annotation label belonging to a Dataset
// ============================================================================

export interface Label {
  id: string;
  datasetId: string;
  name: string;
  color: string;
  description?: string;
  sortOrder: number;
  annotationCount: number;
  createdAt: string;
  updatedAt?: string;
}

export interface LabelCreate {
  name: string;
  color?: string;
  description?: string;
  sortOrder?: number;
}

export interface LabelUpdate {
  name?: string;
  color?: string;
  description?: string;
  sortOrder?: number;
}

// Legacy type for backward compatibility with Project labels
export interface LabelConfig {
  name: string;
  color: string;
}

// ============================================================================
// Task Type - ML task type for active learning (used in Project)
// ============================================================================

export type TaskType = 'classification' | 'detection' | 'segmentation';

// ============================================================================
// Annotation System Type - determines which annotation UI to use
// ============================================================================

export type AnnotationSystemType = 'classic' | 'fedo';

// ============================================================================
// Type Info - for dynamic type loading from backend
// ============================================================================

export interface TypeInfo {
  value: string;
  label: string;
  description: string;
}

export interface AvailableTypes {
  taskTypes: TypeInfo[];
  annotationSystems: TypeInfo[];
}

// ============================================================================
// Dataset - Independent entity for data annotation
// ============================================================================

export interface Dataset {
  id: string;
  name: string;
  description?: string;
  
  // Annotation system - determines UI for this dataset
  annotationSystem: AnnotationSystemType;
  
  createdAt: string;
  updatedAt?: string;
  
  // Statistics
  sampleCount: number;
  labeledCount: number;
}

// ============================================================================
// Project - For active learning training (links to datasets)
// ============================================================================

export interface Project {
  id: string;
  name: string;
  description?: string;
  
  // Task type - for ML model training
  taskType: TaskType;
  
  createdAt: string;
  stats: {
    totalDatasets: number;
    totalSamples: number;
    labeledSamples: number;
    accuracy?: number;
  };
  
  // Settings
  labels: LabelConfig[];
  queryStrategyId?: string;
  baseModelId?: string;
  alConfig: {
    batchSize: number;
    [key: string]: any;
  };
  modelConfig: {
    [key: string]: any;
  };
}

export interface Sample {
  id: string;

  datasetId: string;
  name: string;
  url: string;
  remark: string;
  
  status: 'unlabeled' | 'labeled' | 'skipped';

  metaData: Record<string, any>;
}

// FEDO specialized task types
export interface FedoSampleMetadata {
  nTime: number;
  nEnergy: number;
  LRange: [number, number];
  WdRange: [number, number];
  visualizationConfig: {
    dpi: number;
    lXlim: [number, number];
    wdYlim: [number, number];
  };
}

// Dual-view annotation types
export interface DualViewAnnotation {
  id: string;
  sampleId: string;
  labelId: string;
  labelName: string;  // For display convenience
  labelColor: string; // For display convenience
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
}

export interface QueryStrategy {
  id: string;
  name: string;
  description?: string;
  paramsSchema?: any;
  enabled: boolean;
}

// Alias for backward compatibility
export type ALStrategy = QueryStrategy;

export interface BaseModel {
  id: string;
  name: string;
  taskType: TaskType;
  framework?: string;
  provider?: string;
  description?: string;
  enabled: boolean;
}

// Alias for backward compatibility
export type ModelArchitecture = BaseModel;

export interface ModelVersion {
  id: string;
  projectId: string;
  baseModelId?: string;
  name: string;
  description?: string;
  metrics: Record<string, number>;
  status: 'training' | 'ready' | 'failed';
  createdAt: string;
}

export interface User {
  id: string;
  email: string;
  fullName?: string;
  isActive: boolean;
  isSuperuser: boolean;
}

export interface LoginResponse {
  accessToken: string;
  tokenType: string;
}

// ============================================================================
// Upload Progress Types
// ============================================================================

export type UploadProgressLevel = 'debug' | 'info' | 'warning' | 'error';

export interface UploadProgressLog {
  timestamp: string;
  level: UploadProgressLevel;
  stage: string;
  message: string;
  current: number;
  total: number;
  percentage: number;
  details?: Record<string, any>;
}

export interface UploadFileResult {
  id?: string;
  filename: string;
  status: 'success' | 'error';
  error?: string;
}

export interface UploadResult {
  uploaded: number;
  errors: number;
  results: UploadFileResult[];
  progressLogs?: UploadProgressLog[];
}

export type UploadEventType = 
  | 'start'
  | 'file_start'
  | 'file_complete'
  | 'file_error'
  | 'complete';

export interface UploadProgressEvent {
  event: UploadEventType;
  index?: number;
  filename?: string;
  success?: boolean;
  sampleId?: string;
  error?: string;
  total?: number;
  uploaded?: number;
  errors?: number;
  results?: UploadFileResult[];
}

export interface UploadProgress {
  status: 'idle' | 'uploading' | 'complete' | 'error';
  currentFile: number;
  totalFiles: number;
  percentage: number;
  currentFilename: string;
  results: UploadFileResult[];
  error?: string;
}

