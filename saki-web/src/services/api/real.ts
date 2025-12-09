import axios, { AxiosInstance } from 'axios';
import { Project, Sample, Annotation, ALStrategy, ModelArchitecture } from '../../types';
import { ApiService } from './interface';

export class RealApiService implements ApiService {
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
    // TODO: Implement real API call if needed, or remove if not used
    return undefined;
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
