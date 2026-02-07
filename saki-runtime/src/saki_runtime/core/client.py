import asyncio
from typing import Any, AsyncIterator, Dict, List, Optional, Type, TypeVar

import httpx
from loguru import logger
from pydantic import BaseModel

from saki_runtime.core.config import settings
from saki_runtime.core.exceptions import (
    RuntimeErrorBase,
    forbidden,
    internal_error,
    invalid_argument,
    not_found,
    unavailable,
)
from saki_runtime.schemas.ir import DetAnnotationIR, LabelIR, SampleIR

T = TypeVar("T", bound=BaseModel)


class SakiClient:
    def __init__(self) -> None:
        self.base_url = settings.SAKI_BASE_URL.rstrip("/")
        self.headers = {
            "X-Internal-Token": settings.INTERNAL_TOKEN,
            "Content-Type": "application/json",
        }
        self.timeout = settings.HTTP_TIMEOUT_SEC

    async def _request(
        self, method: str, path: str, params: Optional[Dict[str, Any]] = None
    ) -> Any:
        url = f"{self.base_url}{path}"
        retries = 3
        backoff_factor = 0.5

        for attempt in range(retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.request(
                        method, url, params=params, headers=self.headers
                    )

                if response.status_code == 404:
                    raise not_found(f"Resource not found: {path}")
                elif response.status_code in (401, 403):
                    raise forbidden(f"Access denied: {path}")
                elif 400 <= response.status_code < 500:
                    raise invalid_argument(
                        f"Invalid argument: {path}",
                        details={"body": response.text[:1000]},
                    )
                elif response.status_code >= 500:
                    response.raise_for_status()  # Trigger retry for 5xx

                return response.json()

            except (httpx.RequestError, httpx.HTTPStatusError) as e:
                is_last_attempt = attempt == retries
                should_retry = (
                    isinstance(e, httpx.RequestError)
                    or (
                        isinstance(e, httpx.HTTPStatusError)
                        and e.response.status_code >= 500
                    )
                )

                if should_retry and not is_last_attempt:
                    sleep_time = backoff_factor * (2**attempt)
                    logger.warning(
                        f"Request failed ({method} {url}), retrying in {sleep_time:.2f}s. Error: {e}"
                    )
                    await asyncio.sleep(sleep_time)
                    continue
                
                if isinstance(e, httpx.HTTPStatusError) and e.response.status_code >= 500:
                     raise unavailable(f"Service unavailable: {path}", details={"error": str(e)})

                if is_last_attempt:
                     raise unavailable(f"Connection failed: {path}", details={"error": str(e)})
        
        raise internal_error("Unexpected execution path in _request")

    async def _iter_pages(
        self, path: str, model: Type[T], params: Dict[str, Any]
    ) -> AsyncIterator[T]:
        cursor = None
        while True:
            current_params = params.copy()
            if cursor:
                current_params["cursor"] = cursor

            data = await self._request("GET", path, params=current_params)
            
            # Assuming standard pagination response: { "items": [...], "next_cursor": "..." }
            # Adjust based on actual API contract if different.
            items = data.get("items", [])
            next_cursor = data.get("next_cursor")

            for item in items:
                yield model.model_validate(item)

            if not next_cursor:
                break
            cursor = next_cursor

    async def get_labels(self, project_id: str) -> List[LabelIR]:
        path = f"/internal/v1/projects/{project_id}/labels"
        data = await self._request("GET", path)
        # Assuming response is a list or { "items": [...] }
        # If it's a list directly:
        if isinstance(data, list):
            return [LabelIR.model_validate(item) for item in data]
        # If wrapped
        return [LabelIR.model_validate(item) for item in data.get("items", [])]

    async def iter_samples(self, commit_id: str) -> AsyncIterator[SampleIR]:
        path = f"/internal/v1/commits/{commit_id}/samples"
        async for sample in self._iter_pages(path, SampleIR, {"limit": 1000}):
            yield sample

    async def iter_annotations(self, commit_id: str) -> AsyncIterator[DetAnnotationIR]:
        path = f"/internal/v1/commits/{commit_id}/annotations"
        async for ann in self._iter_pages(path, DetAnnotationIR, {"limit": 1000}):
            yield ann

    async def iter_unlabeled_samples(self, commit_id: str) -> AsyncIterator[SampleIR]:
        path = f"/internal/v1/commits/{commit_id}/unlabeled-samples"
        async for sample in self._iter_pages(path, SampleIR, {"limit": 1000}):
            yield sample

# Global client instance
saki_client = SakiClient()
