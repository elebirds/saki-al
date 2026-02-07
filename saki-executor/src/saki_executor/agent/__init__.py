from __future__ import annotations

__all__ = ["AgentClient"]


def __getattr__(name: str):
    if name == "AgentClient":
        from saki_executor.agent.client import AgentClient
        return AgentClient
    raise AttributeError(name)
