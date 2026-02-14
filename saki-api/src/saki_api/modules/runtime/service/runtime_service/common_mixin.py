"""Common helper mixin for runtime service."""

from __future__ import annotations

import re
import uuid

from saki_api.core.exceptions import BadRequestAppException
from saki_api.modules.runtime.service.catalog.runtime_plugin_catalog_service import (
    extract_executor_plugins,
)


class RuntimeServiceCommonMixin:
    @staticmethod
    def _is_downloadable_uri(uri: str | None) -> bool:
        raw = str(uri or "").strip()
        return raw.startswith("s3://") or raw.startswith("http://") or raw.startswith("https://")

    @staticmethod
    def _normalize_branch_segment(raw: str, *, fallback: str) -> str:
        value = re.sub(r"[^0-9A-Za-z._-]+", "-", str(raw or "").strip().lower())
        value = value.strip("._-")
        return value or fallback

    @staticmethod
    def _truncate(raw: str, *, max_len: int = 100) -> str:
        value = str(raw or "").strip()
        if len(value) <= max_len:
            return value
        return value[:max_len].rstrip("._-/") or value[:max_len]

    async def _known_plugin_ids(self) -> set[str]:
        rows = await self.runtime_executor_repo.list()
        plugin_ids: set[str] = set()
        for executor in rows:
            for item in extract_executor_plugins(executor.plugin_ids or {}):
                plugin_ids.add(item.plugin_id)
        return plugin_ids

    async def _validate_plugin_id(self, plugin_id: str) -> None:
        value = str(plugin_id or "").strip()
        if not value:
            raise BadRequestAppException("plugin_id/model_arch is required")
        known = await self._known_plugin_ids()
        if known and value not in known:
            raise BadRequestAppException(f"plugin_id/model_arch not found in runtime catalog: {value}")

    async def _next_available_branch_name(self, *, project_id: uuid.UUID, base_name: str) -> str:
        candidate = self._truncate(base_name, max_len=100)
        suffix = 1
        while True:
            if not await self.project_gateway.get_branch_by_name(project_id=project_id, name=candidate):
                return candidate
            suffix_token = f"-{suffix}"
            prefix_len = max(1, 100 - len(suffix_token))
            candidate_prefix = self._truncate(base_name, max_len=prefix_len)
            candidate = f"{candidate_prefix}{suffix_token}"
            suffix += 1
