import asyncio

from saki_runtime.agent.client import AgentClient
from saki_runtime.agent.command_router import CommandRouter
from saki_runtime.jobs.manager import JobManager
from saki_runtime.jobs.runner import SubprocessJobRunner
from saki_runtime.plugins.registry import registry


async def run_agent() -> None:
    registry.load_builtin_plugins()
    plugins_map = {p.id: p.get_adapter() for p in registry._plugins.values()}
    runner = SubprocessJobRunner(plugins_map)
    job_manager = JobManager(runner, plugins_map)
    router = CommandRouter(job_manager)
    client = AgentClient(router)
    job_manager.set_event_publisher(client.publish_event)
    await client.run()


def main() -> None:
    asyncio.run(run_agent())


if __name__ == "__main__":
    main()
