from __future__ import annotations

import sys
from collections.abc import Callable

from saki_plugin_sdk.gen.worker.v1 import worker_pb2
from saki_plugin_sdk.worker_runtime import run_worker_session


def main(handler: Callable[[worker_pb2.ExecuteRequest, Callable[[str, bytes], None]], bytes]) -> None:
    run_worker_session(sys.stdin.buffer, sys.stdout.buffer, handler)
