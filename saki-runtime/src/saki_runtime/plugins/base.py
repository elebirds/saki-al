from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from saki_runtime.jobs.interfaces import PluginAdapter
from saki_runtime.jobs.workspace import Workspace


class PluginBase(ABC):
    @property
    @abstractmethod
    def id(self) -> str:
        pass

    @property
    @abstractmethod
    def version(self) -> str:
        pass

    @property
    @abstractmethod
    def capabilities(self) -> List[str]:
        pass

    @abstractmethod
    def get_schema(self, op: str) -> Dict[str, Any]:
        pass

    @abstractmethod
    def get_adapter(self) -> PluginAdapter:
        pass
