"""
API endpoints for Role management.

Provides CRUD operations for roles and user role assignments.
"""

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlmodel import Session, select

from saki_api.api.deps import get_current_user, get_session
from saki_api.core.rbac import (
    require_permission,
    get_permission_checker,
    PermissionChecker,
    log_audit,
)
from saki_api.core.rbac.audit import (
    log_role_create,
    log_role_update,
    log_role_delete,
    log_user_role_assign,
    log_user_role_revoke,
)
from saki_api.models import (
    User,
    Role, RoleType, RoleCreate, RoleRead, RoleUpdate,
    RolePermission, RolePermissionRead,
    UserSystemRole, UserSystemRoleCreate, UserSystemRoleRead,
    AuditAction,
    Permissions,
)

router = APIRouter()


# ============================================================================
# Role CRUD
# ============================================================================

@router.get("/", response_model=List[RoleRead])
def list_roles(
    type: Optional[RoleType] = Query(None, description="Filter by role type"),
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission(Permissions.ROLE_READ)),
):
    """
    List all roles.
    
    Optionally filter by type (system or resource).
    """
    query = select(Role).order_by(Role.sort_order, Role.created_at)
    
    if type:
        query = query.where(Role.type == type)
    
    roles = session.exec(query).all()
    
    result = []
    for role in roles:
        # Get permissions for the role
        perms = session.exec(
            select(RolePermission).where(RolePermission.role_id == role.id)
        ).all()
        
        role_read = RoleRead(
            id=role.id,
            name=role.name,
            display_name=role.display_name,
            description=role.description,
            type=role.type,
            parent_id=role.parent_id,
            is_system=role.is_system,
            is_default=role.is_default,
            sort_order=role.sort_order,
            created_at=role.created_at,
            updated_at=role.updated_at,
            permissions=[
                RolePermissionRead(
                    id=p.id,
                    permission=p.permission,
                    conditions=p.conditions,
                )
                for p in perms
            ],
        )
        result.append(role_read)
    
    return result


@router.get("/{role_id}", response_model=RoleRead)
def get_role(
    role_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission(Permissions.ROLE_READ)),
):
    """Get a role by ID."""
    role = session.get(Role, role_id)
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    
    perms = session.exec(
        select(RolePermission).where(RolePermission.role_id == role.id)
    ).all()
    
    return RoleRead(
        id=role.id,
        name=role.name,
        display_name=role.display_name,
        description=role.description,
        type=role.type,
        parent_id=role.parent_id,
        is_system=role.is_system,
        is_default=role.is_default,
        sort_order=role.sort_order,
        created_at=role.created_at,
        updated_at=role.updated_at,
        permissions=[
            RolePermissionRead(
                id=p.id,
                permission=p.permission,
                conditions=p.conditions,
            )
            for p in perms
        ],
    )


@router.post("/", response_model=RoleRead)
def create_role(
    role_in: RoleCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission(Permissions.ROLE_CREATE)),
):
    """
    Create a custom role.
    
    System preset roles cannot be created through this endpoint.
    """
    # Check name uniqueness
    existing = session.exec(
        select(Role).where(Role.name == role_in.name)
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Role name already exists")
    
    # Validate parent role exists
    if role_in.parent_id:
        parent = session.get(Role, role_in.parent_id)
        if not parent:
            raise HTTPException(status_code=400, detail="Parent role not found")
        if parent.type != role_in.type:
            raise HTTPException(
                status_code=400,
                detail="Parent role must be of the same type"
            )
    
    # Create role
    role = Role(
        name=role_in.name,
        display_name=role_in.display_name,
        description=role_in.description,
        type=role_in.type,
        parent_id=role_in.parent_id,
        is_system=False,  # Custom roles are not system roles
        is_default=False,
    )
    session.add(role)
    session.flush()
    
    # Create permissions
    for perm_in in role_in.permissions:
        perm = RolePermission(
            role_id=role.id,
            permission=perm_in.permission,
            conditions=perm_in.conditions,
        )
        session.add(perm)
    
    # Audit log
    log_role_create(
        session=session,
        role_id=role.id,
        role_data={
            "name": role.name,
            "display_name": role.display_name,
            "type": role.type.value,
            "permissions": [p.permission for p in role_in.permissions],
        },
        actor_id=current_user.id,
    )
    
    session.commit()
    session.refresh(role)
    
    return get_role(role.id, session, current_user)


@router.put("/{role_id}", response_model=RoleRead)
def update_role(
    role_id: str,
    role_in: RoleUpdate,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission(Permissions.ROLE_UPDATE)),
):
    """
    Update a role.
    
    System preset roles have limited update capabilities.
    """
    role = session.get(Role, role_id)
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    
    # Store old values for audit
    old_data = {
        "display_name": role.display_name,
        "description": role.description,
    }
    
    # Update basic fields
    if role_in.display_name is not None:
        role.display_name = role_in.display_name
    if role_in.description is not None:
        role.description = role_in.description
    if role_in.sort_order is not None:
        role.sort_order = role_in.sort_order
    
    # Update parent (only for non-system roles)
    if role_in.parent_id is not None and not role.is_system:
        if role_in.parent_id:
            parent = session.get(Role, role_in.parent_id)
            if not parent:
                raise HTTPException(status_code=400, detail="Parent role not found")
            if parent.type != role.type:
                raise HTTPException(
                    status_code=400,
                    detail="Parent role must be of the same type"
                )
        role.parent_id = role_in.parent_id
    
    # Update permissions (only for non-system roles)
    if role_in.permissions is not None:
        if role.is_system:
            raise HTTPException(
                status_code=403,
                detail="Cannot modify permissions of system preset roles"
            )
        
        # Delete old permissions
        old_perms = session.exec(
            select(RolePermission).where(RolePermission.role_id == role_id)
        ).all()
        for old_perm in old_perms:
            session.delete(old_perm)
        
        # Create new permissions
        for perm_in in role_in.permissions:
            perm = RolePermission(
                role_id=role.id,
                permission=perm_in.permission,
                conditions=perm_in.conditions,
            )
            session.add(perm)
    
    role.updated_at = datetime.utcnow()
    session.add(role)
    
    # Audit log
    log_role_update(
        session=session,
        role_id=role.id,
        old_data=old_data,
        new_data={
            "display_name": role.display_name,
            "description": role.description,
        },
        actor_id=current_user.id,
    )
    
    session.commit()
    
    return get_role(role_id, session, current_user)


@router.delete("/{role_id}")
def delete_role(
    role_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission(Permissions.ROLE_DELETE)),
):
    """
    Delete a role.
    
    System preset roles cannot be deleted.
    Roles that are in use cannot be deleted.
    """
    role = session.get(Role, role_id)
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    
    # Cannot delete system roles
    if role.is_system:
        raise HTTPException(
            status_code=403,
            detail="Cannot delete system preset roles"
        )
    
    # Check if role is in use
    user_count = session.exec(
        select(func.count()).select_from(UserSystemRole).where(
            UserSystemRole.role_id == role_id
        )
    ).one()
    
    from saki_api.models.rbac import ResourceMember
    member_count = session.exec(
        select(func.count()).select_from(ResourceMember).where(
            ResourceMember.role_id == role_id
        )
    ).one()
    
    if user_count > 0 or member_count > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Role is in use by {user_count} users and {member_count} resource members"
        )
    
    # Check if role is a parent
    child_count = session.exec(
        select(func.count()).select_from(Role).where(Role.parent_id == role_id)
    ).one()
    
    if child_count > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Role is a parent of {child_count} other roles"
        )
    
    # Audit log
    log_role_delete(
        session=session,
        role_id=role.id,
        role_data={
            "name": role.name,
            "display_name": role.display_name,
            "type": role.type.value,
        },
        actor_id=current_user.id,
    )
    
    session.delete(role)
    session.commit()
    
    return {"ok": True, "message": "Role deleted"}


# ============================================================================
# User Role Management
# ============================================================================

@router.get("/users/{user_id}/roles", response_model=List[UserSystemRoleRead])
def get_user_roles(
    user_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission(Permissions.USER_READ)),
):
    """Get all system roles assigned to a user."""
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    user_roles = session.exec(
        select(UserSystemRole).where(UserSystemRole.user_id == user_id)
    ).all()
    
    result = []
    for ur in user_roles:
        role = session.get(Role, ur.role_id)
        result.append(UserSystemRoleRead(
            id=ur.id,
            user_id=ur.user_id,
            role_id=ur.role_id,
            assigned_at=ur.assigned_at,
            assigned_by=ur.assigned_by,
            expires_at=ur.expires_at,
            role_name=role.name if role else None,
            role_display_name=role.display_name if role else None,
        ))
    
    return result


@router.post("/users/{user_id}/roles", response_model=UserSystemRoleRead)
def assign_user_role(
    user_id: str,
    role_in: UserSystemRoleCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission(Permissions.USER_MANAGE)),
    checker: PermissionChecker = Depends(get_permission_checker),
):
    """Assign a system role to a user."""
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    role = session.get(Role, role_in.role_id)
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    
    if role.type != RoleType.SYSTEM:
        raise HTTPException(
            status_code=400,
            detail="Can only assign system roles through this endpoint"
        )
    
    # Check if super_admin role - only super_admin can assign
    if role.name == "super_admin":
        if not checker.is_super_admin(current_user.id):
            raise HTTPException(
                status_code=403,
                detail="Only super administrators can assign super_admin role"
            )
    
    # Check if already assigned
    existing = session.exec(
        select(UserSystemRole).where(
            UserSystemRole.user_id == user_id,
            UserSystemRole.role_id == role_in.role_id
        )
    ).first()
    
    if existing:
        raise HTTPException(
            status_code=400,
            detail="Role already assigned to user"
        )
    
    # Create assignment
    user_role = UserSystemRole(
        user_id=user_id,
        role_id=role_in.role_id,
        assigned_by=current_user.id,
        expires_at=role_in.expires_at,
    )
    session.add(user_role)
    
    # Audit log
    log_user_role_assign(
        session=session,
        user_id=user_id,
        role_id=role_in.role_id,
        actor_id=current_user.id,
    )
    
    session.commit()
    session.refresh(user_role)
    
    return UserSystemRoleRead(
        id=user_role.id,
        user_id=user_role.user_id,
        role_id=user_role.role_id,
        assigned_at=user_role.assigned_at,
        assigned_by=user_role.assigned_by,
        expires_at=user_role.expires_at,
        role_name=role.name,
        role_display_name=role.display_name,
    )


@router.delete("/users/{user_id}/roles/{role_id}")
def revoke_user_role(
    user_id: str,
    role_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission(Permissions.USER_MANAGE)),
    checker: PermissionChecker = Depends(get_permission_checker),
):
    """Revoke a system role from a user."""
    user_role = session.exec(
        select(UserSystemRole).where(
            UserSystemRole.user_id == user_id,
            UserSystemRole.role_id == role_id
        )
    ).first()
    
    if not user_role:
        raise HTTPException(
            status_code=404,
            detail="Role not assigned to user"
        )
    
    role = session.get(Role, role_id)
    
    # Check if super_admin role - only super_admin can revoke
    if role and role.name == "super_admin":
        if not checker.is_super_admin(current_user.id):
            raise HTTPException(
                status_code=403,
                detail="Only super administrators can revoke super_admin role"
            )
        # Cannot revoke from self
        if user_id == current_user.id:
            raise HTTPException(
                status_code=403,
                detail="Cannot revoke super_admin role from yourself"
            )
    
    # Audit log
    log_user_role_revoke(
        session=session,
        user_id=user_id,
        role_id=role_id,
        actor_id=current_user.id,
    )
    
    session.delete(user_role)
    session.commit()
    
    return {"ok": True, "message": "Role revoked"}
