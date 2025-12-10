import { Project, Sample, Annotation, ALStrategy, ModelArchitecture } from '../../types';
import { ApiService } from './interface';

const mockStrategies: ALStrategy[] = [
  { id: 'least_confidence', name: 'Least Confidence', description: 'Selects samples where the model is least confident.' },
  { id: 'margin_sampling', name: 'Margin Sampling', description: 'Selects samples with the smallest margin between top two predictions.' },
  { id: 'entropy_sampling', name: 'Entropy Sampling', description: 'Selects samples with the highest entropy.' },
  { id: 'random', name: 'Random Sampling', description: 'Selects samples randomly.' },
];

const mockArchitectures: ModelArchitecture[] = [
  { id: 'resnet18', name: 'ResNet-18', taskType: 'classification' },
  { id: 'resnet50', name: 'ResNet-50', taskType: 'classification' },
  { id: 'efficientnet_b0', name: 'EfficientNet-B0', taskType: 'classification' },
  { id: 'yolov5', name: 'YOLOv5', taskType: 'detection' },
  { id: 'faster_rcnn', name: 'Faster R-CNN', taskType: 'detection' },
];

let mockProjects: Project[] = [
  {
    id: '1',
    name: 'Traffic Sign Detection',
    description: 'Detect traffic signs in street view images.',
    taskType: 'detection',
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
      access_token: 'mock-token',
      token_type: 'bearer',
    };
  }

  async register(email: string, password: string, fullName?: string): Promise<User> {
    return {
      id: '1',
      email,
      full_name: fullName,
      is_active: true,
      is_superuser: false,
    };
  }

  async getCurrentUser(): Promise<User> {
    return {
      id: '1',
      email: 'admin@example.com',
      full_name: 'Admin User',
      is_active: true,
      is_superuser: true,
    };
  }

  async getSystemStatus(): Promise<{ initialized: boolean }> {
    return { initialized: true };
  }

  async setupSystem(email: string, password: string, fullName?: string): Promise<User> {
    return {
      id: '1',
      email,
      full_name: fullName,
      is_active: true,
      is_superuser: true,
    };
  }

  async refreshToken(): Promise<LoginResponse> {
    return {
      access_token: 'mock-refreshed-token',
      token_type: 'bearer',
    };
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

  async getSamples(projectId: string): Promise<Sample[]> {
    console.log(`Fetching samples for project ${projectId}`);
    return new Promise((resolve) => setTimeout(() => resolve(mockSamples), 400));
  }

  async getSample(sampleId: string): Promise<Sample | undefined> {
    return new Promise((resolve) =>
      setTimeout(() => resolve(mockSamples.find((s) => s.id === sampleId)), 300)
    );
  }

  async uploadSamples(projectId: string, files: File[]): Promise<void> {
    console.log(`Uploading ${files.length} files to project ${projectId}`);
    // Mock adding samples
    const newSamples: Sample[] = files.map((file, i) => ({
        id: `new-sample-${Date.now()}-${i}`,
        projectId,
        url: URL.createObjectURL(file), // This will only work for the current session
        status: 'unlabeled',
    }));
    mockSamples = [...mockSamples, ...newSamples];
    return new Promise((resolve) => setTimeout(resolve, 1000));
  }

  async getSampleAnnotations(sampleId: string): Promise<Annotation[]> {
    return new Promise((resolve) => 
        setTimeout(() => resolve(mockAnnotations[sampleId] || []), 300)
    );
  }

  async saveSampleAnnotations(sampleId: string, annotations: Annotation[]): Promise<void> {
    mockAnnotations[sampleId] = annotations;
    // Update sample status
    const sample = mockSamples.find(s => s.id === sampleId);
    if (sample) {
        sample.status = 'labeled';
    }
    return new Promise((resolve) => setTimeout(resolve, 500));
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
