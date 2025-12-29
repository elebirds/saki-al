import { Project, Sample, Annotation, QueryStrategy, BaseModel, ModelVersion, User, LoginResponse, AvailableTypes, Dataset } from '../../types';

export interface ApiService {
  // Auth
  login(username: string, password: string): Promise<LoginResponse>;
  register(email: string, password: string, fullName?: string): Promise<User>;
  getCurrentUser(): Promise<User>;

  // System
  getSystemStatus(): Promise<{ initialized: boolean }>;
  setupSystem(email: string, password: string, fullName?: string): Promise<User>;
  refreshToken(): Promise<LoginResponse>;
  
  // Types & Capabilities
  getAvailableTypes(): Promise<AvailableTypes>;

  // Dataset APIs (for data annotation)
  getDatasets(): Promise<Dataset[]>;
  getDataset(id: string): Promise<Dataset | undefined>;
  createDataset(dataset: Omit<Dataset, 'id' | 'createdAt' | 'updatedAt' | 'sampleCount' | 'labeledCount'>): Promise<Dataset>;
  updateDataset(id: string, dataset: Partial<Dataset>): Promise<Dataset>;
  deleteDataset(id: string): Promise<void>;
  getDatasetStats(id: string): Promise<{
    datasetId: string;
    totalSamples: number;
    labeledSamples: number;
    unlabeledSamples: number;
    skippedSamples: number;
    completionRate: number;
    linkedProjects: number;
  }>;
  exportDataset(id: string, format?: string, includeUnlabeled?: boolean): Promise<any>;

  // Sample APIs (belong to Dataset)
  getSamples(datasetId: string): Promise<Sample[]>;
  getSample(sampleId: string): Promise<Sample | undefined>;
  uploadSamples(datasetId: string, files: File[]): Promise<void>;
  
  // Annotation APIs
  getSampleAnnotations(sampleId: string): Promise<Annotation[]>;
  saveSampleAnnotations(sampleId: string, annotations: Annotation[]): Promise<void>;
  
  // Config APIs
  getStrategies(): Promise<QueryStrategy[]>;
  getBaseModels(): Promise<BaseModel[]>;

  // Project APIs (for active learning - optional, can be added later)
  getProjects(): Promise<Project[]>;
  getProject(id: string): Promise<Project | undefined>;
  createProject(project: Omit<Project, 'id' | 'createdAt' | 'stats'>): Promise<Project>;
  updateProject(id: string, project: Partial<Project>): Promise<Project>;
  deleteProject(id: string): Promise<void>;
  trainProject(projectId: string): Promise<void>;
  querySamples(projectId: string, n: number): Promise<Sample[]>;
  getModelVersions(projectId: string): Promise<ModelVersion[]>;

  // User Management
  getUsers(skip?: number, limit?: number): Promise<User[]>;
  createUser(user: Partial<User> & { password: string }): Promise<User>;
  updateUser(id: string, user: Partial<User> & { password?: string }): Promise<User>;
  deleteUser(id: string): Promise<void>;
}
