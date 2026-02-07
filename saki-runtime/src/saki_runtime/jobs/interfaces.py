from abc import ABC, abstractmethod
from typing import Any, Dict

from saki_runtime.jobs.workspace import Workspace


class PluginAdapter(ABC):
    @property
    @abstractmethod
    def trainer_entrypoint(self) -> str:
        """Return the python module or script path to run."""
        pass

    @property
    @abstractmethod
    def plugin_version(self) -> str:
        pass

    @property
    def capabilities(self) -> list[str]:
        return []

    @abstractmethod
    def validate_params(self, params: Dict[str, Any]) -> None:
        pass

    @abstractmethod
    async def prepare(self, workspace: Workspace, params: Dict[str, Any]) -> None:
        pass


class JobRunner(ABC):
    @abstractmethod
    async def start_train(self, workspace: Workspace, gpu_id: int) -> None:
        pass

    @abstractmethod
    async def stop(self, job_id: str) -> None:
        pass
