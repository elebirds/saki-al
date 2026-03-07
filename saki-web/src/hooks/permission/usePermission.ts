/**
 * Permission Hooks
 *
 * Provides hooks for permission checking in React components.
 */

import {useCallback, useEffect, useRef} from 'react';
import {canModifyAnnotation, usePermissionStore} from '../../store/permissionStore';
import {useAuthStore} from '../../store/authStore';
import {api} from '../../services/api';

const SYSTEM_PERMISSION_REFRESH_MS = 60 * 1000;

/**
 * Basic permission hook.
 *
 * Provides permission checking functions based on user's system roles.
 *
 * @example
 * const { can, isSuperAdmin, hasRole } = usePermission();
 *
 * if (can('user:create')) {
 *   // Show create user button
 * }
 */
export function usePermission() {
    const store = usePermissionStore();

    const can = useCallback(
        (
            permission: string,
            resourceType?: string,
            resourceId?: string
        ) => {
            return store.hasPermission(permission, resourceType, resourceId);
        },
        [store.hasPermission, store.systemPermissions]
    );

    const canAny = useCallback(
        (permissions: string[]) => {
            return store.hasAnyPermission(permissions);
        },
        [store.hasAnyPermission]
    );

    const canAll = useCallback(
        (permissions: string[]) => {
            return store.hasAllPermissions(permissions);
        },
        [store.hasAllPermissions]
    );

    return {
        can,
        canAny,
        canAll,
        isSuperAdmin: store.isSuperAdmin(),
        hasRole: store.hasRole,
        hasAnyRole: store.hasAnyRole,
        systemRoles: store.getSystemRoles(),
        isLoading: store.isLoading,
    };
}

/**
 * Resource-specific permission hook.
 *
 * Fetches and caches permissions for a specific resource.
 *
 * @example
 * const { can, role, isOwner, isLoading } = useResourcePermission('dataset', datasetId);
 *
 * if (can('dataset:update')) {
 *   // Show edit button
 * }
 */
export function useResourcePermission(
    resourceType: string,
    resourceId: string | undefined
) {
    const store = usePermissionStore();
    const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
    const token = useAuthStore((state) => state.token);
    const user = useAuthStore((state) => state.user);

    // Fetch resource permissions
    useEffect(() => {
        // Only fetch if we have a valid authenticated user
        if (!resourceId || !isAuthenticated || !token || !user) return;

        const key = `${resourceType}:${resourceId}`;
        const cached = store.resourcePermissions[key];

        // Skip if already cached and not expired (5 minutes)
        if (cached && Date.now() - cached.fetchedAt < 5 * 60 * 1000) {
            return;
        }

        const fetchPermissions = async () => {
            try {
                const data = await api.getResourcePermissions(resourceType, resourceId);
                store.setResourcePermissions(resourceType, resourceId, {
                    role: data.resourceRole,
                    permissions: data.permissions,
                    isOwner: data.isOwner,
                });
            } catch (error) {
                // Silently fail - the API interceptor will handle 401
                console.error('Failed to fetch resource permissions:', error);
            }
        };

        fetchPermissions();
    }, [resourceType, resourceId, isAuthenticated, token, user]);

    const can = useCallback(
        (permission: string) => {
            return store.hasPermission(permission, resourceType, resourceId);
        },
        [resourceType, resourceId, store.hasPermission, store.resourcePermissions]
    );

    const role = resourceId ? store.getResourceRole(resourceType, resourceId) : undefined;
    const isOwner = resourceId ? store.isResourceOwner(resourceType, resourceId) : false;

    return {
        can,
        role,
        isOwner,
        isLoading: store.isLoading,
        permissions: resourceId
            ? store.resourcePermissions[`${resourceType}:${resourceId}`]?.permissions ?? []
            : [],
    };
}

/**
 * Initialize user permissions on app startup.
 *
 * Should be called in the app root component.
 * Only fetches permissions when there's a valid authenticated user.
 *
 * @example
 * function App() {
 *   useInitPermissions();
 *   return <Router>...</Router>;
 * }
 */
export function useInitPermissions() {
    const store = usePermissionStore();
    const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
    const token = useAuthStore((state) => state.token);
    const user = useAuthStore((state) => state.user);
    const inFlight = useRef(false);
    const lastFetchedAt = useRef(0);

    const refreshSystemPermissions = useCallback(
        async ({force = false, showLoading = false}: { force?: boolean; showLoading?: boolean } = {}) => {
            if (!isAuthenticated || !token || !user) return;
            if (!force && Date.now() - lastFetchedAt.current < SYSTEM_PERMISSION_REFRESH_MS) return;
            if (inFlight.current) return;

            if (showLoading) {
                store.setLoading(true);
            }
            inFlight.current = true;
            try {
                const data = await api.getSystemPermissions();
                store.setSystemPermissions(data);
                lastFetchedAt.current = Date.now();
            } catch (error: any) {
                // On auth error, clear state and wait for auth flow to recover.
                if (error?.statusCode === 401) {
                    store.clearPermissions();
                    lastFetchedAt.current = 0;
                }
                console.error('Failed to refresh system permissions:', error);
            } finally {
                inFlight.current = false;
                if (showLoading) {
                    store.setLoading(false);
                }
            }
        },
        [isAuthenticated, token, user]
    );

    useEffect(() => {
        // Clear permissions if not authenticated
        if (!isAuthenticated || !token) {
            store.clearPermissions();
            inFlight.current = false;
            lastFetchedAt.current = 0;
            return;
        }

        // Don't fetch if no user loaded yet (still validating token)
        // The user object is set after successful login
        if (!user) {
            return;
        }

        void refreshSystemPermissions({force: true, showLoading: true});

        const intervalId = window.setInterval(() => {
            void refreshSystemPermissions();
        }, SYSTEM_PERMISSION_REFRESH_MS);

        const onFocus = () => {
            void refreshSystemPermissions({force: true});
        };
        const onVisibilityChange = () => {
            if (document.visibilityState === 'visible') {
                void refreshSystemPermissions({force: true});
            }
        };
        window.addEventListener('focus', onFocus);
        document.addEventListener('visibilitychange', onVisibilityChange);

        return () => {
            window.clearInterval(intervalId);
            window.removeEventListener('focus', onFocus);
            document.removeEventListener('visibilitychange', onVisibilityChange);
        };
    }, [isAuthenticated, token, user, refreshSystemPermissions]);
}

/**
 * Hook for annotation permission checking.
 *
 * @example
 * const { canModify, canDelete } = useAnnotationPermission('project', projectId, annotation.annotatorId);
 *
 * if (canModify) {
 *   // Show edit button
 * }
 */
export function useAnnotationPermission(
    resourceType: string,
    resourceId: string | undefined,
    annotationCreatorId?: string
) {
    const currentUser = useAuthStore((state) => state.user);

    const canModify = canModifyAnnotation(
        'annotation:create:assigned',
        resourceType,
        resourceId
    );

    const canDelete = canModifyAnnotation(
        'annotation:create:assigned',
        resourceType,
        resourceId
    );

    const canRead = canModifyAnnotation(
        'annotation:read:assigned',
        resourceType,
        resourceId
    );

    return {
        canRead,
        canModify,
        canDelete,
        isOwner: annotationCreatorId === currentUser?.id,
    };
}
