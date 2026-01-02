import axios, { AxiosInstance, InternalAxiosRequestConfig } from 'axios';
import { Project, Sample, Annotation, QueryStrategy, BaseModel, ModelVersion, User, LoginResponse, AvailableTypes, Dataset, Label, LabelCreate, LabelUpdate, UploadProgressEvent, UploadResult, SyncAction, SyncResponse, BatchSaveResult, SampleAnnotationsResponse, DatasetMember, DatasetMemberCreate, DatasetMemberUpdate, GlobalRole } from '../../types';
import { ApiService, UploadProgressCallback } from './interface';
import { useAuthStore } from '../../store/authStore';

// ============================================================================
// Case Conversion Utilities
// ============================================================================

/** Convert snake_case string to camelCase */
function snakeToCamel(str: string): string {
  return str.replace(/_([a-z])/g, (_, letter) => letter.toUpperCase());
}

/** Convert camelCase string to snake_case */
function camelToSnake(str: string): string {
  return str.replace(/[A-Z]/g, letter => `_${letter.toLowerCase()}`);
}

/** Recursively convert object keys from snake_case to camelCase */
function convertKeysToCamel<T>(obj: unknown): T {
  if (Array.isArray(obj)) {
    return obj.map(item => convertKeysToCamel(item)) as T;
  }
  if (obj !== null && typeof obj === 'object') {
    return Object.keys(obj as object).reduce((result, key) => {
      const camelKey = snakeToCamel(key);
      (result as Record<string, unknown>)[camelKey] = convertKeysToCamel((obj as Record<string, unknown>)[key]);
      return result;
    }, {} as T);
  }
  return obj as T;
}

/** Recursively convert object keys from camelCase to snake_case */
function convertKeysToSnake<T>(obj: unknown): T {
  if (Array.isArray(obj)) {
    return obj.map(item => convertKeysToSnake(item)) as T;
  }
  if (obj !== null && typeof obj === 'object') {
    return Object.keys(obj as object).reduce((result, key) => {
      const snakeKey = camelToSnake(key);
      (result as Record<string, unknown>)[snakeKey] = convertKeysToSnake((obj as Record<string, unknown>)[key]);
      return result;
    }, {} as T);
  }
  return obj as T;
}

// ============================================================================
// API Service Implementation
// ============================================================================

export class RealApiService implements ApiService {
  private client: AxiosInstance;

  constructor() {
    this.client = axios.create({
      baseURL: 'http://localhost:8000/api/v1',
      headers: {
        'Content-Type': 'application/json',
      },
    });

    // ========================================================================
    // Request Interceptors
    // ========================================================================
    
    // 1. Add auth token
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

    // 2. Convert request body from camelCase to snake_case
    this.client.interceptors.request.use(
      (config: InternalAxiosRequestConfig) => {
        // Only convert JSON data, skip FormData and URLSearchParams
        if (config.data && 
            !(config.data instanceof FormData) && 
            !(config.data instanceof URLSearchParams)) {
          config.data = convertKeysToSnake(config.data);
        }
        return config;
      },
      (error) => Promise.reject(error)
    );

    // ========================================================================
    // Response Interceptors
    // ========================================================================
    
    // 1. Convert response data from snake_case to camelCase
    this.client.interceptors.response.use(
      (response) => {
        if (response.data) {
          response.data = convertKeysToCamel(response.data);
        }
        return response;
      },
      (error) => {
        if (error.response?.status === 401) {
          useAuthStore.getState().logout();
        }
        
        // Check for network error
        if ((!error.response || error.code === 'ERR_NETWORK') && window.location.pathname !== '/network-error') {
          window.location.href = '/network-error';
          return new Promise(() => {});
        }

        const message = error.response?.data?.detail || error.message || 'API Error';
        console.error('API Request Failed:', message);
        return Promise.reject(new Error(message));
      }
    );
  }

  // ==========================================================================
  // Auth APIs
  // ==========================================================================

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
    const response = await this.client.post<User>('/register', { email, password, fullName });
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
    const response = await this.client.post<User>('/system/setup', { email, password, fullName });
    return response.data;
  }

  async refreshToken(): Promise<LoginResponse> {
    const response = await this.client.post<LoginResponse>('/login/refresh-token');
    return response.data;
  }

  // ==========================================================================
  // System APIs
  // ==========================================================================

  async getAvailableTypes(): Promise<AvailableTypes> {
    const response = await this.client.get<AvailableTypes>('/system/types');
    return response.data;
  }

  // ==========================================================================
  // Dataset APIs (for data annotation)
  // ==========================================================================

  async getDatasets(): Promise<Dataset[]> {
    const response = await this.client.get<Dataset[]>('/datasets');
    return response.data;
  }

  async getDataset(id: string): Promise<Dataset | undefined> {
    const response = await this.client.get<Dataset>(`/datasets/${id}`);
    return response.data;
  }

  async createDataset(dataset: Omit<Dataset, 'id' | 'createdAt' | 'updatedAt' | 'sampleCount' | 'labeledCount'>): Promise<Dataset> {
    const response = await this.client.post<Dataset>('/datasets', dataset);
    return response.data;
  }

  async updateDataset(id: string, dataset: Partial<Dataset>): Promise<Dataset> {
    const response = await this.client.put<Dataset>(`/datasets/${id}`, dataset);
    return response.data;
  }

  async deleteDataset(id: string): Promise<void> {
    await this.client.delete(`/datasets/${id}`);
  }

  async getDatasetStats(id: string): Promise<{
    datasetId: string;
    totalSamples: number;
    labeledSamples: number;
    unlabeledSamples: number;
    skippedSamples: number;
    completionRate: number;
    linkedProjects: number;
  }> {
    const response = await this.client.get(`/datasets/${id}/stats`);
    return response.data;
  }

  async exportDataset(id: string, format: string = 'json', includeUnlabeled: boolean = false): Promise<any> {
    const response = await this.client.get(`/datasets/${id}/export`, {
      params: { format, includeUnlabeled }
    });
    return response.data;
  }

  // ==========================================================================
  // Label APIs (for dataset annotation labels)
  // ==========================================================================

  async getLabels(datasetId: string): Promise<Label[]> {
    const response = await this.client.get<Label[]>(`/datasets/${datasetId}/labels`);
    return response.data;
  }

  async createLabel(datasetId: string, label: LabelCreate): Promise<Label> {
    const response = await this.client.post<Label>(`/datasets/${datasetId}/labels`, label);
    return response.data;
  }

  async createLabelsBatch(datasetId: string, labels: LabelCreate[]): Promise<Label[]> {
    const response = await this.client.post<Label[]>(`/datasets/${datasetId}/labels/batch`, labels);
    return response.data;
  }

  async updateLabel(labelId: string, label: LabelUpdate): Promise<Label> {
    const response = await this.client.put<Label>(`/datasets/labels/${labelId}`, label);
    return response.data;
  }

  async deleteLabel(labelId: string, force: boolean = false): Promise<{ ok: boolean; deletedLabel: string; deletedAnnotations: number }> {
    const response = await this.client.delete(`/datasets/labels/${labelId}`, {
      params: { force }
    });
    return response.data;
  }

  // ==========================================================================
  // Project APIs (for active learning)
  // ==========================================================================

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

  // ==========================================================================
  // Sample APIs (belong to Dataset)
  // ==========================================================================

  async getSamples(datasetId: string): Promise<Sample[]> {
    const response = await this.client.get<{ items: Sample[] }>(`/samples/${datasetId}`);
    return response.data.items;
  }

  async getSample(sampleId: string): Promise<Sample | undefined> {
    const response = await this.client.get<Sample>(`/samples/item/${sampleId}`);
    return response.data;
  }

  async uploadSamplesWithProgress(
    datasetId: string,
    files: File[],
    onProgress?: UploadProgressCallback,
    signal?: AbortSignal
  ): Promise<UploadResult> {
    const formData = new FormData();
    files.forEach(file => formData.append('files', file));

    const token = useAuthStore.getState().token;
    const response = await fetch(`http://localhost:8000/api/v1/samples/${datasetId}/stream`, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${token}`,
      },
      body: formData,
      signal,
    });

    if (!response.ok) {
      throw new Error(`Upload failed: ${response.statusText}`);
    }

    const reader = response.body?.getReader();
    if (!reader) {
      throw new Error('No response body');
    }

    const decoder = new TextDecoder();
    let buffer = '';
    let finalResult: UploadResult = { uploaded: 0, errors: 0, results: [] };

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        if (line.startsWith('data: ')) {
          try {
            const event: UploadProgressEvent = JSON.parse(line.slice(6));
            onProgress?.(event);

            // Capture the final result from the complete event
            if (event.event === 'complete') {
              finalResult = {
                uploaded: event.uploaded || 0,
                errors: event.errors || 0,
                results: event.results || [],
              };
            }
          } catch (e) {
            console.error('Failed to parse SSE event:', e);
          }
        }
      }
    }

    return finalResult;
  }

  async getSampleAnnotations(sampleId: string): Promise<SampleAnnotationsResponse> {
    const response = await this.client.get<SampleAnnotationsResponse>(`/annotations/${sampleId}`);
    return response.data;
  }

  async syncAnnotations(sampleId: string, actions: SyncAction[]): Promise<SyncResponse> {
    const response = await this.client.post<SyncResponse>('/annotations/sync', {
      sampleId,
      actions,
    });
    return response.data;
  }

  async saveAnnotations(sampleId: string, annotations: Annotation[], updateStatus?: 'labeled' | 'skipped'): Promise<BatchSaveResult> {
    const response = await this.client.post<BatchSaveResult>('/annotations/save', {
      sampleId,
      annotations,
      updateStatus,
    });
    return response.data;
  }

  // ==========================================================================
  // Dataset Member APIs (for permission management)
  // ==========================================================================

  async getDatasetMembers(datasetId: string): Promise<DatasetMember[]> {
    const response = await this.client.get<DatasetMember[]>(`/datasets/${datasetId}/members`);
    return response.data;
  }

  async addDatasetMember(datasetId: string, member: DatasetMemberCreate): Promise<DatasetMember> {
    const response = await this.client.post<DatasetMember>(`/datasets/${datasetId}/members`, member);
    return response.data;
  }

  async updateDatasetMemberRole(datasetId: string, userId: string, memberUpdate: DatasetMemberUpdate): Promise<DatasetMember> {
    const response = await this.client.put<DatasetMember>(`/datasets/${datasetId}/members/${userId}`, memberUpdate);
    return response.data;
  }

  async removeDatasetMember(datasetId: string, userId: string): Promise<{ ok: boolean; message: string }> {
    const response = await this.client.delete(`/datasets/${datasetId}/members/${userId}`);
    return response.data;
  }

  // ==========================================================================
  // Config APIs
  // ==========================================================================

  async getStrategies(): Promise<QueryStrategy[]> {
    const response = await this.client.get<QueryStrategy[]>('/configs/strategies');
    return response.data;
  }

  async getBaseModels(): Promise<BaseModel[]> {
    const response = await this.client.get<BaseModel[]>('/configs/base-models');
    return response.data;
  }

  // ==========================================================================
  // Training APIs
  // ==========================================================================

  async trainProject(projectId: string): Promise<void> {
    await this.client.post(`/projects/${projectId}/train`);
  }

  async querySamples(projectId: string, n: number): Promise<Sample[]> {
    const response = await this.client.post<Sample[]>(`/projects/${projectId}/query`, { n });
    return response.data;
  }

  async getModelVersions(projectId: string): Promise<ModelVersion[]> {
    const response = await this.client.get<ModelVersion[]>(`/projects/${projectId}/models`);
    return response.data;
  }

  // ==========================================================================
  // User APIs
  // ==========================================================================

  async getUsers(skip: number = 0, limit: number = 100): Promise<User[]> {
    const response = await this.client.get<User[]>('/users/', { params: { skip, limit } });
    return response.data;
  }

  async createUser(user: Partial<User> & { password: string; globalRole?: GlobalRole }): Promise<User> {
    const response = await this.client.post<User>('/users/', user);
    return response.data;
  }

  async updateUser(id: string, user: Partial<User> & { password?: string; globalRole?: GlobalRole }): Promise<User> {
    const response = await this.client.put<User>(`/users/${id}`, user);
    return response.data;
  }

  async deleteUser(id: string): Promise<void> {
    await this.client.delete(`/users/${id}`);
  }
}
