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
  Sample,
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
  getUsers(skip?: number, limit?: number): Promise<User[]>;
  getUserList(skip?: number, limit?: number): Promise<{ id: string; email: string; fullName?: string }[]>;
  createUser(user: Partial<User> & { password: string }): Promise<User>;
  updateUser(id: string, user: Partial<User> & { password?: string }): Promise<User>;
  deleteUser(id: string): Promise<void>;

  // ============================================================================
  // Permission APIs
  // ============================================================================
  
  // Get system-level permissions
  getSystemPermissions(): Promise<SystemPermissions>;
  
  // Get resource-specific permissions
  getResourcePermissions(resourceType: string, resourceId: string): Promise<ResourcePermissions>;
  
  // Role management
  getRoles(type?: RoleType): Promise<Role[]>;
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
  getDatasets(): Promise<Dataset[]>;
  getDataset(id: string): Promise<Dataset | undefined>;
  createDataset(dataset: DatasetCreate): Promise<Dataset>;
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
  // Sample APIs
  // ============================================================================
  getSamples(datasetId: string, options?: {
    offset?: number;
    limit?: number;
    sortBy?: string;
    sortOrder?: 'asc' | 'desc';
    skip?: number;
  }): Promise<Sample[]>;
  deleteSample(datasetId: string, sampleId: string): Promise<void>;
  uploadSamplesWithProgress(
    datasetId: string,
    files: File[],
    onProgress: (event: any) => void,
    signal?: AbortSignal
  ): Promise<void>;
}
