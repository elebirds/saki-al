export interface LabelConfig {
  name: string;
  color: string;
}

// ============================================================================
// Task Type - ML task type for active learning
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
// Frontend Capability Registration
// ============================================================================

export interface AnnotationSystemCapability {
  systemType: AnnotationSystemType;
  version: string;
  features: string[];
  clientId: string;
}

// ============================================================================
// Project
// ============================================================================

export interface Project {
  id: string;
  name: string;
  description?: string;
  
  // Task type - for ML model training
  taskType: TaskType;
  
  // Annotation system - determines UI
  annotationSystem: AnnotationSystemType;
  
  createdAt: string;
  stats: {
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
  
  // Annotation system specific config
  annotationConfig?: {
    // FEDO-specific config
    thumbnailView?: 'time_energy' | 'l_wd';
    visualization?: {
      dpi?: number;
      lXlim?: [number, number];
      wdYlim?: [number, number];
    };
    [key: string]: any;
  };
}

export interface Sample {
  id: string;
  projectId: string;
  url: string;
  filename?: string; // Original filename
  status: 'unlabeled' | 'labeled' | 'skipped';
  score?: number; // Uncertainty score
  // FEDO annotation system fields
  parquetPath?: string;
  timeEnergyImageUrl?: string;
  lWdImageUrl?: string;
  lookupTablePath?: string;
  metadata?: FedoSampleMetadata;
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

export interface FedoLookupTable {
  nTime: number;
  nEnergy: number;
  L: Float32Array;      // (N,) L-shell values
  Wd: Float32Array;     // (N * M,) drift frequency matrix (flattened)
  E: Float32Array;      // (M,) energy centers
  LMin: number;
  LMax: number;
  WdMin: number;
  WdMax: number;
}

// Dual-view annotation types
export interface DualViewAnnotation {
  id: string;
  sampleId: string;
  label: string;
  color?: string;
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

export interface Annotation {
  id: string;
  sampleId: string;
  label: string;
  color?: string; // Add color property
  type: 'rect' | 'obb';
  bbox: {
    x: number;
    y: number;
    width: number;
    height: number;
    rotation?: number;
  };
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
  taskType: 'classification' | 'detection';
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

