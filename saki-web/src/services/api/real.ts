import axios, { AxiosInstance, InternalAxiosRequestConfig } from 'axios';
import {
  // Auth types
  User, LoginResponse,
  // Permission types
  Role, RoleCreate, RoleUpdate, RoleType,
  UserSystemRole, UserSystemRoleAssign,
  SystemPermissions, ResourcePermissions,
  // L1 types
  Dataset, DatasetCreate, DatasetUpdate,
  Sample,
  AvailableTypesResponse,
} from '../../types';
import { ApiService } from './interface';
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

    // Track if we're currently refreshing to avoid multiple refresh calls
    let isRefreshing = false;
    let failedQueue: Array<{
      resolve: (value?: any) => void;
      reject: (reason?: any) => void;
    }> = [];

    const processQueue = (error: any, token: string | null = null) => {
      failedQueue.forEach((prom) => {
        if (error) {
          prom.reject(error);
        } else {
          prom.resolve(token);
        }
      });
      failedQueue = [];
    };

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
      async (error) => {
        const originalRequest = error.config;

        // Handle 401 Unauthorized - try to refresh token
        if (error.response?.status === 401 && !originalRequest._retry) {
          if (isRefreshing) {
            // If already refreshing, queue this request
            return new Promise((resolve, reject) => {
              failedQueue.push({ resolve, reject });
            })
              .then((token) => {
                originalRequest.headers.Authorization = `Bearer ${token}`;
                return this.client(originalRequest);
              })
              .catch((err) => {
                return Promise.reject(err);
              });
          }

          originalRequest._retry = true;
          isRefreshing = true;

          const refreshToken = useAuthStore.getState().refreshToken;
          if (!refreshToken) {
            // No refresh token, logout user
            useAuthStore.getState().logout();
            processQueue(error, null);
            return Promise.reject(error);
          }

          try {
            const response = await this.client.post<LoginResponse>('/auth/login/refresh-token', {
              token: refreshToken,
            });
            const { accessToken, refreshToken: newRefreshToken } = response.data;
            
            // Update tokens in store
            useAuthStore.getState().setTokens(accessToken, newRefreshToken);
            
            // Update the original request with new token
            originalRequest.headers.Authorization = `Bearer ${accessToken}`;
            
            // Process queued requests
            processQueue(null, accessToken);
            
            // Retry the original request
            return this.client(originalRequest);
          } catch (refreshError) {
            // Refresh failed, logout user
            processQueue(refreshError, null);
            useAuthStore.getState().logout();
            return Promise.reject(refreshError);
          } finally {
            isRefreshing = false;
          }
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
      
      const response = await this.client.post<LoginResponse>('/auth/login/access-token', formData, {
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' }
      });
      return response.data;
    }, password);
  }

  async register(email: string, password: string, fullName?: string): Promise<User> {
    return withPasswordHashing(async (hashedPassword) => {
      const response = await this.client.post<User>('/auth/register', { email, password: hashedPassword, fullName });
      return response.data;
    }, password);
  }

  async getCurrentUser(): Promise<User> {
    const response = await this.client.get<User>('/users/me');
    return response.data;
  }

  async changePassword(oldPassword: string, newPassword: string): Promise<{ message: string }> {
    return withPasswordHashingMultiple(async (hashedOldPassword, hashedNewPassword) => {
      const response = await this.client.post<{ message: string }>('/auth/change-password', {
        old_password: hashedOldPassword,
        new_password: hashedNewPassword
      });
      return response.data;
    }, oldPassword, newPassword);
  }

  async refreshToken(): Promise<LoginResponse> {
    const refreshToken = useAuthStore.getState().refreshToken;
    if (!refreshToken) {
      throw new Error('No refresh token available');
    }
    const response = await this.client.post<LoginResponse>('/auth/login/refresh-token', {
      token: refreshToken,
    });
    return response.data;
  }

  // ==========================================================================
  // System APIs
  // ==========================================================================

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

  async getAvailableTypes(): Promise<AvailableTypesResponse> {
    const response = await this.client.get<AvailableTypesResponse>('/system/types');
    return response.data;
  }

  // ==========================================================================
  // Permission APIs
  // ==========================================================================

  async getSystemPermissions(): Promise<SystemPermissions> {
    const response = await this.client.get<SystemPermissions>('/permissions/system');
    return response.data;
  }

  async getResourcePermissions(resourceType: string, resourceId: string): Promise<ResourcePermissions> {
    const response = await this.client.get<ResourcePermissions>('/permissions/resource', {
      params: {
        resource_type: resourceType,
        resource_id: resourceId,
      },
    });
    return response.data;
  }

  async getRoles(type?: RoleType): Promise<Role[]> {
    const params: Record<string, string> = {};
    if (type) params.type = type;
    
    const response = await this.client.get<Role[]>('/roles', { params });
    return response.data;
  }

  async getRole(roleId: string): Promise<Role> {
    const response = await this.client.get<Role>(`/roles/${roleId}`);
    return response.data;
  }

  async createRole(role: RoleCreate): Promise<Role> {
    const response = await this.client.post<Role>('/roles', role);
    return response.data;
  }

  async updateRole(roleId: string, role: RoleUpdate): Promise<Role> {
    const response = await this.client.put<Role>(`/roles/${roleId}`, role);
    return response.data;
  }

  async deleteRole(roleId: string): Promise<{ ok: boolean; message: string }> {
    const response = await this.client.delete(`/roles/${roleId}`);
    return response.data;
  }

  async getUserRoles(userId: string): Promise<UserSystemRole[]> {
    const response = await this.client.get<UserSystemRole[]>(`/roles/users/${userId}/roles`);
    return response.data;
  }

  async assignUserRole(userId: string, role: UserSystemRoleAssign): Promise<UserSystemRole> {
    const response = await this.client.post<UserSystemRole>(`/roles/users/${userId}/roles`, role);
    return response.data;
  }

  async revokeUserRole(userId: string, roleId: string): Promise<{ ok: boolean; message: string }> {
    const response = await this.client.delete(`/roles/users/${userId}/roles/${roleId}`);
    return response.data;
  }

  // ==========================================================================
  // Dataset APIs
  // ==========================================================================

  async getDatasets(): Promise<Dataset[]> {
    const response = await this.client.get<Dataset[]>('/datasets');
    return response.data;
  }

  async getDataset(id: string): Promise<Dataset | undefined> {
    const response = await this.client.get<Dataset>(`/datasets/${id}`);
    return response.data;
  }

  async createDataset(dataset: DatasetCreate): Promise<Dataset> {
    const response = await this.client.post<Dataset>('/datasets', dataset);
    return response.data;
  }

  async updateDataset(id: string, dataset: Partial<DatasetUpdate>): Promise<Dataset> {
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
    memberCount: number;
  }> {
    // TODO: Implement when backend endpoint is available
    // For now, return mock data
    return {
      datasetId: id,
      totalSamples: 0,
      labeledSamples: 0,
      unlabeledSamples: 0,
      skippedSamples: 0,
      completionRate: 0,
      linkedProjects: 0,
      memberCount: 1,
    };
  }

  async exportDataset(id: string, format?: string, includeUnlabeled?: boolean): Promise<any> {
    // TODO: Implement when backend endpoint is available
    const response = await this.client.get(`/datasets/${id}/export`, {
      params: { format, include_unlabeled: includeUnlabeled }
    });
    return response.data;
  }

  // ==========================================================================
  // Sample APIs
  // ==========================================================================

  async getSamples(datasetId: string, options?: { offset?: number; limit?: number; sortBy?: string; sortOrder?: 'asc' | 'desc'; skip?: number }): Promise<Sample[]> {
    const offset = options?.offset ?? options?.skip;
    const params: Record<string, any> = {
      offset,
      limit: options?.limit,
      sort_by: options?.sortBy,
      sort_order: options?.sortOrder,
    };
    const response = await this.client.get<Sample[]>(`/samples/${datasetId}/samples`, {
      params
    });
    return response.data;
  }

  async deleteSample(datasetId: string, sampleId: string): Promise<void> {
    await this.client.delete(`/samples/${datasetId}/samples/${sampleId}`);
  }

  async uploadSamplesWithProgress(
    datasetId: string,
    files: File[],
    onProgress: (event: any) => void,
    signal?: AbortSignal
  ): Promise<void> {
    const formData = new FormData();
    files.forEach(file => {
      formData.append('files', file);
    });

    const token = useAuthStore.getState().token;
    const response = await fetch(
      `${this.apiBaseUrl}/samples/${datasetId}/stream`,
      {
        method: 'POST',
        body: formData,
        headers: {
          'Authorization': `Bearer ${token}`,
        },
        signal,
      }
    );

    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }

    // Parse Server-Sent Events (SSE)
    const reader = response.body?.getReader();
    if (!reader) {
      throw new Error('Response body is not readable');
    }

    const decoder = new TextDecoder();
    let buffer = '';

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');

        // Process complete lines
        for (let i = 0; i < lines.length - 1; i++) {
          const line = lines[i];
          if (line.startsWith('data: ')) {
            try {
              const data = JSON.parse(line.slice(6));
              onProgress(data);
            } catch (e) {
              console.error('Failed to parse SSE event:', line, e);
            }
          }
        }

        // Keep incomplete line in buffer
        buffer = lines[lines.length - 1];
      }
    } finally {
      reader.releaseLock();
    }
  }

  async getUsers(skip: number = 0, limit: number = 100): Promise<User[]> {
    const response = await this.client.get<User[]>('/users/', { params: { skip, limit } });
    return response.data;
  }

  async getUserList(skip: number = 0, limit: number = 100): Promise<{ id: string; email: string; fullName?: string }[]> {
    const response = await this.client.get<{ id: string; email: string; fullName?: string }[]>('/users/list', { params: { skip, limit } });
    return response.data;
  }

  async createUser(user: Partial<User> & { password: string }): Promise<User> {
    return withOptionalPasswordHashing(async (userData) => {
      const response = await this.client.post<User>('/users/', userData);
      return response.data;
    }, user);
  }

  async updateUser(id: string, user: Partial<User> & { password?: string }): Promise<User> {
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
