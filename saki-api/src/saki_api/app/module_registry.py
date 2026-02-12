from __future__ import annotations

from saki_api.app.module_contract import AppModule
from saki_api.modules.access.app_module import access_app_module
from saki_api.modules.annotation.app_module import annotation_app_module
from saki_api.modules.project.app_module import project_app_module
from saki_api.modules.runtime.app_module import runtime_app_module
from saki_api.modules.storage.app_module import storage_app_module
from saki_api.modules.system.app_module import system_app_module


def get_app_modules() -> tuple[AppModule, ...]:
    # Order matters for route registration and lifecycle startup.
    return (
        system_app_module,
        access_app_module,
        storage_app_module,
        project_app_module,
        annotation_app_module,
        runtime_app_module,
    )
