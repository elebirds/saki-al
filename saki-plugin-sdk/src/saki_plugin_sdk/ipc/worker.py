"""Generic plugin worker process – runs inside the plugin's own virtualenv.

Usage from a plugin package::

    from saki_plugin_sdk.ipc.worker import run_worker
    from my_plugin.plugin import MyPlugin

    def main():
        run_worker(MyPlugin())

    if __name__ == "__main__":
        main()
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from typing import Any

from loguru import logger

from saki_plugin_sdk.base import ExecutorPlugin
from saki_plugin_sdk.ipc import protocol
from saki_plugin_sdk.workspace import Workspace

try:
    from saki_ir.proto.saki.ir.v1 import annotation_ir_pb2 as irpb  # type: ignore
except Exception:
    irpb = None  # type: ignore

try:
    import zmq
except Exception as exc:  # pragma: no cover
    raise RuntimeError("pyzmq is required for plugin worker process") from exc


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="saki plugin worker")
    parser.add_argument("--plugin-id", required=True)
    parser.add_argument("--step-id", required=True)
    parser.add_argument("--command-endpoint", required=True)
    parser.add_argument("--event-endpoint", required=True)
    return parser.parse_args()


def _publish_event(
    *,
    pub_socket,
    event_type: str,
    step_id: str,
    payload: dict[str, Any],
    request_id: str = "",
) -> None:
    envelope = protocol.WorkerEventEnvelope(
        event_type=event_type,
        step_id=step_id,
        ts=protocol.now_ts(),
        request_id=request_id,
    )
    frames = protocol.build_event_frames(
        topic=event_type,
        envelope=envelope,
        payload=payload,
    )
    pub_socket.send_multipart(frames)


def _build_workspace(workspace_root: str) -> Workspace:
    root = Path(str(workspace_root or ""))
    if not root.name:
        raise RuntimeError("workspace_root is required")
    workspace = Workspace(str(root.parent), root.name)
    workspace.ensure()
    return workspace


async def _run_prepare_data(
    *,
    plugin: ExecutorPlugin,
    payload: dict[str, Any],
) -> None:
    workspace = _build_workspace(str(payload.get("workspace_root") or ""))
    labels = protocol.read_json(Path(str(payload.get("labels_path") or "")))
    samples = protocol.read_json(Path(str(payload.get("samples_path") or "")))
    annotations = protocol.read_json(Path(str(payload.get("annotations_path") or "")))
    splits_path_raw = str(payload.get("splits_path") or "").strip()
    if splits_path_raw:
        splits_path = Path(splits_path_raw)
        if splits_path.is_file():
            splits = protocol.read_json(splits_path)
        else:
            splits = {}
    else:
        splits = {}
    dataset_ir_path = Path(str(payload.get("dataset_ir_path") or ""))
    if irpb is not None:
        dataset_ir = irpb.DataBatchIR()
        dataset_ir.ParseFromString(dataset_ir_path.read_bytes())
    else:
        dataset_ir = None
    if not isinstance(labels, list):
        labels = []
    if not isinstance(samples, list):
        samples = []
    if not isinstance(annotations, list):
        annotations = []
    if not isinstance(splits, dict):
        splits = {}
    await plugin.prepare_data(
        workspace=workspace,
        labels=labels,
        samples=samples,
        annotations=annotations,
        dataset_ir=dataset_ir,
        splits=splits,
    )


async def _run_train_like(
    *,
    plugin: ExecutorPlugin,
    payload: dict[str, Any],
    step_id: str,
    request_id: str,
    pub_socket,
    method_name: str,
) -> str:
    workspace = _build_workspace(str(payload.get("workspace_root") or ""))
    params = protocol.read_json(Path(str(payload.get("params_path") or "")))
    if not isinstance(params, dict):
        params = {}

    async def _emit(event_type: str, event_payload: dict[str, Any]) -> None:
        _publish_event(
            pub_socket=pub_socket,
            event_type=event_type,
            step_id=step_id,
            payload=event_payload,
            request_id=request_id,
        )

    method = getattr(plugin, method_name, None)
    if not callable(method):
        raise RuntimeError(f"plugin method not found: {method_name}")
    output = await method(
        workspace=workspace,
        params=params,
        emit=_emit,
    )
    result_path = Path(str(payload.get("result_path") or ""))
    protocol.write_json(result_path, protocol.train_output_to_dict(output))
    return str(result_path)


async def _run_predict(
    *,
    plugin: ExecutorPlugin,
    payload: dict[str, Any],
) -> str:
    workspace = _build_workspace(str(payload.get("workspace_root") or ""))
    samples = protocol.read_json(Path(str(payload.get("samples_path") or "")))
    params = protocol.read_json(Path(str(payload.get("params_path") or "")))
    strategy = str(payload.get("strategy") or "")
    if not isinstance(samples, list):
        samples = []
    if not isinstance(params, dict):
        params = {}
    candidates = await plugin.predict_unlabeled_batch(
        workspace=workspace,
        unlabeled_samples=samples,
        strategy=strategy,
        params=params,
    )
    result_path = Path(str(payload.get("result_path") or ""))
    protocol.write_json(result_path, {"candidates": candidates})
    return str(result_path)


def _run_loop(plugin: ExecutorPlugin, args: argparse.Namespace) -> int:
    """Synchronous ZMQ REP/PUB loop that dispatches commands to the plugin."""
    context = zmq.Context()
    rep_socket = context.socket(zmq.REP)
    pub_socket = context.socket(zmq.PUB)
    rep_socket.bind(args.command_endpoint)
    pub_socket.bind(args.event_endpoint)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def _await(coro):
        return loop.run_until_complete(coro)

    try:
        # Build context for on_load
        load_context = {
            "plugin_id": args.plugin_id,
            "step_id": args.step_id,
            "command_endpoint": args.command_endpoint,
            "event_endpoint": args.event_endpoint,
        }

        # Call on_load lifecycle hook
        _await(plugin.on_load(load_context))

        _publish_event(
            pub_socket=pub_socket,
            event_type="worker",
            step_id=args.step_id,
            payload={
                "level": "INFO",
                "message": (
                    f"worker started plugin_id={args.plugin_id} "
                    f"command_endpoint={args.command_endpoint} "
                    f"event_endpoint={args.event_endpoint}"
                ),
            },
        )

        running = True
        while running:
            raw = rep_socket.recv_json()
            envelope = protocol.WorkerReplyEnvelope(
                request_id="",
                ok=False,
                error_code="INTERNAL",
                error_message="unknown error",
                result_path="",
            )
            try:
                cmd, payload = protocol.parse_command_payload(raw)
                envelope = protocol.WorkerReplyEnvelope(
                    request_id=cmd.request_id,
                    ok=True,
                    error_code="",
                    error_message="",
                    result_path="",
                )
                action = str(cmd.action or "").strip()

                if action == "ping":
                    rep_socket.send_json(envelope.to_dict())
                    continue

                if action == "prepare_data":
                    workspace = _build_workspace(str(payload.get("workspace_root") or ""))
                    _await(plugin.on_start(args.step_id, workspace))
                    try:
                        _await(
                            _run_prepare_data(
                                plugin=plugin,
                                payload=payload,
                            )
                        )
                    finally:
                        _await(plugin.on_stop(args.step_id, workspace))
                    rep_socket.send_json(envelope.to_dict())
                    continue

                if action in {"train", "eval", "export", "upload_artifact"}:
                    workspace = _build_workspace(str(payload.get("workspace_root") or ""))
                    _await(plugin.on_start(args.step_id, workspace))
                    try:
                        result_path = _await(
                            _run_train_like(
                                plugin=plugin,
                                payload=payload,
                                step_id=args.step_id,
                                request_id=cmd.request_id,
                                pub_socket=pub_socket,
                                method_name=action,
                            )
                        )
                        rep_socket.send_json(
                            protocol.WorkerReplyEnvelope(
                                request_id=cmd.request_id,
                                ok=True,
                                error_code="",
                                error_message="",
                                result_path=result_path,
                            ).to_dict()
                        )
                    finally:
                        _await(plugin.on_stop(args.step_id, workspace))
                    continue

                if action == "predict_unlabeled_batch":
                    workspace = _build_workspace(str(payload.get("workspace_root") or ""))
                    _await(plugin.on_start(args.step_id, workspace))
                    try:
                        result_path = _await(
                            _run_predict(
                                plugin=plugin,
                                payload=payload,
                            )
                        )
                        rep_socket.send_json(
                            protocol.WorkerReplyEnvelope(
                                request_id=cmd.request_id,
                                ok=True,
                                error_code="",
                                error_message="",
                                result_path=result_path,
                            ).to_dict()
                        )
                    finally:
                        _await(plugin.on_stop(args.step_id, workspace))
                    continue

                if action == "shutdown":
                    running = False
                    rep_socket.send_json(envelope.to_dict())
                    continue

                raise RuntimeError(f"unsupported worker action: {action or '<empty>'}")
            except Exception as exc:
                logger.exception("worker command failed step_id={} error={}", args.step_id, exc)
                error_message = str(exc)
                _publish_event(
                    pub_socket=pub_socket,
                    event_type="worker",
                    step_id=args.step_id,
                    payload={"level": "ERROR", "message": error_message},
                    request_id=envelope.request_id,
                )
                rep_socket.send_json(
                    protocol.WorkerReplyEnvelope(
                        request_id=envelope.request_id,
                        ok=False,
                        error_code=type(exc).__name__,
                        error_message=error_message,
                        result_path="",
                    ).to_dict()
                )
    finally:
        # Call on_unload lifecycle hook
        try:
            _await(plugin.on_unload())
        except Exception:
            logger.exception("worker on_unload failed step_id={}", args.step_id)
        finally:
            loop.close()
            asyncio.set_event_loop(None)

        rep_socket.close(linger=0)
        pub_socket.close(linger=0)
        context.term()
    return 0


def run_worker(plugin: ExecutorPlugin) -> None:
    """Entry point called by each plugin's ``worker.py`` / ``__main__.py``.

    Parses CLI arguments (``--plugin-id``, ``--step-id``, ``--command-endpoint``,
    ``--event-endpoint``) and starts the ZMQ command loop.
    """
    args = _parse_args()
    raise SystemExit(_run_loop(plugin, args))
