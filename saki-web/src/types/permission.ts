/**
 * Permission System Types
 *
 * Defines types for the RBAC permission system.
 */

// ============================================================================
// Enums
// ============================================================================

export type RoleType = 'system' | 'resource';
export type ResourceType = 'dataset' | 'project';
export type Scope = 'all' | 'owned' | 'assigned' | 'self';

// ============================================================================
// Role Types
// ============================================================================

export interface RoleInfo {
  id: string;
  name: string;
  displayName: string;
}

export interface Role {
  id: string;
  name: string;
  displayName: string;
  description?: string;
  type: RoleType;
  parentId?: string;
  isSystem: boolean;
  isDefault: boolean;
  sortOrder: number;
  createdAt: string;
  updatedAt?: string;
  permissions: RolePermission[];
}

export interface RolePermission {
  id: string;
  permission: string;
  conditions?: Record<string, any>;
}

export interface RoleCreate {
  name: string;
  displayName: string;
  description?: string;
  type: RoleType;
  parentId?: string;
  permissions: RolePermissionCreate[];
}

export interface RolePermissionCreate {
  permission: string;
  conditions?: Record<string, any>;
}

export interface RoleUpdate {
  displayName?: string;
  description?: string;
  parentId?: string;
  sortOrder?: number;
  permissions?: RolePermissionCreate[];
}

// ============================================================================
// User Role Types
// ============================================================================

export interface UserSystemRole {
  id: string;
  userId: string;
  roleId: string;
  assignedAt: string;
  assignedBy?: string;
  expiresAt?: string;
  roleName?: string;
  roleDisplayName?: string;
}

export interface UserSystemRoleCreate {
  roleId: string;
  expiresAt?: string;
}

// ============================================================================
// Resource Member Types
// ============================================================================

export interface ResourceMember {
  id: string;
  resourceType: ResourceType;
  resourceId: string;
  userId: string;
  roleId: string;
  createdAt: string;
  createdBy?: string;
  updatedAt?: string;
  userEmail?: string;
  userFullName?: string;
  roleName?: string;
  roleDisplayName?: string;
}

export interface ResourceMemberCreate {
  userId: string;
  roleId: string;
}

export interface ResourceMemberUpdate {
  roleId: string;
}

// ============================================================================
// Permission Response Types
// ============================================================================

export interface UserPermissions {
  userId: string;
  systemRoles: RoleInfo[];
  resourceRole?: RoleInfo;
  permissions: string[];
  isSuperAdmin: boolean;
  isOwner?: boolean;
}

// ============================================================================
// Permission Store Types
// ============================================================================

export interface ResourcePermissionCache {
  resourceType: string;
  resourceId: string;
  role?: RoleInfo;
  permissions: string[];
  isOwner: boolean;
  fetchedAt: number;
}

// ============================================================================
// Permission Constants
// ============================================================================

export const Permissions = {
  // System
  SYSTEM_MANAGE: 'system:manage:all',

  // User management
  USER_CREATE: 'user:create:all',
  USER_READ: 'user:read:all',
  USER_UPDATE: 'user:update:all',
  USER_DELETE: 'user:delete:all',
  USER_MANAGE: 'user:manage:all',

  // Role management
  ROLE_CREATE: 'role:create:all',
  ROLE_READ: 'role:read:all',
  ROLE_UPDATE: 'role:update:all',
  ROLE_DELETE: 'role:delete:all',

  // Dataset
  DATASET_CREATE: 'dataset:create:all',
  DATASET_READ: 'dataset:read:assigned',
  DATASET_UPDATE: 'dataset:update:assigned',
  DATASET_DELETE: 'dataset:delete:assigned',
  DATASET_ASSIGN: 'dataset:assign:assigned',
  DATASET_EXPORT: 'dataset:export:assigned',
  DATASET_IMPORT: 'dataset:import:assigned',

  // Sample
  SAMPLE_READ: 'sample:read:assigned',
  SAMPLE_CREATE: 'sample:create:assigned',
  SAMPLE_UPDATE: 'sample:update:assigned',
  SAMPLE_DELETE: 'sample:delete:assigned',

  // Annotation
  ANNOTATION_READ: 'annotation:read:assigned',
  ANNOTATION_CREATE: 'annotation:create:assigned',
  ANNOTATION_UPDATE: 'annotation:update:assigned',
  ANNOTATION_DELETE: 'annotation:delete:assigned',
  ANNOTATION_REVIEW: 'annotation:review:assigned',

  // Annotation - self scope
  ANNOTATION_READ_SELF: 'annotation:read:self',
  ANNOTATION_UPDATE_SELF: 'annotation:update:self',
  ANNOTATION_DELETE_SELF: 'annotation:delete:self',
} as const;

export type PermissionKey = keyof typeof Permissions;
