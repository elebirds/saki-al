from fastapi import Header
from saki_runtime.core.config import settings
from saki_runtime.core.exceptions import forbidden
from saki_runtime.jobs.manager import JobManager
from saki_runtime.jobs.runner import SubprocessJobRunner
from saki_runtime.plugins.registry import registry

# Initialize globals
registry.load_builtin_plugins()
plugins_map = {p.id: p.get_adapter() for p in registry._plugins.values()}
runner = SubprocessJobRunner(plugins_map)
job_manager = JobManager(runner, plugins_map)

async def verify_token(x_internal_token: str = Header(...)):
    if x_internal_token != settings.INTERNAL_TOKEN:
        raise forbidden("Invalid internal token")
    return x_internal_token
