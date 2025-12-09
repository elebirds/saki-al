import axios, { AxiosInstance } from 'axios';
import { Project, Sample, Annotation, ALStrategy, ModelArchitecture, User, LoginResponse } from '../../types';
import { ApiService } from './interface';
import { useAuthStore } from '../../store/authStore';

export class RealApiService implements ApiService {
  private client: AxiosInstance;

  constructor() {
    this.client = axios.create({
      baseURL: 'http://localhost:8000/api/v1', // Updated to point to backend
      headers: {
        'Content-Type': 'application/json',
      },
    });

    // Add request interceptor to inject token
    this.client.interceptors.request.use(
      (config) => {
        const token = useAuthStore.getState().token;
        if (token) {
          config.headers.Authorization = `Bearer ${token}`;
        }
        return config;
      },
      (error) => Promise.reject(error)
    );

    // Add response interceptor for error handling
    this.client.interceptors.response.use(
      (response) => response,
      (error) => {
        if (error.response?.status === 401) {
          useAuthStore.getState().logout();
        }
        const message = error.response?.data?.detail || error.message || 'API Error';
        console.error('API Request Failed:', message);
        return Promise.reject(new Error(message));
      }
    );
  }

  async login(username: string, password: string): Promise<LoginResponse> {
    const formData = new URLSearchParams();
    formData.append('username', username);
    formData.append('password', password);
    
    const response = await this.client.post<LoginResponse>('/login/access-token', formData, {
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' }
    });
    return response.data;
  }

  async register(email: string, password: string, fullName?: string): Promise<User> {
    const response = await this.client.post<User>('/register', { email, password, full_name: fullName });
    return response.data;
  }

  async getCurrentUser(): Promise<User> {
    const response = await this.client.get<User>('/users/me');
    return response.data;
  }

  async getSystemStatus(): Promise<{ initialized: boolean }> {
    const response = await this.client.get<{ initialized: boolean }>('/system/status');
    return response.data;
  }

  async setupSystem(email: string, password: string, fullName?: string): Promise<User> {
    const response = await this.client.post<User>('/system/setup', { email, password, full_name: fullName });
    return response.data;
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

  async updateProject(id: string, project: Partial<Project>): Promise<Project> {
    const response = await this.client.put<Project>(`/projects/${id}`, project);
    return response.data;
  }

  async deleteProject(id: string): Promise<void> {
    await this.client.delete(`/projects/${id}`);
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
