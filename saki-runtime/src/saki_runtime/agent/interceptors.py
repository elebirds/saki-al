from __future__ import annotations

import time
from typing import Optional, Sequence, Tuple

import grpc
from loguru import logger


class _ClientCallDetails(grpc.aio.ClientCallDetails):
    def __init__(
        self,
        method: str,
        timeout: Optional[float],
        metadata: Optional[Sequence[Tuple[str, str]]],
        credentials: Optional[grpc.CallCredentials],
        wait_for_ready: Optional[bool],
        compression: Optional[grpc.Compression],
    ) -> None:
        self.method = method
        self.timeout = timeout
        self.metadata = metadata
        self.credentials = credentials
        self.wait_for_ready = wait_for_ready
        self.compression = compression


class AuthInterceptor(grpc.aio.ClientInterceptor):
    def __init__(self, token: str) -> None:
        self._token = token

    async def intercept_stream_stream(self, continuation, client_call_details, request_iterator):
        metadata = list(client_call_details.metadata or [])
        metadata.append(("x-internal-token", self._token))
        new_details = _ClientCallDetails(
            method=client_call_details.method,
            timeout=client_call_details.timeout,
            metadata=metadata,
            credentials=client_call_details.credentials,
            wait_for_ready=client_call_details.wait_for_ready,
            compression=client_call_details.compression,
        )
        return await continuation(new_details, request_iterator)


class LoggingInterceptor(grpc.aio.ClientInterceptor):
    async def intercept_stream_stream(self, continuation, client_call_details, request_iterator):
        start = time.monotonic()
        logger.info("gRPC stream start: {}", client_call_details.method)
        call = await continuation(client_call_details, request_iterator)
        call.add_done_callback(
            lambda _: logger.info(
                "gRPC stream done: {} ({:.2f}s)",
                client_call_details.method,
                time.monotonic() - start,
            )
        )
        return call
