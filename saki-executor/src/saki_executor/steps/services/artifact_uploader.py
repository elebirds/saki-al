from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Callable

import httpx
from loguru import logger

ClientFactory = Callable[..., Any]


class ArtifactUploader:
    def __init__(
        self,
        *,
        client_factory: ClientFactory | None = None,
        max_attempts: int = 3,
        retry_backoff_sec: tuple[float, ...] = (1.0, 2.0),
    ) -> None:
        self._client_factory = client_factory or httpx.AsyncClient
        self._max_attempts = max(1, int(max_attempts))
        self._retry_backoff_sec = retry_backoff_sec or (1.0,)

    async def upload_with_retry(
        self,
        *,
        artifact_path: Path,
        upload_url: str,
        headers: dict[str, str],
    ) -> None:
        if not upload_url:
            raise RuntimeError("上传 URL 为空")

        payload = await asyncio.to_thread(artifact_path.read_bytes)
        request_headers = dict(headers)
        if not any(str(key).lower() == "content-length" for key in request_headers):
            request_headers["Content-Length"] = str(len(payload))

        attempt = 0
        last_error: Exception | None = None
        while attempt < self._max_attempts:
            attempt += 1
            try:
                async with self._client_factory(timeout=180) as client:
                    response = await client.put(
                        upload_url,
                        content=payload,
                        headers=request_headers,
                    )
                    status_code = int(response.status_code)
                    if 400 <= status_code < 500:
                        logger.error(
                            "制品上传失败（不可重试） artifact={} attempt={} status={}",
                            artifact_path.name,
                            attempt,
                            status_code,
                        )
                        response.raise_for_status()
                    response.raise_for_status()
                logger.info(
                    "制品上传成功 artifact={} attempt={} status={}",
                    artifact_path.name,
                    attempt,
                    int(response.status_code),
                )
                return
            except httpx.HTTPStatusError as exc:
                last_error = exc
                status_code = int(exc.response.status_code) if exc.response is not None else 0
                logger.warning(
                    "制品上传失败 artifact={} attempt={} status={} error={}",
                    artifact_path.name,
                    attempt,
                    status_code,
                    type(exc).__name__,
                )
                if 400 <= status_code < 500:
                    raise RuntimeError(
                        f"上传失败且状态码不可重试 status={status_code} artifact={artifact_path.name}"
                    ) from exc
                if attempt >= self._max_attempts:
                    break
                backoff = self._retry_backoff_sec[min(attempt - 1, len(self._retry_backoff_sec) - 1)]
                await asyncio.sleep(backoff)
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "制品上传异常 artifact={} attempt={} error={}",
                    artifact_path.name,
                    attempt,
                    type(exc).__name__,
                )
                if attempt >= self._max_attempts:
                    break
                backoff = self._retry_backoff_sec[min(attempt - 1, len(self._retry_backoff_sec) - 1)]
                await asyncio.sleep(backoff)

        raise RuntimeError(
            f"上传失败，已重试 {self._max_attempts} 次 artifact={artifact_path.name}"
        ) from last_error
