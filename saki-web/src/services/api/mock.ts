import { Project, Sample, Annotation, ALStrategy, ModelArchitecture, AvailableTypes, User, LoginResponse, UploadProgressEvent, UploadResult, UploadFileResult, SyncAction, SyncResponse, BatchSaveResult, SampleAnnotationsResponse } from '../../types';
import { ApiService, UploadProgressCallback } from './interface';

const mockStrategies: ALStrategy[] = [
  { enabled: true, id: 'least_confidence', name: 'Least Confidence', description: 'Selects samples where the model is least confident.' },
  { enabled: true, id: 'margin_sampling', name: 'Margin Sampling', description: 'Selects samples with the smallest margin between top two predictions.' },
  { enabled: true, id: 'entropy_sampling', name: 'Entropy Sampling', description: 'Selects samples with the highest entropy.' },
  { enabled: true, id: 'random', name: 'Random Sampling', description: 'Selects samples randomly.' },
];

const mockArchitectures: ModelArchitecture[] = [
  { enabled: true, id: 'resnet18', name: 'ResNet-18', taskType: 'classification' },
  { enabled: true, id: 'resnet50', name: 'ResNet-50', taskType: 'classification' },
  { enabled: true, id: 'efficientnet_b0', name: 'EfficientNet-B0', taskType: 'classification' },
  { enabled: true, id: 'yolov5', name: 'YOLOv5', taskType: 'detection' },
  { enabled: true, id: 'faster_rcnn', name: 'Faster R-CNN', taskType: 'detection' },
];

const mockAvailableTypes: AvailableTypes = {
  taskTypes: [
    { value: 'classification', label: 'Classification', description: 'Image classification task' },
    { value: 'detection', label: 'Detection', description: 'Object detection task' },
    { value: 'segmentation', label: 'Segmentation', description: 'Semantic segmentation task' },
  ],
  annotationSystems: [
    { value: 'classic', label: 'Classic Annotation', description: 'Standard image annotation' },
    { value: 'fedo', label: 'FEDO Dual-View', description: 'Satellite electron energy data annotation' },
  ],
};

let mockProjects: Project[] = [
  {
    id: '1',
    name: 'Traffic Sign Detection',
    description: 'Detect traffic signs in street view images.',
    taskType: 'detection',
    annotationSystem: 'classic',
    createdAt: '2023-10-01T10:00:00Z',
    stats: {
      totalSamples: 1200,
      labeledSamples: 150,
      accuracy: 0.85,
    },
    labels: [
      { name: 'stop sign', color: '#ff0000' },
      { name: 'traffic light', color: '#00ff00' },
      { name: 'pedestrian', color: '#0000ff' }
    ],
    alConfig: {
      strategy: 'least_confidence',
      batchSize: 20,
    },
    modelConfig: {
      architecture: 'yolov5',
    },
  },
  {
    id: '2',
    name: 'Cat vs Dog Classification',
    description: 'Classify images as cat or dog.',
    taskType: 'classification',
    annotationSystem: 'classic',
    createdAt: '2023-10-05T14:30:00Z',
    stats: {
      totalSamples: 5000,
      labeledSamples: 20,
      accuracy: 0.60,
    },
    labels: [
      { name: 'cat', color: '#ffa500' },
      { name: 'dog', color: '#800080' }
    ],
    alConfig: {
      strategy: 'entropy_sampling',
      batchSize: 10,
    },
    modelConfig: {
      architecture: 'resnet50',
    },
  },
  {
    id: '3',
    name: 'FEDO Electron Flux',
    description: 'Satellite electron energy data annotation.',
    taskType: 'detection',
    annotationSystem: 'fedo',
    createdAt: '2023-12-01T10:00:00Z',
    stats: {
      totalSamples: 50,
      labeledSamples: 5,
      accuracy: 0,
    },
    labels: [
      { name: 'injection', color: '#ff0000' },
      { name: 'dropout', color: '#0000ff' }
    ],
    alConfig: {
      batchSize: 5,
    },
    modelConfig: {},
  },
];

let mockSamples: Sample[] = Array.from({ length: 20 }).map((_, i) => ({
  id: `sample-${i}`,
  projectId: '1',
  url: `https://picsum.photos/seed/${i}/800/600`,
  status: i < 5 ? 'labeled' : 'unlabeled',
  score: Math.random(),
}));

// In-memory storage for annotations: sampleId -> Annotation[]
const mockAnnotations: Record<string, Annotation[]> = {};

export class MockApiService implements ApiService {
  async login(username: string, password: string): Promise<LoginResponse> {
    return {
      accessToken: 'mock-token',
      tokenType: 'bearer',
    };
  }

  async register(email: string, password: string, fullName?: string): Promise<User> {
    return {
      id: '1',
      email,
      fullName: fullName,
      isActive: true,
      globalRole: 'viewer' as const,
    };
  }

  async getCurrentUser(): Promise<User> {
    return {
      id: '1',
      email: 'admin@example.com',
      fullName: 'Admin User',
      isActive: true,
      globalRole: 'super_admin' as const,
    };
  }

  async getSystemStatus(): Promise<{ initialized: boolean }> {
    return { initialized: true };
  }

  async setupSystem(email: string, password: string, fullName?: string): Promise<User> {
    return {
      id: '1',
      email,
      fullName: fullName,
      isActive: true,
      globalRole: 'super_admin' as const,
    };
  }

  async refreshToken(): Promise<LoginResponse> {
    return {
      accessToken: 'mock-refreshed-token',
      tokenType: 'bearer',
    };
  }

  async getAvailableTypes(): Promise<AvailableTypes> {
    return mockAvailableTypes;
  }


  async getProjects(): Promise<Project[]> {
    return new Promise((resolve) => setTimeout(() => resolve(mockProjects), 500));
  }

  async getProject(id: string): Promise<Project | undefined> {
    return new Promise((resolve) =>
      setTimeout(() => resolve(mockProjects.find((p) => p.id === id)), 300)
    );
  }

  async createProject(project: Omit<Project, 'id' | 'createdAt' | 'stats'>): Promise<Project> {
    const newProject: Project = {
      ...project,
      id: Math.random().toString(36).substr(2, 9),
      createdAt: new Date().toISOString(),
      stats: { totalSamples: 0, labeledSamples: 0 },
    };
    mockProjects.push(newProject);
    return new Promise((resolve) => setTimeout(() => resolve(newProject), 500));
  }

  async updateProject(id: string, project: Partial<Project>): Promise<Project> {
    const index = mockProjects.findIndex((p) => p.id === id);
    if (index !== -1) {
      mockProjects[index] = { ...mockProjects[index], ...project };
      return new Promise((resolve) => setTimeout(() => resolve(mockProjects[index]), 500));
    }
    throw new Error('Project not found');
  }

  async deleteProject(id: string): Promise<void> {
    mockProjects = mockProjects.filter((p) => p.id !== id);
    return new Promise((resolve) => setTimeout(() => resolve(), 500));
  }

  async getSamples(
    datasetId: string,
    options?: {
      status?: 'unlabeled' | 'labeled' | 'skipped';
      skip?: number;
      limit?: number;
      sortBy?: 'name' | 'status' | 'created_at' | 'updated_at' | 'remark';
      sortOrder?: 'asc' | 'desc';
    }
  ): Promise<Sample[]> {
    console.log(`Fetching samples for dataset ${datasetId}`, options);
    let result = [...mockSamples];
    
    // Apply status filter
    if (options?.status) {
      result = result.filter(s => s.status === options.status);
    }
    
    // Apply sorting
    if (options?.sortBy) {
      const sortField = options.sortBy;
      const sortOrder = options.sortOrder || 'asc';
      
      result.sort((a, b) => {
        let aVal: any = (a as any)[sortField];
        let bVal: any = (b as any)[sortField];
        
        // Handle date fields
        if (sortField === 'created_at' || sortField === 'updated_at') {
          aVal = aVal ? new Date(aVal).getTime() : 0;
          bVal = bVal ? new Date(bVal).getTime() : 0;
        }
        
        // Handle string comparison
        if (typeof aVal === 'string' && typeof bVal === 'string') {
          aVal = aVal.toLowerCase();
          bVal = bVal.toLowerCase();
        }
        
        if (aVal < bVal) return sortOrder === 'asc' ? -1 : 1;
        if (aVal > bVal) return sortOrder === 'asc' ? 1 : -1;
        return 0;
      });
    }
    
    // Apply pagination
    if (options?.skip !== undefined) {
      result = result.slice(options.skip);
    }
    if (options?.limit !== undefined) {
      result = result.slice(0, options.limit);
    }
    
    return new Promise((resolve) => setTimeout(() => resolve(result), 400));
  }

  async getSample(sampleId: string): Promise<Sample | undefined> {
    return new Promise((resolve) =>
      setTimeout(() => resolve(mockSamples.find((s) => s.id === sampleId)), 300)
    );
  }

  async uploadSamplesWithProgress(
    projectId: string,
    files: File[],
    onProgress?: UploadProgressCallback,
    _signal?: AbortSignal
  ): Promise<UploadResult> {
    console.log(`Uploading ${files.length} files to project ${projectId}`);

    // Simulate start event
    onProgress?.({ event: 'start', total: files.length });

    const results: UploadFileResult[] = [];
    const newSamples: Sample[] = [];

    for (let i = 0; i < files.length; i++) {
      const file = files[i];
      const sampleId = `new-sample-${Date.now()}-${i}`;

      // Simulate file_start event
      onProgress?.({ event: 'file_start', index: i, filename: file.name });

      // Simulate processing delay
      await new Promise(resolve => setTimeout(resolve, 200));

      // Create mock sample
      const sample: Sample = {
        id: sampleId,
        projectId,
        url: URL.createObjectURL(file),
        status: 'unlabeled',
      };
      newSamples.push(sample);

      results.push({
        id: sampleId,
        filename: file.name,
        status: 'success',
      });

      // Simulate file_complete event
      onProgress?.({
        event: 'file_complete',
        index: i,
        filename: file.name,
        success: true,
        sampleId,
      });
    }

    mockSamples = [...mockSamples, ...newSamples];

    const uploadResult: UploadResult = {
      uploaded: files.length,
      errors: 0,
      results,
    };

    // Simulate complete event
    onProgress?.({
      event: 'complete',
      uploaded: files.length,
      errors: 0,
      results,
    });

    return uploadResult;
  }

  async getSampleAnnotations(sampleId: string): Promise<SampleAnnotationsResponse> {
    return new Promise((resolve) => 
        setTimeout(() => resolve({
          sampleId,
          datasetId: 'mock-dataset',
          annotationSystem: 'classic',
          annotations: mockAnnotations[sampleId] || [],
        }), 300)
    );
  }

  async syncAnnotations(sampleId: string, actions: SyncAction[]): Promise<SyncResponse> {
    // Mock sync - just return success for each action
    const results = actions.map(action => ({
      action: action.action,
      annotationId: action.annotationId,
      success: true,
      generated: [],
    }));
    return new Promise((resolve) => 
      setTimeout(() => resolve({
        sampleId,
        results,
        ready: true,
      }), 100)
    );
  }

  async saveAnnotations(sampleId: string, annotations: Annotation[], updateStatus?: 'labeled' | 'skipped'): Promise<BatchSaveResult> {
    mockAnnotations[sampleId] = annotations;
    // Update sample status
    const sample = mockSamples.find(s => s.id === sampleId);
    if (sample && updateStatus) {
        sample.status = updateStatus;
    }
    return new Promise((resolve) => setTimeout(() => resolve({
      sampleId,
      savedCount: annotations.length,
      success: true,
    }), 500));
  }

  async deleteAnnotations(sampleId: string): Promise<{ deleted: number; sampleId: string }> {
    const count = (mockAnnotations[sampleId] || []).length;
    mockAnnotations[sampleId] = [];
    return new Promise((resolve) => setTimeout(() => resolve({ deleted: count, sampleId }), 300));
  }

  async getStrategies(): Promise<ALStrategy[]> {
    return Promise.resolve(mockStrategies);
  }

  async getArchitectures(): Promise<ModelArchitecture[]> {
    return Promise.resolve(mockArchitectures);
  }

  async trainProject(projectId: string): Promise<void> {
    console.log(`Training project ${projectId}`);
    return new Promise((resolve) => setTimeout(resolve, 2000));
  }

  async querySamples(projectId: string, n: number): Promise<Sample[]> {
    console.log(`Querying top ${n} samples for project ${projectId}`);
    // Return random unlabeled samples
    const unlabeled = mockSamples.filter(s => s.status === 'unlabeled');
    return new Promise((resolve) => setTimeout(() => resolve(unlabeled.slice(0, n)), 1000));
  }
}
