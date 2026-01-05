import axios, { AxiosInstance, InternalAxiosRequestConfig } from 'axios';
import { Project, Sample, Annotation, QueryStrategy, BaseModel, ModelVersion, User, LoginResponse, AvailableTypes, Dataset, Label, LabelCreate, LabelUpdate, UploadProgressEvent, UploadResult, SyncAction, SyncResponse, BatchSaveResult, SampleAnnotationsResponse, DatasetMember, DatasetMemberCreate, DatasetMemberUpdate, GlobalRole } from '../../types';
import { ApiService, UploadProgressCallback } from './interface';
import { useAuthStore } from '../../store/authStore';
import { hashPassword, enforceHttps } from '../../utils/security';

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
// Error Handling Utilities
// ============================================================================

/**
 * 统一提取错误消息的函数
 * 支持多种错误响应格式：
 * 1. 统一格式：{ success: false, message: "..." }
 * 2. FastAPI默认格式：{ detail: "..." }（包括权限错误 403）
 * 3. 其他格式：{ message: "..." } 或字符串
 */
function extractErrorMessage(error: any): string {
  // 处理网络错误（没有响应的情况）
  if (!error.response) {
    if (error.code === 'ERR_NETWORK') {
      return 'Network error. Please check your connection.';
    }
    // 没有响应但也不是网络错误，返回原始错误消息
    return error.message || 'API Error';
  }

  // 尝试从响应数据中提取错误消息
  if (error.response.data) {
    // 如果响应体是字符串，直接返回
    if (typeof error.response.data === 'string') {
      return error.response.data;
    }
    
    const data = convertKeysToCamel(error.response.data) as any;
    
    // 检查是否为统一格式的错误响应
    if (data && typeof data === 'object' && 'success' in data && data.success === false) {
      return data.message || 'API Error';
    }
    
    // FastAPI 默认错误格式（包括权限错误 403）
    if (data && typeof data === 'object' && 'detail' in data) {
      const detail = data.detail;
      // detail 可能是字符串或数组
      if (Array.isArray(detail)) {
        // 处理验证错误数组（Pydantic 验证错误）
        const messages = detail.map((item: any) => {
          if (typeof item === 'object' && item.msg) {
            return `${item.loc?.join('.') || ''}: ${item.msg}`;
          }
          return String(item);
        });
        return messages.join('; ');
      }
      return String(detail);
    }
    
    // 其他可能的错误消息字段
    if (data && typeof data === 'object' && 'message' in data) {
      return String(data.message);
    }
    
    // 如果转换后的数据是字符串
    if (typeof data === 'string') {
      return data;
    }
  }

  // 回退到错误对象的消息
  return error.message || 'API Error';
}

/**
 * 创建标准化的错误对象
 */
function createApiError(error: any): Error {
  const message = extractErrorMessage(error);
  const apiError = new Error(message);
  // 保留原始错误信息以便调试
  (apiError as any).originalError = error;
  (apiError as any).statusCode = error.response?.status;
  return apiError;
}

// ============================================================================
// Password Handling Utilities
// ============================================================================

/**
 * 包装需要密码哈希的函数
 * 自动执行 enforceHttps 和密码哈希处理
 */
async function withPasswordHashing<T>(
  fn: (hashedPassword: string) => Promise<T>,
  password: string
): Promise<T> {
  enforceHttps();
  const hashedPassword = await hashPassword(password);
  return fn(hashedPassword);
}

/**
 * 包装需要多个密码哈希的函数（如 changePassword）
 */
async function withPasswordHashingMultiple<T>(
  fn: (hashedOldPassword: string, hashedNewPassword: string) => Promise<T>,
  oldPassword: string,
  newPassword: string
): Promise<T> {
  enforceHttps();
  const hashedOldPassword = await hashPassword(oldPassword);
  const hashedNewPassword = await hashPassword(newPassword);
  return fn(hashedOldPassword, hashedNewPassword);
}

/**
 * 包装需要可选密码哈希的用户数据函数
 */
async function withOptionalPasswordHashing<T>(
  fn: (userData: any) => Promise<T>,
  userData: any
): Promise<T> {
  enforceHttps();
  const processedData = { ...userData };
  if (processedData.password) {
    processedData.password = await hashPassword(processedData.password);
  }
  return fn(processedData);
}

// ============================================================================
// API Service Implementation
// ============================================================================

export class RealApiService implements ApiService {
  private client: AxiosInstance;
  private readonly apiBaseUrl: string;

  constructor() {
    // 从环境变量读取 API 地址，如果没有则使用默认值
    this.apiBaseUrl = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api/v1';
    
    this.client = axios.create({
      baseURL: this.apiBaseUrl,
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
    
    // 1. Handle unified response format and convert snake_case to camelCase
    this.client.interceptors.response.use(
      (response) => {
        if (response.data) {
          // Convert snake_case to camelCase first
          const convertedData = convertKeysToCamel(response.data);
          
          // Check if this is a unified response format (has success field)
          if (convertedData && typeof convertedData === 'object' && 'success' in convertedData) {
            // This is a unified response format
            const unifiedData = convertedData as any;
            if (unifiedData.success === false) {
              // Error response in unified format - should not happen in success response
              // but handle it gracefully
              return Promise.reject(createApiError({ response: { data: unifiedData } }));
            }
            // Success response: extract data field
            response.data = unifiedData.data;
          } else {
            // Not unified format, use converted data as-is
            response.data = convertedData;
          }
        }
        return response;
      },
      (error) => {
        // Handle 401 Unauthorized - logout user
        if (error.response?.status === 401) {
          useAuthStore.getState().logout();
        }
        
        // Handle network errors - redirect to network error page
        if ((!error.response || error.code === 'ERR_NETWORK') && window.location.pathname !== '/network-error') {
          // 保存当前路径，以便恢复后可以返回
          const currentPath = window.location.pathname;
          if (currentPath !== '/network-error') {
            sessionStorage.setItem('networkErrorReturnPath', currentPath);
          }
          window.location.href = '/network-error';
          return new Promise(() => {});
        }

        // Extract and reject with standardized error
        const apiError = createApiError(error);
        // 不在这里输出日志，由全局错误处理器统一处理
        return Promise.reject(apiError);
      }
    );
  }

  // ==========================================================================
  // Auth APIs
  // ==========================================================================

  async login(username: string, password: string): Promise<LoginResponse> {
    return withPasswordHashing(async (hashedPassword) => {
      const formData = new URLSearchParams();
      formData.append('username', username);
      formData.append('password', hashedPassword);
      
      const response = await this.client.post<LoginResponse>('/login/access-token', formData, {
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' }
      });
      return response.data;
    }, password);
  }

  async register(email: string, password: string, fullName?: string): Promise<User> {
    return withPasswordHashing(async (hashedPassword) => {
      const response = await this.client.post<User>('/register', { email, password: hashedPassword, fullName });
      return response.data;
    }, password);
  }

  async getCurrentUser(): Promise<User> {
    const response = await this.client.get<User>('/users/me');
    return response.data;
  }

  async changePassword(oldPassword: string, newPassword: string): Promise<{ message: string }> {
    return withPasswordHashingMultiple(async (hashedOldPassword, hashedNewPassword) => {
      const response = await this.client.post<{ message: string }>('/change-password', {
        old_password: hashedOldPassword,
        new_password: hashedNewPassword
      });
      return response.data;
    }, oldPassword, newPassword);
  }

  async getSystemStatus(): Promise<{ initialized: boolean }> {
    const response = await this.client.get<{ initialized: boolean }>('/system/status');
    return response.data;
  }

  async setupSystem(email: string, password: string, fullName?: string): Promise<User> {
    return withPasswordHashing(async (hashedPassword) => {
      const response = await this.client.post<User>('/system/setup', { email, password: hashedPassword, fullName });
      return response.data;
    }, password);
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

  async createDataset(dataset: Omit<Dataset, 'id' | 'createdAt' | 'updatedAt' | 'sampleCount' | 'labeledCount' | 'ownerId'>): Promise<Dataset> {
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
    const params = new URLSearchParams();
    if (options?.status) {
      params.append('status', options.status);
    }
    if (options?.skip !== undefined) {
      params.append('skip', options.skip.toString());
    }
    if (options?.limit !== undefined) {
      params.append('limit', options.limit.toString());
    }
    if (options?.sortBy) {
      params.append('sort_by', options.sortBy);
    }
    if (options?.sortOrder) {
      params.append('sort_order', options.sortOrder);
    }
    
    const queryString = params.toString();
    const url = `/samples/${datasetId}${queryString ? `?${queryString}` : ''}`;
    const response = await this.client.get<{ items: Sample[] }>(url);
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
    const response = await fetch(`${this.apiBaseUrl}/samples/${datasetId}/stream`, {
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
            // 静默处理 SSE 解析错误，避免控制台噪音
            // 如果需要调试，可以在开发环境下启用
            if (typeof window !== 'undefined' && 
                (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1')) {
              console.warn('Failed to parse SSE event:', e);
            }
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
    return withOptionalPasswordHashing(async (userData) => {
      const response = await this.client.post<User>('/users/', userData);
      return response.data;
    }, user);
  }

  async updateUser(id: string, user: Partial<User> & { password?: string; globalRole?: GlobalRole }): Promise<User> {
    return withOptionalPasswordHashing(async (userData) => {
      const response = await this.client.put<User>(`/users/${id}`, userData);
      return response.data;
    }, user);
  }

  async deleteUser(id: string): Promise<void> {
    await this.client.delete(`/users/${id}`);
  }

  // ==========================================================================
  // Utility Methods
  // ==========================================================================

  /**
   * 获取 API 基础 URL
   * @returns API 基础 URL
   */
  getApiBaseUrl(): string {
    return this.apiBaseUrl;
  }
}
