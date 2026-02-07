/**
 * Authorization Components
 *
 * Provides declarative components for permission-based rendering.
 */

import React from 'react';
import {usePermission, useResourcePermission} from '../../hooks/permission';

// ============================================================================
// Authorized Component
// ============================================================================

interface AuthorizedProps {
    /**
     * Required permission string (e.g., "dataset:create", "annotation:update:self")
     */
    permission: string;
    /**
     * Resource type (e.g., "dataset")
     */
    resourceType?: string;
    /**
     * Resource ID
     */
    resourceId?: string;
    /**
     * Content to show when user doesn't have permission
     */
    fallback?: React.ReactNode;
    /**
     * Children to render when authorized
     */
    children: React.ReactNode;
}

/**
 * Conditionally render children based on user permissions.
 *
 * @example
 * // Simple permission check
 * <Authorized permission="dataset:create">
 *   <Button>Create Dataset</Button>
 * </Authorized>
 *
 * @example
 * // Resource-level permission with fallback
 * <Authorized
 *   permission="dataset:delete"
 *   resourceType="dataset"
 *   resourceId={datasetId}
 *   fallback={<Tooltip title="No permission"><Button disabled>Delete</Button></Tooltip>}
 * >
 *   <Button danger>Delete Dataset</Button>
 * </Authorized>
 */
export const Authorized: React.FC<AuthorizedProps> = ({
                                                          permission,
                                                          resourceType,
                                                          resourceId,
                                                          fallback = null,
                                                          children,
                                                      }) => {
    const {can} = usePermission();

    const hasAccess = can(permission, resourceType, resourceId);

    if (hasAccess) {
        return <>{children}</>;
    }

    return <>{fallback}</>;
};

// ============================================================================
// HasRole Component
// ============================================================================

interface HasRoleProps {
    /**
     * Role name or array of role names to check
     */
    role: string | string[];
    /**
     * Content to show when user doesn't have the role
     */
    fallback?: React.ReactNode;
    /**
     * Children to render when user has the role
     */
    children: React.ReactNode;
}

/**
 * Conditionally render children based on user roles.
 *
 * @example
 * <HasRole role="admin">
 *   <AdminPanel />
 * </HasRole>
 *
 * @example
 * <HasRole role={['admin', 'super_admin']}>
 *   <Button>Admin Action</Button>
 * </HasRole>
 */
export const HasRole: React.FC<HasRoleProps> = ({
                                                    role,
                                                    fallback = null,
                                                    children,
                                                }) => {
    const {hasRole, hasAnyRole} = usePermission();

    const roles = Array.isArray(role) ? role : [role];
    const hasAccess = roles.length === 1 ? hasRole(roles[0]) : hasAnyRole(roles);

    if (hasAccess) {
        return <>{children}</>;
    }

    return <>{fallback}</>;
};

// ============================================================================
// SuperAdminOnly Component
// ============================================================================

interface SuperAdminOnlyProps {
    /**
     * Content to show when user is not super admin
     */
    fallback?: React.ReactNode;
    /**
     * Children to render for super admins
     */
    children: React.ReactNode;
}

/**
 * Only render children for super administrators.
 *
 * @example
 * <SuperAdminOnly>
 *   <DangerousSystemSettings />
 * </SuperAdminOnly>
 */
export const SuperAdminOnly: React.FC<SuperAdminOnlyProps> = ({
                                                                  fallback = null,
                                                                  children,
                                                              }) => {
    const {isSuperAdmin} = usePermission();

    if (isSuperAdmin) {
        return <>{children}</>;
    }

    return <>{fallback}</>;
};

// ============================================================================
// ResourceAuthorized Component
// ============================================================================

interface ResourceAuthorizedProps {
    /**
     * Required permission string
     */
    permission: string;
    /**
     * Resource type
     */
    resourceType: string;
    /**
     * Resource ID
     */
    resourceId: string;
    /**
     * Content to show when user doesn't have permission
     */
    fallback?: React.ReactNode;
    /**
     * Children to render when authorized
     */
    children: React.ReactNode;
}

/**
 * Specialized component for resource-level authorization.
 * Automatically fetches and caches resource permissions.
 *
 * @example
 * <ResourceAuthorized
 *   permission="annotation:modify"
 *   resourceType="dataset"
 *   resourceId={datasetId}
 * >
 *   <AnnotationTools />
 * </ResourceAuthorized>
 */
export const ResourceAuthorized: React.FC<ResourceAuthorizedProps> = ({
                                                                          permission,
                                                                          resourceType,
                                                                          resourceId,
                                                                          fallback = null,
                                                                          children,
                                                                      }) => {
    const {can} = useResourcePermission(resourceType, resourceId);

    if (can(permission)) {
        return <>{children}</>;
    }

    return <>{fallback}</>;
};

// ============================================================================
// withAuthorization HOC
// ============================================================================

interface WithAuthorizationOptions {
    permission: string;
    resourceType?: string;
    resourceIdProp?: string;
    fallback?: React.ReactNode;
}

/**
 * Higher-order component for authorization.
 *
 * @example
 * const ProtectedButton = withAuthorization(Button, {
 *   permission: 'dataset:delete',
 *   fallback: <Button disabled>No Access</Button>,
 * });
 */
export function withAuthorization<P extends object>(
    Component: React.ComponentType<P>,
    options: WithAuthorizationOptions
): React.FC<P> {
    const {
        permission,
        resourceType,
        resourceIdProp,
        fallback = null,
    } = options;

    const AuthorizedComponent: React.FC<P> = (props) => {
        const resourceId = resourceIdProp ? (props as any)[resourceIdProp] : undefined;

        return (
            <Authorized
                permission={permission}
                resourceType={resourceType}
                resourceId={resourceId}
                fallback={fallback}
            >
                <Component {...props} />
            </Authorized>
        );
    };

    AuthorizedComponent.displayName = `withAuthorization(${
        Component.displayName || Component.name || 'Component'
    })`;

    return AuthorizedComponent;
}
