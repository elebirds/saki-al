from __future__ import annotations

import json

from saki_plugin_sdk.gen.worker.v1 import worker_pb2
from saki_plugin_sdk.worker_main import main as run_worker_main

from saki_mapping_engine.fedo_mapper import map_fedo_obb


def _handle(request: worker_pb2.ExecuteRequest, emit) -> bytes:
    if request.action != "map_fedo_obb":
        raise ValueError(f"unsupported action: {request.action}")

    payload = json.loads(request.payload.decode("utf-8")) if request.payload else {}
    result = map_fedo_obb(payload)
    return json.dumps(result).encode("utf-8")


def main() -> None:
    run_worker_main(_handle)


if __name__ == "__main__":
    main()
