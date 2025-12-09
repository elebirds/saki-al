import { Project, Sample, Annotation, ALStrategy, ModelArchitecture } from '../../types';

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
