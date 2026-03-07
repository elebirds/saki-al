from __future__ import annotations

from saki_api.modules.access.domain.rbac import Permissions
from saki_api.modules.access.service.presets import PRESET_ROLES


def _role_permissions(role_name: str) -> set[str]:
    role = next(item for item in PRESET_ROLES if item["name"] == role_name)
    return set(role.get("permissions", []))


def test_export_permission_constants_values() -> None:
    assert Permissions.DATASET_EXPORT_ALL == "dataset:export:all"
    assert Permissions.DATASET_EXPORT == "dataset:export:assigned"
    assert Permissions.PROJECT_EXPORT_ALL == "project:export:all"
    assert Permissions.PROJECT_EXPORT == "project:export:assigned"


def test_admin_role_contains_global_export_permissions() -> None:
    admin_permissions = _role_permissions("admin")
    assert Permissions.DATASET_EXPORT_ALL in admin_permissions
    assert Permissions.PROJECT_EXPORT_ALL in admin_permissions


def test_project_resource_roles_contain_assigned_project_export_permission() -> None:
    role_names = [
        "project_owner",
        "project_manager",
        "project_viewer",
        "project_annotator",
        "project_runtime_operator",
    ]

    for role_name in role_names:
        permissions = _role_permissions(role_name)
        assert Permissions.PROJECT_EXPORT in permissions


def test_dataset_resource_roles_contain_assigned_dataset_export_permission() -> None:
    role_names = [
        "dataset_owner",
        "dataset_manager",
        "dataset_viewer",
        "dataset_editor",
        "dataset_uploader",
    ]

    for role_name in role_names:
        permissions = _role_permissions(role_name)
        assert Permissions.DATASET_EXPORT in permissions
