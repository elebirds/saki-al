from __future__ import annotations

from typing import Protocol

from fastapi import APIRouter


class AppModule(Protocol):
    """Application composition contract for business modules."""

    name: str

    def register_routes(self, api_router: APIRouter) -> None:
        """Attach module routers into api router."""

    async def startup(self) -> None:
        """Run module startup hook."""

    async def shutdown(self) -> None:
        """Run module shutdown hook."""
