import axios, {AxiosInstance, InternalAxiosRequestConfig} from 'axios';
import {
    AnnotationDraftCommitRequest,
    AnnotationDraftPayload,
    AnnotationDraftRead,
    AnnotationRead,
    AnnotationSyncRequest,
    AnnotationSyncResponse,
    Loop,
    AvailableTypesResponse,
    CommitDiff,
    CommitHistoryItem,
    CommitRead,
    CommitResult,
    Dataset,
    DatasetCreate,
    DatasetUpdate,
    LoginResponse,
    PaginationResponse,
    Project,
    ProjectBranch,
    ProjectCreate,
    ProjectForkCreate,
    ProjectLabel,
    ProjectLabelCreate,
    ProjectLabelUpdate,
    ProjectSample,
    RoundSelectionApplyRequest,
    RoundSelectionApplyResponse,
    RoundSelectionRead,
    RuntimeRound,
    RuntimeRoundCommandResponse,
    RuntimeRoundArtifactsResponse,
    RuntimeStep,
    RuntimeStepArtifactsResponse,
    RuntimeStepCandidate,
    RuntimeStepCommandResponse,
    RuntimeStepEvent,
    RuntimeRoundEvent,
    RoundEventQuery,
    RoundEventQueryResponse,
    StepEventQuery,
    StepEventQueryResponse,
    RuntimeStepMetricPoint,
    StepArtifactDownload,
    LoopCreateRequest,
    LoopActionRequest,
    LoopActionResponse,
    LoopSnapshotRead,
    LoopGateResponse,
    RoundMissingSamplesQuery,
    RoundMissingSamplesResponse,
    PredictionSetApplyRequest,
    PredictionSetApplyResponse,
    PredictionSetDetailRead,
    PredictionSetGenerateRequest,
    PredictionSetRead,
    RoundPredictionCleanupResponse,
    LoopUpdateRequest,
    LoopSummary,
    SimulationComparison,
    SimulationExperimentCreateRequest,
    SimulationExperimentCreateResponse,
    RuntimePluginCatalogResponse,
    RuntimeExecutorListResponse,
    RuntimeExecutorRead,
    RuntimeExecutorStatsRange,
    RuntimeExecutorStatsResponse,
    ProjectModel,
    ModelArtifactDownload,
    ResourceMember,
    ResourceMemberCreate,
    ResourceMemberUpdate,
    ResourcePermissions,
    Role,
    RoleCreate,
    RolePermissionCatalog,
    RoleInfo,
    RoleType,
    RoleUpdate,
    Sample,
    SystemSettingsBundle,
    SystemStatus,
    SystemPermissions,
    User,
    UserSystemRole,
    UserSystemRoleAssign,
    ImportDryRunResponse,
    ImportExecuteRequest,
    ImportProgressEvent,
    ImportTaskCreateResponse,
    ImportTaskStatusResponse,
    SampleBulkImportRequest,
    UploadProgressEvent,
    AnnotationBulkRequest,
    ProjectAnnotationImportDryRunRequest,
    ProjectAssociatedImportDryRunRequest,
    ProjectIOCapabilities,
    ProjectExportResolveRequest,
    ProjectExportResolveResponse,
    ProjectExportChunkRequest,
    ProjectExportChunkResponse,
} from '../../types';
import {ApiService} from './interface';
import {useAuthStore} from '../../store/authStore';
import {hydrateAnnotationRead, hydrateDraftPayload} from '../../utils/annotationGeometry';
import {enforceHttps, hashPassword} from '../../utils/security';
import {normalizeRuntimeRoundEvent, normalizeRuntimeStepEvent} from '../../pages/project/loops/runtimeEventFormatter';

// ============================================================================
// Case Conversion Utilities
// ============================================================================

/** Convert snake_case string to camelCase */
function snakeToCamel(str: string): string {
    if (str.includes('.')) {
        return str;
    }
    return str.replace(/_([a-z])/g, (_, letter) => letter.toUpperCase());
}

/** Convert camelCase string to snake_case */
function camelToSnake(str: string): string {
    if (str.includes('.')) {
        return str;
    }
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
    const processedData = {...userData};
    if (processedData.password) {
        processedData.password = await hashPassword(processedData.password);
    }
    return fn(processedData);
}

function normalizeLoop(loop: Loop): Loop {
    return {
        ...loop,
        lifecycle: (loop as any).lifecycle,
        gate: (loop as any).gate ?? undefined,
        lastRoundId: (loop as any).lastRoundId ?? null,
        config: (loop as any).config ?? {plugin: {}},
    };
}

function normalizeLoopSummary(summary: LoopSummary): LoopSummary {
    return {
        ...summary,
        lifecycle: (summary as any).lifecycle,
        roundsTotal: (summary as any).roundsTotal ?? 0,
        attemptsTotal: (summary as any).attemptsTotal ?? 0,
        roundsSucceeded: (summary as any).roundsSucceeded ?? 0,
        stepsTotal: (summary as any).stepsTotal ?? 0,
        stepsSucceeded: (summary as any).stepsSucceeded ?? 0,
    };
}

function normalizeRound(round: RuntimeRound): RuntimeRound {
    return {
        ...round,
        state: (round as any).state ?? 'pending',
        attemptIndex: Number((round as any).attemptIndex ?? 1),
        awaitingConfirm: Boolean((round as any).awaitingConfirm ?? false),
        stepCounts: (round as any).stepCounts ?? {},
        roundType: (round as any).roundType ?? 'loop_round',
        inputCommitId: (round as any).inputCommitId ?? null,
        outputCommitId: (round as any).outputCommitId ?? null,
        retryOfRoundId: (round as any).retryOfRoundId ?? null,
        retryReason: (round as any).retryReason ?? null,
        confirmedAt: (round as any).confirmedAt ?? null,
        confirmedCommitId: (round as any).confirmedCommitId ?? null,
        confirmedRevealedCount: Number((round as any).confirmedRevealedCount ?? 0),
        confirmedSelectedCount: Number((round as any).confirmedSelectedCount ?? 0),
        confirmedEffectiveMinRequired: Number((round as any).confirmedEffectiveMinRequired ?? 0),
        lastError: (round as any).lastError ?? (round as any).terminalReason ?? null,
        resolvedParams: (round as any).resolvedParams ?? {},
    };
}

function normalizeStepEvent(event: any): RuntimeStepEvent {
    return normalizeRuntimeStepEvent(event);
}

function normalizeStepEventQueryResponse(response: any): StepEventQueryResponse {
    const itemsRaw = Array.isArray(response?.items) ? response.items : [];
    const facetsRaw = response?.facets && typeof response.facets === 'object' ? response.facets : null;
    return {
        items: itemsRaw.map((item: any) => normalizeStepEvent(item)),
        nextAfterSeq: response?.nextAfterSeq ?? response?.next_after_seq ?? null,
        facets: facetsRaw
            ? {
                eventTypes: facetsRaw.eventTypes ?? facetsRaw.event_types ?? {},
                levels: facetsRaw.levels ?? {},
                tags: facetsRaw.tags ?? {},
            }
            : null,
    };
}

function normalizeRoundEvent(event: any): RuntimeRoundEvent | null {
    return normalizeRuntimeRoundEvent(event);
}

function normalizeRoundEventQueryResponse(response: any): RoundEventQueryResponse {
    const itemsRaw = Array.isArray(response?.items) ? response.items : [];
    return {
        items: itemsRaw
            .map((item: any) => normalizeRoundEvent(item))
            .filter((item: RuntimeRoundEvent | null): item is RuntimeRoundEvent => Boolean(item)),
        nextAfterCursor: response?.nextAfterCursor ?? response?.next_after_cursor ?? null,
        hasMore: Boolean(response?.hasMore ?? response?.has_more ?? false),
    };
}

function normalizeRoundCommandResponse(response: RuntimeRoundCommandResponse): RuntimeRoundCommandResponse {
    return {
        ...response,
        roundId: (response as any).roundId,
    };
}

function normalizeStepCommandResponse(response: RuntimeStepCommandResponse): RuntimeStepCommandResponse {
    return {
        ...response,
        stepId: (response as any).stepId,
    };
}

function normalizeRuntimePluginCatalog(response: RuntimePluginCatalogResponse): RuntimePluginCatalogResponse {
    return {
        ...response,
        items: (response.items || []).map((item: any) => ({
            ...item,
            supportedStepTypes: item.supportedStepTypes ?? [],
        })),
    };
}

function normalizeRuntimeExecutor(executor: RuntimeExecutorRead): RuntimeExecutorRead {
    const pluginIds = (executor.pluginIds || {}) as Record<string, any>;
    const plugins = Array.isArray(pluginIds.plugins)
        ? pluginIds.plugins.map((plugin: any) => ({
            ...plugin,
            supportedStepTypes: plugin.supportedStepTypes ?? [],
        }))
        : pluginIds.plugins;
    return {
        ...executor,
        currentStepId: (executor as any).currentStepId ?? null,
        pluginIds: {
            ...pluginIds,
            plugins,
        },
    };
}

function normalizeRuntimeExecutorList(response: RuntimeExecutorListResponse): RuntimeExecutorListResponse {
    return {
        ...response,
        items: (response.items || []).map((item) => normalizeRuntimeExecutor(item)),
    };
}

function normalizeProjectModel(model: ProjectModel): ProjectModel {
    return {
        ...model,
        roundId: (model as any).roundId ?? null,
        inputCommitId: (model as any).inputCommitId ?? null,
    };
}

function resolveUploadFile(fileLike: unknown): File {
    if (fileLike instanceof File) {
        return fileLike;
    }
    if (fileLike && typeof fileLike === 'object') {
        const candidate = fileLike as Record<string, unknown>;
        if (candidate.originFileObj instanceof File) {
            return candidate.originFileObj;
        }
        if (candidate.file instanceof File) {
            return candidate.file;
        }
    }
    throw new Error('Invalid upload file, please re-select the ZIP file.');
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
                if (config.data instanceof FormData) {
                    // Let browser set multipart boundary automatically.
                    if (config.headers && typeof (config.headers as any).set === 'function') {
                        (config.headers as any).set('Content-Type', undefined);
                    } else if (config.headers) {
                        delete (config.headers as any)['Content-Type'];
                        delete (config.headers as any)['content-type'];
                    }
                    return config;
                }
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
                            return Promise.reject(createApiError({response: {data: unifiedData}}));
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
                            failedQueue.push({resolve, reject});
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
                        const {accessToken, refreshToken: newRefreshToken} = response.data;

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
                    return new Promise(() => {
                    });
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
                headers: {'Content-Type': 'application/x-www-form-urlencoded'}
            });
            return response.data;
        }, password);
    }

    async register(email: string, password: string, fullName?: string): Promise<User> {
        return withPasswordHashing(async (hashedPassword) => {
            const response = await this.client.post<User>('/auth/register', {
                email,
                password: hashedPassword,
                fullName
            });
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

    async getSystemStatus(): Promise<SystemStatus> {
        const response = await this.client.get<SystemStatus>('/system/status');
        return response.data;
    }

    async setupSystem(email: string, password: string, fullName?: string): Promise<User> {
        return withPasswordHashing(async (hashedPassword) => {
            const response = await this.client.post<User>('/system/setup', {email, password: hashedPassword, fullName});
            return response.data;
        }, password);
    }

    async getAvailableTypes(): Promise<AvailableTypesResponse> {
        const response = await this.client.get<AvailableTypesResponse>('/system/types');
        return response.data;
    }

    async getSystemSettingsBundle(): Promise<SystemSettingsBundle> {
        const response = await this.client.get<SystemSettingsBundle>('/system/settings/bundle');
        return response.data;
    }

    async updateSystemSettings(values: Record<string, unknown>): Promise<SystemSettingsBundle> {
        const response = await this.client.patch<SystemSettingsBundle>('/system/settings', {values});
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

    async getPermissionCatalog(): Promise<RolePermissionCatalog> {
        const response = await this.client.get<RolePermissionCatalog>('/roles/permission-catalog');
        return response.data;
    }

    async getRoles(type?: RoleType, page: number = 1, limit: number = 50): Promise<PaginationResponse<Role>> {
        const params: Record<string, any> = {page, limit};
        if (type) params.type = type;

        const response = await this.client.get<PaginationResponse<Role>>('/roles', {params});
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

    async getDatasets(page: number = 1, limit: number = 20, q?: string): Promise<PaginationResponse<Dataset>> {
        const response = await this.client.get<PaginationResponse<Dataset>>('/datasets', {params: {page, limit, q}});
        return response.data;
    }

    async getDataset(id: string): Promise<Dataset | undefined> {
        const response = await this.client.get<Dataset>(`/datasets/${id}`);
        return response.data;
    }

    async createDataset(dataset: DatasetCreate): Promise<void> {
        await this.client.post<Dataset>('/datasets', dataset);
    }

    async updateDataset(id: string, dataset: Partial<DatasetUpdate>): Promise<Dataset> {
        const response = await this.client.put<Dataset>(`/datasets/${id}`, dataset);
        return response.data;
    }

    async deleteDataset(id: string): Promise<void> {
        await this.client.delete(`/datasets/${id}`);
    }

    // ==========================================================================
    // Dataset Member Management APIs
    // ==========================================================================

    async getDatasetMembers(datasetId: string): Promise<ResourceMember[]> {
        const response = await this.client.get<ResourceMember[]>(`/datasets/${datasetId}/members`);
        return response.data;
    }

    async addDatasetMember(datasetId: string, member: ResourceMemberCreate): Promise<ResourceMember> {
        const response = await this.client.post<ResourceMember>(`/datasets/${datasetId}/members`, member);
        return response.data;
    }

    async updateDatasetMemberRole(datasetId: string, userId: string, member: ResourceMemberUpdate): Promise<ResourceMember> {
        const response = await this.client.put<ResourceMember>(`/datasets/${datasetId}/members/${userId}`, member);
        return response.data;
    }

    async removeDatasetMember(datasetId: string, userId: string): Promise<{ ok: boolean; message: string }> {
        const response = await this.client.delete<{ ok: boolean; message: string }>(
            `/datasets/${datasetId}/members/${userId}`
        );
        return response.data;
    }

    async getAvailableDatasetRoles(datasetId: string): Promise<RoleInfo[]> {
        const response = await this.client.get<RoleInfo[]>(`/datasets/${datasetId}/available-roles`);
        return response.data;
    }

    // ==========================================================================
    // Project APIs
    // ==========================================================================

    async getProjects(page: number = 1, limit: number = 20): Promise<PaginationResponse<Project>> {
        const response = await this.client.get<PaginationResponse<Project>>('/projects', {params: {page, limit}});
        return response.data;
    }

    async createProject(payload: ProjectCreate): Promise<Project> {
        const response = await this.client.post<Project>('/projects', payload);
        return response.data;
    }

    async forkProject(projectId: string, payload: ProjectForkCreate): Promise<Project> {
        const response = await this.client.post<Project>(`/projects/${projectId}/fork`, payload);
        return response.data;
    }

    async getProject(id: string): Promise<Project> {
        const response = await this.client.get<Project>(`/projects/${id}`);
        return response.data;
    }

    async updateProject(projectId: string, payload: Partial<Project>): Promise<Project> {
        const response = await this.client.put<Project>(`/projects/${projectId}`, payload);
        return response.data;
    }

    async archiveProject(projectId: string): Promise<Project> {
        const response = await this.client.post<Project>(`/projects/${projectId}:archive`);
        return response.data;
    }

    async unarchiveProject(projectId: string): Promise<Project> {
        const response = await this.client.post<Project>(`/projects/${projectId}:unarchive`);
        return response.data;
    }

    async getProjectDatasets(projectId: string): Promise<string[]> {
        const response = await this.client.get<string[]>(`/projects/${projectId}/datasets`);
        return response.data;
    }

    async getProjectDatasetDetails(projectId: string): Promise<Dataset[]> {
        const response = await this.client.get<Dataset[]>(`/projects/${projectId}/datasets/detail`);
        return response.data;
    }

    async linkProjectDatasets(projectId: string, datasetIds: string[]): Promise<string[]> {
        const response = await this.client.post<string[]>(`/projects/${projectId}/datasets`, {
            datasetIds,
        });
        return response.data;
    }

    async unlinkProjectDatasets(projectId: string, datasetIds: string[]): Promise<number> {
        const response = await this.client.delete<number>(`/projects/${projectId}/datasets`, {
            data: {datasetIds},
        });
        return response.data;
    }

    async getProjectBranches(projectId: string): Promise<ProjectBranch[]> {
        const response = await this.client.get<ProjectBranch[]>(`/branches/projects/${projectId}/branches`);
        return response.data;
    }

    async getProjectIOCapabilities(projectId: string): Promise<ProjectIOCapabilities> {
        const response = await this.client.get<ProjectIOCapabilities>(`/projects/${projectId}/io-capabilities`);
        return response.data;
    }

    async resolveProjectExport(
        projectId: string,
        payload: ProjectExportResolveRequest,
        signal?: AbortSignal,
    ): Promise<ProjectExportResolveResponse> {
        const response = await this.client.post<ProjectExportResolveResponse>(
            `/projects/${projectId}/exports/resolve`,
            convertKeysToSnake(payload),
            {signal},
        );
        return convertKeysToCamel<ProjectExportResolveResponse>(response.data);
    }

    async getProjectExportChunk(
        projectId: string,
        payload: ProjectExportChunkRequest,
        signal?: AbortSignal,
    ): Promise<ProjectExportChunkResponse> {
        const response = await this.client.post<ProjectExportChunkResponse>(
            `/projects/${projectId}/exports/chunk`,
            convertKeysToSnake(payload),
            {signal},
        );
        return convertKeysToCamel<ProjectExportChunkResponse>(response.data);
    }

    async getProjectLoops(projectId: string): Promise<Loop[]> {
        const response = await this.client.get<Loop[]>(`/projects/${projectId}/loops`);
        return response.data.map((item) => normalizeLoop(item));
    }

    async createProjectLoop(projectId: string, payload: LoopCreateRequest): Promise<Loop> {
        const response = await this.client.post<Loop>(`/projects/${projectId}/loops`, payload);
        return normalizeLoop(response.data);
    }

    async getLoopById(loopId: string): Promise<Loop> {
        const response = await this.client.get<Loop>(`/loops/${loopId}`);
        return normalizeLoop(response.data);
    }

    async updateLoop(loopId: string, payload: LoopUpdateRequest): Promise<Loop> {
        const response = await this.client.patch<Loop>(`/loops/${loopId}`, payload);
        return normalizeLoop(response.data);
    }

    async actLoop(loopId: string, payload: LoopActionRequest): Promise<LoopActionResponse> {
        const response = await this.client.post<LoopActionResponse>(`/loops/${loopId}:act`, payload ?? {});
        return {
            ...response.data,
            lifecycle: (response.data as any).lifecycle,
            actions: (response.data as any).actions ?? [],
            primaryAction: (response.data as any).primaryAction ?? null,
            executedAction: (response.data as any).executedAction ?? null,
            commandId: (response.data as any).commandId ?? null,
            decisionToken: (response.data as any).decisionToken ?? '',
            blockingReasons: (response.data as any).blockingReasons ?? [],
        };
    }

    async getLoopSnapshot(loopId: string): Promise<LoopSnapshotRead> {
        const response = await this.client.get<LoopSnapshotRead>(`/loops/${loopId}/snapshot`);
        return response.data;
    }

    async getLoopGate(loopId: string): Promise<LoopGateResponse> {
        const response = await this.client.get<LoopGateResponse>(`/loops/${loopId}/gate`);
        return {
            ...response.data,
            actions: (response.data as any).actions ?? [],
            primaryAction: (response.data as any).primaryAction ?? null,
            decisionToken: (response.data as any).decisionToken ?? '',
            blockingReasons: (response.data as any).blockingReasons ?? [],
        };
    }

    async generatePredictionSet(loopId: string, payload: PredictionSetGenerateRequest): Promise<PredictionSetRead> {
        const response = await this.client.post<PredictionSetRead>(
            `/loops/${loopId}/prediction-sets:generate`,
            payload ?? {},
        );
        return response.data;
    }

    async listPredictionSets(loopId: string, limit: number = 100): Promise<PredictionSetRead[]> {
        const response = await this.client.get<PredictionSetRead[]>(`/loops/${loopId}/prediction-sets`, {
            params: {limit},
        });
        return response.data;
    }

    async getPredictionSetDetail(predictionSetId: string, itemLimit: number = 1000): Promise<PredictionSetDetailRead> {
        const response = await this.client.get<PredictionSetDetailRead>(`/prediction-sets/${predictionSetId}`, {
            params: {item_limit: itemLimit},
        });
        return response.data;
    }

    async applyPredictionSet(
        predictionSetId: string,
        payload: PredictionSetApplyRequest,
    ): Promise<PredictionSetApplyResponse> {
        const response = await this.client.post<PredictionSetApplyResponse>(
            `/prediction-sets/${predictionSetId}:apply`,
            payload ?? {},
        );
        return response.data;
    }

    async cleanupRoundPredictions(loopId: string, roundIndex: number): Promise<RoundPredictionCleanupResponse> {
        const response = await this.client.post<RoundPredictionCleanupResponse>(
            `/loops/${loopId}/rounds/${roundIndex}:cleanup-predictions`,
        );
        return response.data;
    }

    async getLoopSummary(loopId: string): Promise<LoopSummary> {
        const response = await this.client.get<LoopSummary>(`/loops/${loopId}/summary`);
        return normalizeLoopSummary(response.data);
    }

    async createSimulationExperiment(
        projectId: string,
        payload: SimulationExperimentCreateRequest
    ): Promise<SimulationExperimentCreateResponse> {
        const response = await this.client.post<SimulationExperimentCreateResponse>(
            `/projects/${projectId}/simulation-experiments`,
            payload,
        );
        return response.data;
    }

    async getSimulationExperimentComparison(
        groupId: string,
        metricName: string = 'map50',
    ): Promise<SimulationComparison> {
        const response = await this.client.get<SimulationComparison>(
            `/simulation-experiments/${groupId}/comparison`,
            {params: {metric_name: metricName}},
        );
        return response.data;
    }

    async getRuntimePlugins(): Promise<RuntimePluginCatalogResponse> {
        const response = await this.client.get<RuntimePluginCatalogResponse>('/runtime/plugins');
        return normalizeRuntimePluginCatalog(response.data);
    }

    async getLoopRounds(loopId: string, limit: number = 50): Promise<RuntimeRound[]> {
        const response = await this.client.get<RuntimeRound[]>(`/loops/${loopId}/rounds`, {params: {limit}});
        return response.data.map((item) => normalizeRound(item));
    }

    async stopRound(roundId: string, reason: string = 'user requested stop'): Promise<RuntimeRoundCommandResponse> {
        const response = await this.client.post<RuntimeRoundCommandResponse>(`/rounds/${roundId}:stop`, null, {params: {reason}});
        return normalizeRoundCommandResponse(response.data);
    }

    async getRound(roundId: string): Promise<RuntimeRound> {
        const response = await this.client.get<RuntimeRound>(`/rounds/${roundId}`);
        return normalizeRound(response.data);
    }

    async getRoundSelection(roundId: string): Promise<RoundSelectionRead> {
        const response = await this.client.get<RoundSelectionRead>(`/rounds/${roundId}/selection`);
        return response.data;
    }

    async applyRoundSelection(
        roundId: string,
        payload: RoundSelectionApplyRequest
    ): Promise<RoundSelectionApplyResponse> {
        const response = await this.client.post<RoundSelectionApplyResponse>(
            `/rounds/${roundId}/selection:apply`,
            payload ?? {},
        );
        return response.data;
    }

    async resetRoundSelection(roundId: string): Promise<RoundSelectionApplyResponse> {
        const response = await this.client.post<RoundSelectionApplyResponse>(`/rounds/${roundId}/selection:reset`);
        return response.data;
    }

    async getRoundMissingSamples(
        loopId: string,
        roundId: string,
        params: RoundMissingSamplesQuery = {},
    ): Promise<RoundMissingSamplesResponse> {
        const response = await this.client.get<RoundMissingSamplesResponse>(
            `/loops/${loopId}/rounds/${roundId}/missing-samples`,
            {
                params: {
                    dataset_id: params.datasetId,
                    q: params.q,
                    sort_by: params.sortBy,
                    sort_order: params.sortOrder,
                    page: params.page,
                    limit: params.limit,
                },
            },
        );
        return response.data;
    }

    async getRoundSteps(roundId: string, limit: number = 2000): Promise<RuntimeStep[]> {
        const response = await this.client.get<RuntimeStep[]>(`/rounds/${roundId}/steps`, {params: {limit}});
        return response.data;
    }

    async getRoundArtifacts(roundId: string, limit: number = 2000): Promise<RuntimeRoundArtifactsResponse> {
        const response = await this.client.get<RuntimeRoundArtifactsResponse>(`/rounds/${roundId}/artifacts`, {
            params: {limit},
        });
        return response.data;
    }

    async getRoundEvents(roundId: string, query: RoundEventQuery = {}): Promise<RoundEventQueryResponse> {
        const params: Record<string, any> = {
            limit: Number(query.limit ?? 5000),
        };
        if (query.afterCursor) {
            params.after_cursor = String(query.afterCursor);
        }
        if (query.stages && query.stages.length > 0) {
            params.stages = query.stages.join(',');
        }
        const response = await this.client.get(`/rounds/${roundId}/events`, {params});
        return normalizeRoundEventQueryResponse(response.data);
    }

    async getStep(stepId: string): Promise<RuntimeStep> {
        const response = await this.client.get<RuntimeStep>(`/steps/${stepId}`);
        return response.data;
    }

    async stopStep(stepId: string, reason: string = 'user requested stop'): Promise<RuntimeStepCommandResponse> {
        const response = await this.client.post<RuntimeStepCommandResponse>(`/steps/${stepId}:stop`, null, {params: {reason}});
        return normalizeStepCommandResponse(response.data);
    }

    async getStepEvents(stepId: string, query: StepEventQuery = {}): Promise<StepEventQueryResponse> {
        const params: Record<string, any> = {
            after_seq: Number(query.afterSeq ?? 0),
            limit: Number(query.limit ?? 5000),
            include_facets: Boolean(query.includeFacets ?? false),
        };
        if (query.eventTypes && query.eventTypes.length > 0) {
            params.event_types = query.eventTypes.join(',');
        }
        if (query.levels && query.levels.length > 0) {
            params.levels = query.levels.join(',');
        }
        if (query.tags && query.tags.length > 0) {
            params.tags = query.tags.join(',');
        }
        if (query.q) {
            params.q = String(query.q);
        }
        if (query.fromTs) {
            params.from_ts = String(query.fromTs);
        }
        if (query.toTs) {
            params.to_ts = String(query.toTs);
        }
        const response = await this.client.get(
            `/steps/${stepId}/events`,
            {params},
        );
        return normalizeStepEventQueryResponse(response.data);
    }

    async getStepMetricSeries(stepId: string, limit: number = 5000): Promise<RuntimeStepMetricPoint[]> {
        const response = await this.client.get<RuntimeStepMetricPoint[]>(`/steps/${stepId}/metrics/series`, {params: {limit}});
        return response.data;
    }

    async getStepCandidates(stepId: string, limit: number = 200): Promise<RuntimeStepCandidate[]> {
        const response = await this.client.get<RuntimeStepCandidate[]>(`/steps/${stepId}/candidates`, {params: {limit}});
        return response.data;
    }

    async getStepArtifacts(stepId: string): Promise<RuntimeStepArtifactsResponse> {
        const response = await this.client.get<RuntimeStepArtifactsResponse>(`/steps/${stepId}/artifacts`);
        return response.data;
    }

    async getStepArtifactDownloadUrl(
        stepId: string,
        artifactName: string,
        expiresInHours: number = 2
    ): Promise<StepArtifactDownload> {
        const response = await this.client.get<StepArtifactDownload>(
            `/steps/${stepId}/artifacts/${artifactName}:download-url`,
            {params: {expires_in_hours: expiresInHours}}
        );
        return response.data;
    }

    async getRuntimeExecutors(): Promise<RuntimeExecutorListResponse> {
        const response = await this.client.get<RuntimeExecutorListResponse>('/runtime/executors');
        return normalizeRuntimeExecutorList(response.data);
    }

    async getRuntimeExecutorStats(range: RuntimeExecutorStatsRange): Promise<RuntimeExecutorStatsResponse> {
        const response = await this.client.get<RuntimeExecutorStatsResponse>('/runtime/executors/stats', {
            params: {range},
        });
        return response.data;
    }

    async getRuntimeExecutor(executorId: string): Promise<RuntimeExecutorRead> {
        const response = await this.client.get<RuntimeExecutorRead>(`/runtime/executors/${executorId}`);
        return normalizeRuntimeExecutor(response.data);
    }

    async registerModelFromRound(
        projectId: string,
        payload: {
            roundId: string;
            name?: string;
            versionTag?: string;
            status?: string;
        }
    ): Promise<ProjectModel> {
        const response = await this.client.post<ProjectModel>(
            `/projects/${projectId}/models:register-from-round`,
            payload,
        );
        return normalizeProjectModel(response.data);
    }

    async getProjectModels(projectId: string, limit: number = 100): Promise<ProjectModel[]> {
        const response = await this.client.get<ProjectModel[]>(`/projects/${projectId}/models`, {params: {limit}});
        return response.data.map((item) => normalizeProjectModel(item));
    }

    async promoteModel(modelId: string, status: string = 'production'): Promise<ProjectModel> {
        const response = await this.client.post<ProjectModel>(`/models/${modelId}:promote`, {status});
        return normalizeProjectModel(response.data);
    }

    async getModelArtifactDownloadUrl(
        modelId: string,
        artifactName: string,
        expiresInHours: number = 2
    ): Promise<ModelArtifactDownload> {
        const response = await this.client.get<ModelArtifactDownload>(
            `/models/${modelId}/artifacts/${artifactName}:download-url`,
            {params: {expires_in_hours: expiresInHours}}
        );
        return response.data;
    }

    async getAssetDownloadUrl(
        assetId: string,
        expiresInHours: number = 1,
        datasetId?: string,
    ): Promise<{
        assetId: string;
        downloadUrl: string;
        expiresIn: number;
        filename?: string;
    }> {
        const endpoint = datasetId
            ? `/assets/datasets/${datasetId}/assets/${assetId}/download-url`
            : `/assets/${assetId}/download-url`;
        const response = await this.client.get<{
            assetId: string;
            downloadUrl: string;
            expiresIn: number;
            filename?: string;
        }>(endpoint, {params: {expires_in_hours: expiresInHours}});
        return response.data;
    }

    async createProjectBranch(
        projectId: string,
        payload: {
            name: string;
            fromCommitId: string;
            description?: string;
        }
    ): Promise<ProjectBranch> {
        const response = await this.client.post<ProjectBranch>(
            `/branches/projects/${projectId}/branches`,
            null,
            {
                params: {
                    name: payload.name,
                    from_commit_id: payload.fromCommitId,
                    description: payload.description,
                },
            }
        );
        return response.data;
    }

    async updateBranch(
        projectId: string,
        branchId: string,
        payload: {
            name?: string;
            description?: string;
            isProtected?: boolean;
        }
    ): Promise<ProjectBranch> {
        const response = await this.client.put<ProjectBranch>(
            `/branches/projects/${projectId}/branches/${branchId}`,
            null,
            {
                params: {
                    name: payload.name,
                    description: payload.description,
                    is_protected: payload.isProtected,
                },
            }
        );
        return response.data;
    }

    async deleteBranch(projectId: string, branchId: string): Promise<void> {
        await this.client.delete(`/branches/projects/${projectId}/branches/${branchId}`);
    }

    async getProjectCommits(projectId: string): Promise<CommitHistoryItem[]> {
        const response = await this.client.get<CommitHistoryItem[]>(`/commits/projects/${projectId}/commits`);
        return response.data;
    }

    async getCommitHistory(commitId: string, depth: number = 100): Promise<CommitHistoryItem[]> {
        const response = await this.client.get<CommitHistoryItem[]>(
            `/commits/${commitId}/history`,
            {params: {depth}}
        );
        return response.data;
    }

    async getCommit(commitId: string): Promise<CommitRead> {
        const response = await this.client.get<CommitRead>(`/commits/${commitId}`);
        return response.data;
    }

    async getCommitDiff(commitId: string, compareWithId?: string): Promise<CommitDiff> {
        const response = await this.client.get<CommitDiff>(`/commits/${commitId}/diff`, {
            params: {
                compare_with_id: compareWithId,
            },
        });
        return response.data;
    }

    async getProjectMembers(projectId: string): Promise<ResourceMember[]> {
        const response = await this.client.get<ResourceMember[]>(`/projects/${projectId}/members`);
        return response.data;
    }

    async getAvailableProjectRoles(projectId: string): Promise<RoleInfo[]> {
        const response = await this.client.get<RoleInfo[]>(`/projects/${projectId}/available-roles`);
        return response.data;
    }

    async addProjectMember(projectId: string, member: ResourceMemberCreate): Promise<void> {
        await this.client.post(`/projects/${projectId}/members`, member);
    }

    async updateProjectMemberRole(projectId: string, userId: string, member: ResourceMemberUpdate): Promise<void> {
        await this.client.put(`/projects/${projectId}/members/${userId}`, member);
    }

    async removeProjectMember(projectId: string, userId: string): Promise<void> {
        await this.client.delete(`/projects/${projectId}/members/${userId}`);
    }

    async getProjectLabels(projectId: string): Promise<ProjectLabel[]> {
        const response = await this.client.get<ProjectLabel[]>(`/labels/projects/${projectId}/labels`);
        return response.data;
    }

    async createProjectLabel(projectId: string, payload: ProjectLabelCreate): Promise<ProjectLabel> {
        const response = await this.client.post<ProjectLabel>(
            `/labels/projects/${projectId}/labels`,
            {
                ...payload,
                projectId,
            }
        );
        return response.data;
    }

    async updateProjectLabel(projectId: string, labelId: string, payload: ProjectLabelUpdate): Promise<ProjectLabel> {
        const response = await this.client.put<ProjectLabel>(`/labels/projects/${projectId}/labels/${labelId}`, payload);
        return response.data;
    }

    async deleteProjectLabel(projectId: string, labelId: string): Promise<void> {
        await this.client.delete(`/labels/projects/${projectId}/labels/${labelId}`);
    }

    async reorderProjectLabels(projectId: string, labelIds: string[]): Promise<ProjectLabel[]> {
        const response = await this.client.post<ProjectLabel[]>(
            `/labels/projects/${projectId}/labels/reorder`,
            labelIds,
        );
        return response.data;
    }

    async getProjectSamples(
        projectId: string,
        datasetId: string,
        params: {
            q?: string;
            status?: 'all' | 'labeled' | 'unlabeled' | 'draft';
            branchName?: string;
            sortBy?: string;
            sortOrder?: 'asc' | 'desc';
            page?: number;
            limit?: number;
        }
    ): Promise<PaginationResponse<ProjectSample>> {
        const response = await this.client.get<PaginationResponse<ProjectSample>>(
            `/projects/${projectId}/datasets/${datasetId}/samples`,
            {
                params: {
                    q: params.q,
                    status: params.status,
                    branch_name: params.branchName,
                    sort_by: params.sortBy,
                    sort_order: params.sortOrder,
                    page: params.page,
                    limit: params.limit,
                },
            }
        );
        return response.data;
    }

    async getAnnotationsAtCommit(projectId: string, commitId: string, sampleId?: string): Promise<AnnotationRead[]> {
        const response = await this.client.get<AnnotationRead[]>(
            `/annotations/projects/${projectId}/commits/${commitId}/annotations`,
            {
                params: {
                    sample_id: sampleId,
                },
            }
        );
        return (response.data || []).map((item) => hydrateAnnotationRead(item));
    }

    async getWorkingAnnotations(
        projectId: string,
        sampleId: string,
        branchName?: string
    ): Promise<AnnotationDraftPayload | null> {
        const response = await this.client.get<AnnotationDraftPayload | null>(
            `/annotations/projects/${projectId}/samples/${sampleId}/working`,
            {
                params: {
                    branch_name: branchName,
                },
            }
        );
        return hydrateDraftPayload(response.data);
    }

    async upsertWorkingAnnotations(
        projectId: string,
        sampleId: string,
        payload: AnnotationDraftPayload & { branchName?: string }
    ): Promise<void> {
        await this.client.put(
            `/annotations/projects/${projectId}/samples/${sampleId}/working`,
            payload
        );
    }

    async syncWorkingToDraft(
        projectId: string,
        sampleId: string,
        branchName?: string,
        reviewEmpty?: boolean
    ): Promise<AnnotationDraftRead | null> {
        const response = await this.client.post<AnnotationDraftRead | null>(
            `/annotations/projects/${projectId}/samples/${sampleId}/drafts/sync`,
            null,
            {
                params: {
                    branch_name: branchName,
                    review_empty: reviewEmpty,
                },
            }
        );
        return response.data ?? null;
    }

    async listAnnotationDrafts(
        projectId: string,
        branchName?: string,
        sampleId?: string
    ): Promise<AnnotationDraftRead[]> {
        const response = await this.client.get<AnnotationDraftRead[]>(
            `/annotations/projects/${projectId}/drafts`,
            {
                params: {
                    branch_name: branchName,
                    sample_id: sampleId,
                },
            }
        );
        return (response.data || []).map((item) => ({
            ...item,
            payload: hydrateDraftPayload(item.payload) || {annotations: [], meta: {}},
        }));
    }

    async commitAnnotationDrafts(
        projectId: string,
        payload: AnnotationDraftCommitRequest
    ): Promise<CommitResult> {
        const response = await this.client.post<CommitResult>(
            `/annotations/projects/${projectId}/drafts/commit`,
            payload
        );
        return response.data;
    }

    async syncAnnotation(
        projectId: string,
        sampleId: string,
        payload: AnnotationSyncRequest
    ): Promise<AnnotationSyncResponse> {
        const response = await this.client.post<AnnotationSyncResponse>(
            `/annotations/projects/${projectId}/samples/${sampleId}/sync`,
            payload
        );
        return {
            ...response.data,
            payload: hydrateDraftPayload(response.data?.payload) || {annotations: [], meta: {}},
        };
    }

    // ==========================================================================
    // Import APIs
    // ==========================================================================

    async dryRunDatasetImageImport(
        datasetId: string,
        file: File,
        options?: {
            pathFlattenMode?: 'basename' | 'preserve_path';
            nameCollisionPolicy?: 'abort' | 'auto_rename' | 'overwrite';
        },
    ): Promise<ImportDryRunResponse> {
        const formData = new FormData();
        formData.append('file', resolveUploadFile(file));
        formData.append('path_flatten_mode', options?.pathFlattenMode || 'basename');
        formData.append('name_collision_policy', options?.nameCollisionPolicy || 'abort');
        const response = await this.client.post<ImportDryRunResponse>(
            `/datasets/${datasetId}/imports/images:dry-run`,
            formData,
        );
        return response.data;
    }

    async executeDatasetImageImport(
        datasetId: string,
        payload: ImportExecuteRequest,
    ): Promise<ImportTaskCreateResponse> {
        const response = await this.client.post<ImportTaskCreateResponse>(
            `/datasets/${datasetId}/imports/images:execute`,
            convertKeysToSnake(payload),
        );
        return convertKeysToCamel<ImportTaskCreateResponse>(response.data);
    }

    async dryRunProjectAnnotationImport(
        projectId: string,
        payload: ProjectAnnotationImportDryRunRequest
    ): Promise<ImportDryRunResponse> {
        const formData = new FormData();
        formData.append('file', resolveUploadFile(payload.file));
        formData.append('format_profile', payload.formatProfile);
        formData.append('dataset_id', payload.datasetId);
        formData.append('branch_name', payload.branchName);
        formData.append('path_flatten_mode', payload.pathFlattenMode || 'basename');
        formData.append('name_collision_policy', payload.nameCollisionPolicy || 'abort');

        const response = await this.client.post<ImportDryRunResponse>(
            `/projects/${projectId}/imports/annotations:dry-run`,
            formData,
        );
        return response.data;
    }

    async executeProjectAnnotationImport(
        projectId: string,
        payload: ImportExecuteRequest,
    ): Promise<ImportTaskCreateResponse> {
        const response = await this.client.post<ImportTaskCreateResponse>(
            `/projects/${projectId}/imports/annotations:execute`,
            convertKeysToSnake(payload),
        );
        return convertKeysToCamel<ImportTaskCreateResponse>(response.data);
    }

    async dryRunProjectAssociatedImport(
        projectId: string,
        payload: ProjectAssociatedImportDryRunRequest
    ): Promise<ImportDryRunResponse> {
        const formData = new FormData();
        formData.append('file', resolveUploadFile(payload.file));
        formData.append('format_profile', payload.formatProfile);
        formData.append('branch_name', payload.branchName);
        formData.append('path_flatten_mode', payload.pathFlattenMode || 'basename');
        formData.append('name_collision_policy', payload.nameCollisionPolicy || 'abort');
        formData.append('target_dataset_mode', payload.targetDatasetMode);
        if (payload.targetDatasetId) formData.append('target_dataset_id', payload.targetDatasetId);
        if (payload.newDatasetName) formData.append('new_dataset_name', payload.newDatasetName);
        if (payload.newDatasetDescription) formData.append('new_dataset_description', payload.newDatasetDescription);

        const response = await this.client.post<ImportDryRunResponse>(
            `/projects/${projectId}/imports/associated:dry-run`,
            formData,
        );
        return response.data;
    }

    async executeProjectAssociatedImport(
        projectId: string,
        payload: ImportExecuteRequest,
    ): Promise<ImportTaskCreateResponse> {
        const response = await this.client.post<ImportTaskCreateResponse>(
            `/projects/${projectId}/imports/associated:execute`,
            convertKeysToSnake(payload),
        );
        return convertKeysToCamel<ImportTaskCreateResponse>(response.data);
    }

    async getImportTaskStatus(taskId: string): Promise<ImportTaskStatusResponse> {
        const response = await this.client.get<ImportTaskStatusResponse>(`/imports/tasks/${taskId}`);
        return convertKeysToCamel<ImportTaskStatusResponse>(response.data);
    }

    async streamImportTaskEvents(
        taskId: string,
        afterSeq: number,
        onProgress: (event: ImportProgressEvent) => void,
        signal?: AbortSignal
    ): Promise<void> {
        const token = useAuthStore.getState().token;
        const headers: Record<string, string> = {};
        if (token) headers.Authorization = `Bearer ${token}`;

        const response = await fetch(
            `${this.apiBaseUrl}/imports/tasks/${taskId}/events?after_seq=${Math.max(0, afterSeq)}`,
            {
                method: 'GET',
                headers: Object.keys(headers).length > 0 ? headers : undefined,
                signal,
            },
        );
        if (!response.ok) {
            const errorText = await response.text().catch(() => '');
            throw new Error(errorText || `HTTP error! status: ${response.status}`);
        }

        const reader = response.body?.getReader();
        if (!reader) {
            throw new Error('Response body is not readable');
        }

        const decoder = new TextDecoder();
        let buffer = '';
        try {
            while (true) {
                const {done, value} = await reader.read();
                if (done) break;

                buffer += decoder.decode(value, {stream: true});
                const lines = buffer.split('\n');
                for (let i = 0; i < lines.length - 1; i++) {
                    const line = lines[i].trim();
                    if (!line || line.startsWith(':')) continue;
                    if (!line.startsWith('data: ')) continue;
                    const raw = line.slice(6).trim();
                    if (!raw) continue;
                    try {
                        const parsed = convertKeysToCamel<ImportProgressEvent>(JSON.parse(raw));
                        onProgress(parsed);
                    } catch (error) {
                        console.error('Failed to parse SSE event:', raw, error);
                    }
                }
                buffer = lines[lines.length - 1];
            }
        } finally {
            reader.releaseLock();
        }
    }

    async bulkUploadSamples(
        datasetId: string,
        files: File[],
    ): Promise<ImportTaskCreateResponse> {
        const formData = new FormData();
        files.forEach((file) => {
            formData.append('files', resolveUploadFile(file));
        });
        const response = await this.client.post<ImportTaskCreateResponse>(
            `/datasets/${datasetId}/samples:bulk-upload`,
            formData,
        );
        return convertKeysToCamel<ImportTaskCreateResponse>(response.data);
    }

    async bulkImportSamples(
        datasetId: string,
        payload: SampleBulkImportRequest,
    ): Promise<ImportTaskCreateResponse> {
        const response = await this.client.post<ImportTaskCreateResponse>(
            `/datasets/${datasetId}/samples:bulk-import`,
            convertKeysToSnake(payload),
        );
        return convertKeysToCamel<ImportTaskCreateResponse>(response.data);
    }

    async bulkSaveAnnotations(
        projectId: string,
        payload: AnnotationBulkRequest,
    ): Promise<ImportTaskCreateResponse> {
        const response = await this.client.post<ImportTaskCreateResponse>(
            `/projects/${projectId}/annotations:bulk`,
            convertKeysToSnake(payload),
        );
        return convertKeysToCamel<ImportTaskCreateResponse>(response.data);
    }

    // ==========================================================================
    // Sample APIs
    // ==========================================================================

    async getSamples(
        datasetId: string,
        page?: number,
        limit?: number,
        sortBy?: string,
        sortOrder?: 'asc' | 'desc',
        q?: string
    ): Promise<PaginationResponse<Sample>> {
        const response = await this.client.get<PaginationResponse<Sample>>(
            `/samples/${datasetId}/samples`,
            {
                params: {
                    page: page ?? 1,
                    limit: limit,
                    sort_by: sortBy,
                    sort_order: sortOrder,
                    q,
                }
            }
        );
        return response.data;
    }

    async deleteSample(datasetId: string, sampleId: string, force?: boolean): Promise<void> {
        await this.client.delete(`/samples/${datasetId}/samples/${sampleId}`, {
            params: {
                force,
            },
        });
    }

    async uploadSamplesWithProgress(
        datasetId: string,
        files: File[],
        onProgress: (event: UploadProgressEvent) => void,
        signal?: AbortSignal
    ): Promise<void> {
        const formData = new FormData();
        files.forEach((file) => {
            formData.append('files', resolveUploadFile(file));
        });

        const token = useAuthStore.getState().token;
        const headers: Record<string, string> = {};
        if (token) headers.Authorization = `Bearer ${token}`;

        const response = await fetch(
            `${this.apiBaseUrl}/samples/${datasetId}/stream`,
            {
                method: 'POST',
                body: formData,
                headers: Object.keys(headers).length > 0 ? headers : undefined,
                signal,
            }
        );

        if (!response.ok) {
            const errorText = await response.text().catch(() => '');
            throw new Error(errorText || `HTTP error! status: ${response.status}`);
        }

        const reader = response.body?.getReader();
        if (!reader) {
            throw new Error('Response body is not readable');
        }

        const decoder = new TextDecoder();
        let buffer = '';

        try {
            while (true) {
                const {done, value} = await reader.read();
                if (done) break;

                buffer += decoder.decode(value, {stream: true});
                const lines = buffer.split('\n');

                for (let i = 0; i < lines.length - 1; i++) {
                    const line = lines[i].trim();
                    if (!line || line.startsWith(':')) continue;
                    if (!line.startsWith('data: ')) continue;
                    const raw = line.slice(6).trim();
                    if (!raw) continue;
                    try {
                        const parsed = convertKeysToCamel<UploadProgressEvent>(JSON.parse(raw));
                        onProgress(parsed);
                    } catch (error) {
                        console.error('Failed to parse SSE event:', raw, error);
                    }
                }

                buffer = lines[lines.length - 1];
            }
        } finally {
            reader.releaseLock();
        }
    }

    async getUsers(page: number = 1, limit: number = 100): Promise<PaginationResponse<User>> {
        const response = await this.client.get<PaginationResponse<User>>('/users', {params: {page, limit}});
        return response.data;
    }

    async getUserList(
        page: number = 1,
        limit: number = 100,
        q?: string,
        resourceType?: 'dataset' | 'project',
        resourceId?: string,
    ): Promise<PaginationResponse<{
        id: string;
        email: string;
        fullName?: string
    }>> {
        const params: Record<string, unknown> = {page, limit, q};
        if (resourceType && resourceId) {
            params.resource_type = resourceType;
            params.resource_id = resourceId;
        }
        const response = await this.client.get<PaginationResponse<{
            id: string;
            email: string;
            fullName?: string
        }>>('/users/list', {params});
        return response.data;
    }

    async createUser(user: Partial<User> & { password: string }): Promise<User> {
        return withOptionalPasswordHashing(async (userData) => {
            const response = await this.client.post<User>('/users', userData);
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

    async updateCurrentUser(user: Partial<User>): Promise<User> {
        const response = await this.client.patch<User>('/users/me', user);
        return response.data;
    }

    async uploadUserAvatar(file: File): Promise<User> {
        const formData = new FormData();
        formData.append('file', file);
        const response = await this.client.post<User>('/users/me/avatar', formData, {
            headers: {'Content-Type': 'multipart/form-data'},
        });
        return response.data;
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
