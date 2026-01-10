import {
  Project, Sample, Annotation, QueryStrategy, BaseModel, ModelVersion, User, LoginResponse,
  AvailableTypes, Dataset, Label, LabelCreate, LabelUpdate, UploadProgressEvent, UploadResult,
  SyncAction, SyncResponse, BatchSaveResult, SampleAnnotationsResponse,
  // Permission types
  Role, RoleCreate, RoleUpdate, RoleType,
  UserSystemRole, UserSystemRoleCreate,
  ResourceMember, ResourceMemberCreate, ResourceMemberUpdate,
  UserPermissions,
} from '../../types';

/**
 * Callback type for upload progress events
 */
export type UploadProgressCallback = (event: UploadProgressEvent) => void;

export interface ApiService {
  // ============================================================================
  // Auth
  // ============================================================================
  login(username: string, password: string): Promise<LoginResponse>;
  register(email: string, password: string, fullName?: string): Promise<User>;
  getCurrentUser(): Promise<User>;
  changePassword(oldPassword: string, newPassword: string): Promise<{ message: string }>;

  // ============================================================================
  // System
  // ============================================================================
  getSystemStatus(): Promise<{ initialized: boolean }>;
  setupSystem(email: string, password: string, fullName?: string): Promise<User>;
  refreshToken(): Promise<LoginResponse>;
  initRoles(): Promise<{ ok: boolean; roles_count: number; roles: string[] }>;
  
  // Types & Capabilities
  getAvailableTypes(): Promise<AvailableTypes>;

  // ============================================================================
  // Permission APIs
  // ============================================================================
  
  // Get current user's permissions
  getMyPermissions(resourceType?: string, resourceId?: string): Promise<UserPermissions>;
  
  // Role management
  getRoles(type?: RoleType): Promise<Role[]>;
  getRole(roleId: string): Promise<Role>;
  createRole(role: RoleCreate): Promise<Role>;
  updateRole(roleId: string, role: RoleUpdate): Promise<Role>;
  deleteRole(roleId: string): Promise<{ ok: boolean; message: string }>;
  
  // User role management
  getUserRoles(userId: string): Promise<UserSystemRole[]>;
  assignUserRole(userId: string, role: UserSystemRoleCreate): Promise<UserSystemRole>;
  revokeUserRole(userId: string, roleId: string): Promise<{ ok: boolean; message: string }>;

  // ============================================================================
  // Dataset APIs
  // ============================================================================
  getDatasets(): Promise<Dataset[]>;
  getDataset(id: string): Promise<Dataset | undefined>;
  createDataset(dataset: Omit<Dataset, 'id' | 'createdAt' | 'updatedAt' | 'sampleCount' | 'labeledCount' | 'ownerId'>): Promise<Dataset>;
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
    memberCount: number;
  }>;
  exportDataset(id: string, format?: string, includeUnlabeled?: boolean): Promise<any>;

  // ============================================================================
  // Label APIs
  // ============================================================================
  getLabels(datasetId: string): Promise<Label[]>;
  createLabel(datasetId: string, label: LabelCreate): Promise<Label>;
  createLabelsBatch(datasetId: string, labels: LabelCreate[]): Promise<Label[]>;
  updateLabel(labelId: string, label: LabelUpdate): Promise<Label>;
  deleteLabel(labelId: string, force?: boolean): Promise<{ ok: boolean; deletedLabel: string; deletedAnnotations: number }>;

  // ============================================================================
  // Sample APIs
  // ============================================================================
  getSamples(datasetId: string, options?: {
    status?: 'unlabeled' | 'labeled' | 'skipped';
    skip?: number;
    limit?: number;
    sortBy?: 'name' | 'status' | 'created_at' | 'updated_at' | 'remark';
    sortOrder?: 'asc' | 'desc';
  }): Promise<Sample[]>;
  getSample(sampleId: string): Promise<Sample | undefined>;
  uploadSamplesWithProgress(
    datasetId: string,
    files: File[],
    onProgress?: UploadProgressCallback,
    signal?: AbortSignal
  ): Promise<UploadResult>;
  
  // ============================================================================
  // Annotation APIs
  // ============================================================================
  getSampleAnnotations(sampleId: string): Promise<SampleAnnotationsResponse>;
  syncAnnotations(sampleId: string, actions: SyncAction[]): Promise<SyncResponse>;
  saveAnnotations(sampleId: string, annotations: Annotation[], updateStatus?: 'labeled' | 'skipped'): Promise<BatchSaveResult>;
  
  // ============================================================================
  // Dataset Member APIs (Resource Members)
  // ============================================================================
  getDatasetMembers(datasetId: string): Promise<ResourceMember[]>;
  addDatasetMember(datasetId: string, member: ResourceMemberCreate): Promise<ResourceMember>;
  updateDatasetMemberRole(datasetId: string, userId: string, memberUpdate: ResourceMemberUpdate): Promise<ResourceMember>;
  removeDatasetMember(datasetId: string, userId: string): Promise<{ ok: boolean; message: string }>;
  getAvailableDatasetRoles(datasetId: string): Promise<{ id: string; name: string; displayName: string; description?: string }[]>;
  
  // ============================================================================
  // Config APIs
  // ============================================================================
  getStrategies(): Promise<QueryStrategy[]>;
  getBaseModels(): Promise<BaseModel[]>;

  // ============================================================================
  // Project APIs (for active learning)
  // ============================================================================
  getProjects(): Promise<Project[]>;
  getProject(id: string): Promise<Project | undefined>;
  createProject(project: Omit<Project, 'id' | 'createdAt' | 'stats'>): Promise<Project>;
  updateProject(id: string, project: Partial<Project>): Promise<Project>;
  deleteProject(id: string): Promise<void>;
  trainProject(projectId: string): Promise<void>;
  querySamples(projectId: string, n: number): Promise<Sample[]>;
  getModelVersions(projectId: string): Promise<ModelVersion[]>;

  // ============================================================================
  // User Management
  // ============================================================================
  getUsers(skip?: number, limit?: number): Promise<User[]>;
  getUserList(skip?: number, limit?: number): Promise<{ id: string; email: string; fullName?: string }[]>;
  createUser(user: Partial<User> & { password: string }): Promise<User>;
  updateUser(id: string, user: Partial<User> & { password?: string }): Promise<User>;
  deleteUser(id: string): Promise<void>;
}
