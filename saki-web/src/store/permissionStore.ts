/**
 * Permission Store
 *
 * Manages user permissions and provides permission checking utilities.
 */

import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import {
  RoleInfo,
  UserPermissions,
  ResourcePermissionCache,
} from '../types/permission';

// Cache expiration time (5 minutes)
const CACHE_EXPIRATION_MS = 5 * 60 * 1000;

interface PermissionState {
  // User's base permissions (from system roles)
  userPermissions: UserPermissions | null;

  // Resource-specific permission cache
  // Key: `${resourceType}:${resourceId}`
  resourcePermissions: Record<string, ResourcePermissionCache>;

  // Loading state
  isLoading: boolean;

  // Actions
  setUserPermissions: (permissions: UserPermissions) => void;
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
    resourceId?: string,
    resourceOwnerId?: string
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
      userPermissions: null,
      resourcePermissions: {},
      isLoading: false,

      setUserPermissions: (permissions) => {
        set({ userPermissions: permissions });
      },

      setResourcePermissions: (resourceType, resourceId, data) => {
        const key = `${resourceType}:${resourceId}`;
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
        }));
      },

      clearResourcePermissions: (resourceType, resourceId) => {
        if (resourceType && resourceId) {
          const key = `${resourceType}:${resourceId}`;
          set((state) => {
            const newPerms = { ...state.resourcePermissions };
            delete newPerms[key];
            return { resourcePermissions: newPerms };
          });
        } else {
          set({ resourcePermissions: {} });
        }
      },

      clearPermissions: () => {
        set({
          userPermissions: null,
          resourcePermissions: {},
        });
      },

      setLoading: (loading) => {
        set({ isLoading: loading });
      },

      hasPermission: (permission, resourceType, resourceId, resourceOwnerId) => {
        const state = get();
        const { userPermissions, resourcePermissions } = state;

        if (!userPermissions) return false;

        // Super admin has all permissions
        if (userPermissions.isSuperAdmin) return true;

        // Parse required permission
        const [reqResource, reqAction, reqScope = 'assigned'] = permission.split(':');

        // Check user's system permissions
        for (const perm of userPermissions.permissions) {
          const [permResource, permAction, permScope = 'assigned'] = perm.split(':');

          if (permResource !== reqResource) continue;
          if (permAction !== reqAction && permAction !== 'manage') continue;

          // Check scope
          if (permScope === 'all') return true;

          if (permScope === 'owned' && resourceOwnerId) {
            if (resourceOwnerId === userPermissions.userId) return true;
          }
        }

        // Check resource-specific permissions
        if (resourceType && resourceId) {
          const key = `${resourceType}:${resourceId}`;
          const resPerm = resourcePermissions[key];

          // Check cache expiration
          if (resPerm && Date.now() - resPerm.fetchedAt < CACHE_EXPIRATION_MS) {
            // Owner has all permissions on their resources
            if (resPerm.isOwner) return true;

            // Check resource permissions
            for (const perm of resPerm.permissions) {
              const [permResource, permAction, permScope = 'assigned'] = perm.split(':');

              if (permResource !== reqResource) continue;
              if (permAction !== reqAction && permAction !== 'manage') continue;

              if (permScope === 'assigned') return true;
              if (permScope === 'self' && reqScope === 'self') return true;
            }
          }
        }

        return false;
      },

      hasAnyPermission: (permissions) => {
        const { hasPermission } = get();
        return permissions.some((p) => hasPermission(p));
      },

      hasAllPermissions: (permissions) => {
        const { hasPermission } = get();
        return permissions.every((p) => hasPermission(p));
      },

      hasRole: (roleName) => {
        const { userPermissions } = get();
        return userPermissions?.systemRoles.some((r) => r.name === roleName) ?? false;
      },

      hasAnyRole: (roleNames) => {
        const { hasRole } = get();
        return roleNames.some((r) => hasRole(r));
      },

      isSuperAdmin: () => {
        const { userPermissions } = get();
        return userPermissions?.isSuperAdmin ?? false;
      },

      getSystemRoles: () => {
        const { userPermissions } = get();
        return userPermissions?.systemRoles ?? [];
      },

      getResourceRole: (resourceType, resourceId) => {
        const { resourcePermissions } = get();
        const key = `${resourceType}:${resourceId}`;
        return resourcePermissions[key]?.role;
      },

      isResourceOwner: (resourceType, resourceId) => {
        const { resourcePermissions } = get();
        const key = `${resourceType}:${resourceId}`;
        return resourcePermissions[key]?.isOwner ?? false;
      },
    }),
    {
      name: 'permission-storage',
      partialize: (state) => ({
        userPermissions: state.userPermissions,
        // Don't persist resource permissions cache
      }),
    }
  )
);

/**
 * Helper function to check if user can perform action on annotation
 * considering the 'self' scope.
 */
export function canModifyAnnotation(
  permission: string,
  annotationCreatorId: string | undefined,
  currentUserId: string | undefined
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
