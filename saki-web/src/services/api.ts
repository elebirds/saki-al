import { Project, Sample, Annotation, ALStrategy, ModelArchitecture } from '../types';
import axios, { AxiosInstance } from 'axios';

// --- Interface Definition ---

export interface ApiService {
  getProjects(): Promise<Project[]>;
  getProject(id: string): Promise<Project | undefined>;
  createProject(project: Omit<Project, 'id' | 'createdAt' | 'stats'>): Promise<Project>;
  
  getSamples(projectId: string): Promise<Sample[]>;
  getSample(sampleId: string): Promise<Sample | undefined>;
  uploadSamples(projectId: string, files: File[]): Promise<void>;
  
  getSampleAnnotations(sampleId: string): Promise<Annotation[]>;
  saveSampleAnnotations(sampleId: string, annotations: Annotation[]): Promise<void>;
  
  getStrategies(): Promise<ALStrategy[]>;
  getArchitectures(): Promise<ModelArchitecture[]>;
  
  trainProject(projectId: string): Promise<void>;
  querySamples(projectId: string, n: number): Promise<Sample[]>;
}

// --- Mock Implementation ---

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

class MockApiService implements ApiService {
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

// --- Real Implementation ---

class RealApiService implements ApiService {
  private client: AxiosInstance;

  constructor() {
    this.client = axios.create({
      baseURL: '/api/v1',
      headers: {
        'Content-Type': 'application/json',
      },
    });

    // Add response interceptor for error handling
    this.client.interceptors.response.use(
      (response) => response,
      (error) => {
        const message = error.response?.data?.message || error.message || 'API Error';
        console.error('API Request Failed:', message);
        return Promise.reject(new Error(message));
      }
    );
  }

  async getProjects(): Promise<Project[]> {
    const response = await this.client.get<Project[]>('/projects');
    return response.data;
  }

  async getProject(id: string): Promise<Project | undefined> {
    const response = await this.client.get<Project>(`/projects/${id}`);
    return response.data;
  }

  async createProject(project: Omit<Project, 'id' | 'createdAt' | 'stats'>): Promise<Project> {
    const response = await this.client.post<Project>('/projects', project);
    return response.data;
  }

  async getSamples(projectId: string): Promise<Sample[]> {
    const response = await this.client.get<{ items: Sample[] }>(`/projects/${projectId}/samples`);
    return response.data.items;
  }

  async getSample(sampleId: string): Promise<Sample | undefined> {
    return new Promise((resolve) =>
      setTimeout(() => resolve(mockSamples.find((s) => s.id === sampleId)), 300)
    );
  }

  async uploadSamples(projectId: string, files: File[]): Promise<void> {
    const formData = new FormData();
    files.forEach(file => formData.append('files', file));
    await this.client.post(`/projects/${projectId}/samples`, formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    });
  }

  async getSampleAnnotations(sampleId: string): Promise<Annotation[]> {
    const response = await this.client.get<{ data: any }>(`/samples/${sampleId}/annotation`);
    return response.data.data || [];
  }

  async saveSampleAnnotations(sampleId: string, annotations: Annotation[]): Promise<void> {
    await this.client.post(`/samples/${sampleId}/annotation`, {
      data: annotations,
      status: 'labeled',
    });
  }

  async getStrategies(): Promise<ALStrategy[]> {
    const response = await this.client.get<ALStrategy[]>('/configs/strategies');
    return response.data;
  }

  async getArchitectures(): Promise<ModelArchitecture[]> {
    const response = await this.client.get<ModelArchitecture[]>('/configs/architectures');
    return response.data;
  }

  async trainProject(projectId: string): Promise<void> {
    await this.client.post(`/projects/${projectId}/train`);
  }

  async querySamples(projectId: string, n: number): Promise<Sample[]> {
    const response = await this.client.post<Sample[]>(`/projects/${projectId}/query`, { n });
    return response.data;
  }
}

// --- Export ---

// Default to mock if not specified or set to 'true'
const useMock = (import.meta as any).env.VITE_USE_MOCK_API !== 'false';

export const api: ApiService = useMock ? new MockApiService() : new RealApiService();
