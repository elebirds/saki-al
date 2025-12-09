export interface LabelConfig {
  name: string;
  color: string;
}

export interface Project {
  id: string;
  name: string;
  description?: string;
  taskType: 'classification' | 'detection';
  createdAt: string;
  stats: {
    totalSamples: number;
    labeledSamples: number;
    accuracy?: number;
  };
  // New fields for settings
  labels: LabelConfig[];
  alConfig: {
    strategy: string;
    batchSize: number;
  };
  modelConfig: {
    architecture: string;
    baseModel?: string;
  };
}

export interface Sample {
  id: string;
  projectId: string;
  url: string;
  status: 'unlabeled' | 'labeled' | 'skipped';
  score?: number; // Uncertainty score
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

export interface ALStrategy {
  id: string;
  name: string;
  description?: string;
}

export interface ModelArchitecture {
  id: string;
  name: string;
  taskType: 'classification' | 'detection' | 'both';
}

export interface User {
  id: string;
  email: string;
  full_name?: string;
  is_active: boolean;
  is_superuser: boolean;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
}
