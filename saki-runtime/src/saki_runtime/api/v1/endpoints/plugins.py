import uuid
from fastapi import APIRouter, Depends, Query
from saki_runtime.api.v1.deps import verify_token
from saki_runtime.core.exceptions import not_found
from saki_runtime.plugins.registry import registry

router = APIRouter()

@router.get("", dependencies=[Depends(verify_token)])
async def list_plugins():
    return {"request_id": str(uuid.uuid4()), "plugins": registry.list_plugins()}

@router.get("/{plugin_id}/schema", dependencies=[Depends(verify_token)])
async def get_plugin_schema(plugin_id: str, op: str = Query(...)):
    plugin = registry.get(plugin_id)
    if not plugin:
        raise not_found(f"Plugin {plugin_id} not found")
    return {"request_id": str(uuid.uuid4()), "schema": plugin.get_schema(op)}

@router.get("/{plugin_id}/capabilities", dependencies=[Depends(verify_token)])
async def get_plugin_capabilities(plugin_id: str):
    plugin = registry.get(plugin_id)
    if not plugin:
        raise not_found(f"Plugin {plugin_id} not found")
    return {"request_id": str(uuid.uuid4()), "capabilities": plugin.capabilities}
