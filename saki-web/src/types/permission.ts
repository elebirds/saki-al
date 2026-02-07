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
export type Scope = 'all' | 'assigned' | 'self';

/**
 * Permission object representation
 *
 * Scope hierarchy (from highest to lowest):
 * - all: System-level permissions, only for system roles
 * - assigned: Resource-level permissions, for resource role members
 * - self: Resource-level permissions, for own resources/annotations
 */
export interface Permission {
    target: string;  // Resource type (e.g., 'user', 'dataset', '*')
    action: string;  // Action (e.g., 'create', 'read', '*')
    scope: Scope;    // Permission scope: 'all' | 'assigned' | 'self'
}

/**
 * Parse permission string to Permission object
 * Format: "target:action:scope" or "target:action" (defaults to 'assigned')
 *
 * @example
 * parsePermission("user:create:all") => { target: "user", action: "create", scope: "all" }
 * parsePermission("dataset:*:assigned") => { target: "dataset", action: "*", scope: "assigned" }
 * parsePermission("annotation:read") => { target: "annotation", action: "read", scope: "assigned" }
 */
export function parsePermission(permissionStr: string): Permission {
    const parts = permissionStr.split(':');
    if (parts.length < 2) {
        throw new Error(`Invalid permission format: ${permissionStr}`);
    }

    const target = parts[0];
    const action = parts[1];
    const scope = (parts[2] as Scope) || 'assigned';

    // Validate scope
    if (scope !== 'all' && scope !== 'assigned' && scope !== 'self') {
        throw new Error(`Invalid scope: ${scope}. Must be 'all', 'assigned', or 'self'`);
    }

    return {target, action, scope};
}

/**
 * Convert Permission object back to string
 */
export function permissionToString(permission: Permission): string {
    return `${permission.target}:${permission.action}:${permission.scope}`;
}

// ============================================================================
// Role Types
// ============================================================================

export interface RoleInfo {
    id: string;
    name: string;
    displayName: string;
    description: string;
    color: string;
    isSupremo: boolean;
}

export interface Role {
    id: string;
    name: string;
    displayName: string;
    description?: string;
    type: RoleType;
    parentId?: string;
    isSuperAdmin: boolean;
    isSystem: boolean;
    isDefault: boolean;
    isSupremo: boolean;
    sortOrder: number;
    color: string;
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
    color: string;
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
    color?: string;
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

export interface UserSystemRoleAssign {
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
    userAvatarUrl?: string;
    roleName?: string;
    roleDisplayName?: string;
    roleColor?: string;
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

/**
 * System-level permissions (from system roles)
 */
export interface SystemPermissions {
    userId: string;
    systemRoles: RoleInfo[];
    permissions: string[];  // Permission strings, will be parsed to Permission objects
    isSuperAdmin: boolean;
}

/**
 * Resource-specific permissions (from resource roles)
 */
export interface ResourcePermissions {
    resourceRole?: RoleInfo;
    permissions: string[];  // Permission strings, will be parsed to Permission objects
    isOwner: boolean;
}

// ============================================================================
// Permission Store Types
// ============================================================================

export interface ResourcePermissionCache {
    resourceType: string;
    resourceId: string;
    role?: RoleInfo;
    permissions: string[];  // Permission strings, will be parsed to Permission objects
    isOwner: boolean;
    fetchedAt: number;
}

/**
 * Permission index structure for fast lookup
 *
 * Structure:
 * - Map<target, Map<action, Set<scope>>>
 *
 * This allows O(1) lookup instead of O(n) iteration
 */
export type PermissionIndex = Map<string, Map<string, Set<Scope>>>;

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
