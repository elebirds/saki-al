import { Project, Sample, Annotation, QueryStrategy, BaseModel, ModelVersion, User, LoginResponse, AvailableTypes, AnnotationSystemCapability } from '../../types';

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
  registerAnnotationCapability(capability: AnnotationSystemCapability): Promise<{ status: string; clientId: string }>;

  getProjects(): Promise<Project[]>;
  getProject(id: string): Promise<Project | undefined>;
  createProject(project: Omit<Project, 'id' | 'createdAt' | 'stats'>): Promise<Project>;
  updateProject(id: string, project: Partial<Project>): Promise<Project>;
  deleteProject(id: string): Promise<void>;
  
  getSamples(projectId: string): Promise<Sample[]>;
  getSample(sampleId: string): Promise<Sample | undefined>;
  uploadSamples(projectId: string, files: File[]): Promise<void>;
  
  getSampleAnnotations(sampleId: string): Promise<Annotation[]>;
  saveSampleAnnotations(sampleId: string, annotations: Annotation[]): Promise<void>;
  
  getStrategies(): Promise<QueryStrategy[]>;
  getBaseModels(): Promise<BaseModel[]>;
  
  trainProject(projectId: string): Promise<void>;
  querySamples(projectId: string, n: number): Promise<Sample[]>;

  getModelVersions(projectId: string): Promise<ModelVersion[]>;

  // User Management
  getUsers(skip?: number, limit?: number): Promise<User[]>;
  createUser(user: Partial<User> & { password: string }): Promise<User>;
  updateUser(id: string, user: Partial<User> & { password?: string }): Promise<User>;
  deleteUser(id: string): Promise<void>;
}
