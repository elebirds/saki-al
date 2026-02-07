/**
 * Permission Store
 *
 * Manages user permissions and provides permission checking utilities.
 */

import {create} from 'zustand';
import {persist} from 'zustand/middleware';
import {
    parsePermission,
    Permission,
    PermissionIndex,
    ResourcePermissionCache,
    RoleInfo,
    Scope,
    SystemPermissions,
} from '../types';

// Cache expiration time (5 minutes)
const CACHE_EXPIRATION_MS = 5 * 60 * 1000;

/**
 * Scope hierarchy: all > assigned > self
 * Higher scope includes lower scopes
 */
const SCOPE_HIERARCHY: Record<Scope, number> = {
    all: 3,
    assigned: 2,
    self: 1,
};

/**
 * Build permission index from permission strings
 * Structure: Map<target, Map<action, Set<scope>>>
 */
function buildPermissionIndex(permissionStrings: string[]): PermissionIndex {
    const index: PermissionIndex = new Map();

    for (const permStr of permissionStrings) {
        try {
            const perm = parsePermission(permStr);

            if (!index.has(perm.target)) {
                index.set(perm.target, new Map());
            }

            const targetMap = index.get(perm.target)!;
            if (!targetMap.has(perm.action)) {
                targetMap.set(perm.action, new Set());
            }

            targetMap.get(perm.action)!.add(perm.scope);
        } catch (error) {
            console.warn(`Failed to parse permission: ${permStr}`, error);
        }
    }

    return index;
}

/**
 * Check if a permission matches using wildcard support
 *
 * @param permIndex Permission index to search
 * @param required Required permission
 * @returns The highest matching scope, or null if no match
 */
function findMatchingScope(
    permIndex: PermissionIndex,
    required: Permission
): Scope | null {
    // Check exact match first
    const targetMap = permIndex.get(required.target);
    if (targetMap) {
        const scopes = targetMap.get(required.action);
        if (scopes && scopes.size > 0) {
            // Return the highest scope
            return Array.from(scopes).reduce((highest, scope) =>
                SCOPE_HIERARCHY[scope] > SCOPE_HIERARCHY[highest] ? scope : highest
            );
        }

        // Check wildcard action (*)
        const wildcardScopes = targetMap.get('*');
        if (wildcardScopes && wildcardScopes.size > 0) {
            return Array.from(wildcardScopes).reduce((highest, scope) =>
                SCOPE_HIERARCHY[scope] > SCOPE_HIERARCHY[highest] ? scope : highest
            );
        }
    }

    // Check wildcard target (*)
    const wildcardTargetMap = permIndex.get('*');
    if (wildcardTargetMap) {
        const scopes = wildcardTargetMap.get(required.action);
        if (scopes && scopes.size > 0) {
            return Array.from(scopes).reduce((highest, scope) =>
                SCOPE_HIERARCHY[scope] > SCOPE_HIERARCHY[highest] ? scope : highest
            );
        }

        // Check wildcard target + wildcard action (*:*)
        const wildcardScopes = wildcardTargetMap.get('*');
        if (wildcardScopes && wildcardScopes.size > 0) {
            return Array.from(wildcardScopes).reduce((highest, scope) =>
                SCOPE_HIERARCHY[scope] > SCOPE_HIERARCHY[highest] ? scope : highest
            );
        }
    }

    return null;
}

/**
 * Check if a scope satisfies the required scope
 * Higher scope includes lower scopes
 */
function scopeSatisfies(have: Scope, required: Scope): boolean {
    return SCOPE_HIERARCHY[have] >= SCOPE_HIERARCHY[required];
}

interface PermissionState {
    // System-level permissions (from system roles)
    systemPermissions: SystemPermissions | null;

    // System permission index for fast lookup
    systemPermissionIndex: PermissionIndex;

    // Resource-specific permission cache
    // Key: `${resourceType}:${resourceId}`
    resourcePermissions: Record<string, ResourcePermissionCache>;

    // Resource permission indices for fast lookup
    // Key: `${resourceType}:${resourceId}`
    resourcePermissionIndices: Record<string, PermissionIndex>;

    // Loading state
    isLoading: boolean;

    // Actions
    setSystemPermissions: (permissions: SystemPermissions) => void;
    setResourcePermissions: (
        resourceType: string,
        resourceId: string,
        data: Omit<ResourcePermissionCache, 'resourceType' | 'resourceId' | 'fetchedAt'>
    ) => void;
    clearResourcePermissions: (resourceType?: string, resourceId?: string) => void;
    clearPermissions: () => void;
    setLoading: (loading: boolean) => void;

    // Permission checking
    hasPermission: (
        permission: string,
        resourceType?: string,
        resourceId?: string
    ) => boolean;
    hasAnyPermission: (permissions: string[]) => boolean;
    hasAllPermissions: (permissions: string[]) => boolean;

    // Role checking
    hasRole: (roleName: string) => boolean;
    hasAnyRole: (roleNames: string[]) => boolean;

    // Computed properties
    isSuperAdmin: () => boolean;
    getSystemRoles: () => RoleInfo[];
    getResourceRole: (resourceType: string, resourceId: string) => RoleInfo | undefined;
    isResourceOwner: (resourceType: string, resourceId: string) => boolean;
}

export const usePermissionStore = create<PermissionState>()(
    persist(
        (set, get) => ({
            systemPermissions: null,
            systemPermissionIndex: new Map(),
            resourcePermissions: {},
            resourcePermissionIndices: {},
            isLoading: false,

            setSystemPermissions: (permissions) => {
                const index = buildPermissionIndex(permissions.permissions);
                set({
                    systemPermissions: permissions,
                    systemPermissionIndex: index,
                });
            },

            setResourcePermissions: (resourceType, resourceId, data) => {
                const key = `${resourceType}:${resourceId}`;
                const index = buildPermissionIndex(data.permissions);
                set((state) => ({
                    resourcePermissions: {
                        ...state.resourcePermissions,
                        [key]: {
                            ...data,
                            resourceType,
                            resourceId,
                            fetchedAt: Date.now(),
                        },
                    },
                    resourcePermissionIndices: {
                        ...state.resourcePermissionIndices,
                        [key]: index,
                    },
                }));
            },

            clearResourcePermissions: (resourceType, resourceId) => {
                if (resourceType && resourceId) {
                    const key = `${resourceType}:${resourceId}`;
                    set((state) => {
                        const newPerms = {...state.resourcePermissions};
                        const newIndices = {...state.resourcePermissionIndices};
                        delete newPerms[key];
                        delete newIndices[key];
                        return {
                            resourcePermissions: newPerms,
                            resourcePermissionIndices: newIndices,
                        };
                    });
                } else {
                    set({
                        resourcePermissions: {},
                        resourcePermissionIndices: {},
                    });
                }
            },

            clearPermissions: () => {
                set({
                    systemPermissions: null,
                    systemPermissionIndex: new Map(),
                    resourcePermissions: {},
                    resourcePermissionIndices: {},
                });
            },

            setLoading: (loading) => {
                set({isLoading: loading});
            },

            hasPermission: (permission, resourceType, resourceId) => {
                const state = get();
                const {
                    systemPermissions,
                    systemPermissionIndex,
                    resourcePermissions,
                    resourcePermissionIndices
                } = state;

                if (!systemPermissions) return false;

                // Super admin has all permissions
                if (systemPermissions.isSuperAdmin) return true;

                // Parse required permission
                let required: Permission;
                try {
                    required = parsePermission(permission);
                } catch (error) {
                    console.warn(`Invalid permission format: ${permission}`, error);
                    return false;
                }

                // Check system permissions first
                const systemScope = findMatchingScope(systemPermissionIndex, required);
                if (systemScope !== null) {
                    // System permissions with 'all' scope always pass
                    if (systemScope === 'all') return true;

                    // Check if system scope satisfies required scope
                    if (scopeSatisfies(systemScope, required.scope)) {
                        return true;
                    }
                }

                // Check resource-specific permissions (if resource context provided)
                if (resourceType && resourceId) {
                    const key = `${resourceType}:${resourceId}`;
                    const resPerm = resourcePermissions[key];

                    // Check cache expiration
                    if (resPerm && Date.now() - resPerm.fetchedAt < CACHE_EXPIRATION_MS) {
                        // Owner has all permissions on their resources
                        if (resPerm.isOwner) return true;

                        // Check resource permissions using index
                        const resourceIndex = resourcePermissionIndices[key];
                        if (resourceIndex) {
                            const resourceScope = findMatchingScope(resourceIndex, required);
                            if (resourceScope !== null) {
                                // Resource permissions can only have 'assigned' or 'self' scope
                                // 'all' scope is only for system permissions
                                if (resourceScope === 'all') {
                                    // This shouldn't happen, but handle it gracefully
                                    return true;
                                }

                                // Check if resource scope satisfies required scope
                                if (scopeSatisfies(resourceScope, required.scope)) {
                                    return true;
                                }
                            }
                        }
                    }
                }

                return false;
            },

            hasAnyPermission: (permissions) => {
                const {hasPermission} = get();
                return permissions.some((p) => hasPermission(p));
            },

            hasAllPermissions: (permissions) => {
                const {hasPermission} = get();
                return permissions.every((p) => hasPermission(p));
            },

            hasRole: (roleName) => {
                const {systemPermissions} = get();
                return systemPermissions?.systemRoles.some((r) => r.name === roleName) ?? false;
            },

            hasAnyRole: (roleNames) => {
                const {hasRole} = get();
                return roleNames.some((r) => hasRole(r));
            },

            isSuperAdmin: () => {
                const {systemPermissions} = get();
                return systemPermissions?.isSuperAdmin ?? false;
            },

            getSystemRoles: () => {
                const {systemPermissions} = get();
                return systemPermissions?.systemRoles ?? [];
            },

            getResourceRole: (resourceType, resourceId) => {
                const {resourcePermissions} = get();
                const key = `${resourceType}:${resourceId}`;
                return resourcePermissions[key]?.role;
            },

            isResourceOwner: (resourceType, resourceId) => {
                const {resourcePermissions} = get();
                const key = `${resourceType}:${resourceId}`;
                return resourcePermissions[key]?.isOwner ?? false;
            },
        }),
        {
            name: 'permission-storage',
            partialize: (state) => ({
                systemPermissions: state.systemPermissions,
                // Don't persist indices - they can be rebuilt from permission strings
                // Don't persist resource permissions cache
            }),
            onRehydrateStorage: () => (state) => {
                // Rebuild indices after rehydration
                if (state?.systemPermissions) {
                    state.systemPermissionIndex = buildPermissionIndex(state.systemPermissions.permissions);
                }

                // Rebuild resource permission indices
                if (state?.resourcePermissions) {
                    const resourceIndices: Record<string, PermissionIndex> = {};
                    for (const [key, resPerm] of Object.entries(state.resourcePermissions)) {
                        resourceIndices[key] = buildPermissionIndex(resPerm.permissions);
                    }
                    state.resourcePermissionIndices = resourceIndices;
                }
            },
        }
    )
);

/**
 * Helper function to check if user can perform action on annotation
 * considering the 'self' scope.
 */
export function canModifyAnnotation(
    permission: string,
    annotationCreatorId: string | null | undefined,
    currentUserId: string | null | undefined
): boolean {
    const store = usePermissionStore.getState();

    // If no creator ID, assume it's a new annotation
    if (!annotationCreatorId) return store.hasPermission(permission);

    // Check if user has full permission (assigned scope)
    if (store.hasPermission(permission)) return true;

    // Check if user has self scope and is the creator
    const selfPermission = permission.replace(':assigned', ':self');
    if (store.hasPermission(selfPermission) && annotationCreatorId === currentUserId) {
        return true;
    }

    return false;
}
