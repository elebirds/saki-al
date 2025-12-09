import { Project, Sample, Annotation, ALStrategy, ModelArchitecture, User, LoginResponse } from '../../types';

export interface ApiService {
  // Auth
  login(username: string, password: string): Promise<LoginResponse>;
  register(email: string, password: string, fullName?: string): Promise<User>;
  getCurrentUser(): Promise<User>;

  // System
  getSystemStatus(): Promise<{ initialized: boolean }>;
  setupSystem(email: string, password: string, fullName?: string): Promise<User>;

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
