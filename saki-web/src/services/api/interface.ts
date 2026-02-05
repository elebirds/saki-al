import {
  // Auth types
  User, LoginResponse,
  // System types
  AvailableTypesResponse,
  // Permission types
  Role, RoleCreate, RoleUpdate, RoleType,
  UserSystemRole, UserSystemRoleAssign,
  ResourceMember, ResourceMemberCreate, ResourceMemberUpdate,
  SystemPermissions, ResourcePermissions,
  // Dataset types
  Dataset, DatasetCreate, DatasetUpdate,
  // Sample types
  Sample, RoleInfo,
  // Project types
  Project, ProjectBranch, CommitHistoryItem,
  ProjectLabel, ProjectLabelCreate, ProjectLabelUpdate,
  // Pagination
  PaginationResponse,
} from '../../types';


export interface ApiService {
  // ============================================================================
  // Auth
  // ============================================================================
  login(username: string, password: string): Promise<LoginResponse>;
  register(email: string, password: string, fullName?: string): Promise<User>;
  getCurrentUser(): Promise<User>;
  changePassword(oldPassword: string, newPassword: string): Promise<{ message: string }>;
  refreshToken(): Promise<LoginResponse>;

  // ============================================================================
  // System
  // ============================================================================
  getSystemStatus(): Promise<{ initialized: boolean }>;
  setupSystem(email: string, password: string, fullName?: string): Promise<User>;
  getAvailableTypes(): Promise<AvailableTypesResponse>;

  // ============================================================================
  // User Management
  // ============================================================================
  getUsers(page?: number, limit?: number): Promise<PaginationResponse<User>>;
  getUserList(page?: number, limit?: number): Promise<PaginationResponse<{ id: string; email: string; fullName?: string }>>;
  createUser(user: Partial<User> & { password: string }): Promise<User>;
  updateUser(id: string, user: Partial<User> & { password?: string }): Promise<User>;
  deleteUser(id: string): Promise<void>;
  updateCurrentUser(user: Partial<User>): Promise<User>;
  uploadUserAvatar(file: File): Promise<User>;

  // ============================================================================
  // Permission APIs
  // ============================================================================
  
  // Get system-level permissions
  getSystemPermissions(): Promise<SystemPermissions>;
  
  // Get resource-specific permissions
  getResourcePermissions(resourceType: string, resourceId: string): Promise<ResourcePermissions>;
  
  // Role management
  getRoles(type?: RoleType, page?: number, limit?: number): Promise<PaginationResponse<Role>>;
  getRole(roleId: string): Promise<Role>;
  createRole(role: RoleCreate): Promise<Role>;
  updateRole(roleId: string, role: RoleUpdate): Promise<Role>;
  deleteRole(roleId: string): Promise<{ ok: boolean; message: string }>;
  
  // User role management
  getUserRoles(userId: string): Promise<UserSystemRole[]>;
  assignUserRole(userId: string, role: UserSystemRoleAssign): Promise<UserSystemRole>;
  revokeUserRole(userId: string, roleId: string): Promise<{ ok: boolean; message: string }>;

  // ============================================================================
  // Dataset APIs
  // ============================================================================
  getDatasets(page?: number, limit?: number): Promise<PaginationResponse<Dataset>>;
  getDataset(id: string): Promise<Dataset | undefined>;
  createDataset(dataset: DatasetCreate): Promise<void>;
  updateDataset(id: string, dataset: Partial<DatasetUpdate>): Promise<Dataset>;
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
  // Dataset Members APIs
  // ============================================================================
  getDatasetMembers(datasetId: string): Promise<ResourceMember[]>;
  addDatasetMember(datasetId: string, member: ResourceMemberCreate): Promise<ResourceMember>;
  updateDatasetMemberRole(datasetId: string, userId: string, member: ResourceMemberUpdate): Promise<ResourceMember>;
  removeDatasetMember(datasetId: string, userId: string): Promise<{ ok: boolean; message: string }>;
  getAvailableDatasetRoles(datasetId: string): Promise<RoleInfo[]>;

  // ============================================================================
  // Project APIs
  // ============================================================================
  getProjects(page?: number, limit?: number): Promise<PaginationResponse<Project>>;
  getProject(id: string): Promise<Project>;
  updateProject(projectId: string, payload: Partial<Project>): Promise<Project>;
  getProjectDatasets(projectId: string): Promise<string[]>;
  getProjectBranches(projectId: string): Promise<ProjectBranch[]>;
  getProjectCommits(projectId: string): Promise<CommitHistoryItem[]>;
  getProjectMembers(projectId: string): Promise<ResourceMember[]>;
  addProjectMember(projectId: string, member: ResourceMemberCreate): Promise<void>;
  updateProjectMemberRole(projectId: string, userId: string, member: ResourceMemberUpdate): Promise<void>;
  removeProjectMember(projectId: string, userId: string): Promise<void>;
  getProjectLabels(projectId: string): Promise<ProjectLabel[]>;
  createProjectLabel(projectId: string, payload: ProjectLabelCreate): Promise<ProjectLabel>;
  updateProjectLabel(labelId: string, payload: ProjectLabelUpdate): Promise<ProjectLabel>;
  deleteProjectLabel(labelId: string): Promise<void>;
  
  // ============================================================================
  // Sample APIs
  // ============================================================================
  getSamples(datasetId: string,
    page?: number,
    limit?: number,
    sortBy?: string,
    sortOrder?: 'asc' | 'desc'
  ): Promise<PaginationResponse<Sample>>;
  deleteSample(datasetId: string, sampleId: string): Promise<void>;
  uploadSamplesWithProgress(
    datasetId: string,
    files: File[],
    onProgress: (event: any) => void,
    signal?: AbortSignal
  ): Promise<void>;
}
