from __future__ import annotations

import asyncio
import hashlib
import os
from pathlib import Path
import sys
from typing import Any, Awaitable, Callable
import uuid

from loguru import logger

from saki_executor.core.config import settings
from saki_executor.plugins.ipc import protocol

try:
    import zmq
    import zmq.asyncio
except Exception as exc:  # pragma: no cover
    raise RuntimeError("pyzmq is required for subprocess plugin worker") from exc

EventHandler = Callable[[str, dict[str, Any]], Awaitable[None]]


class WorkerCommandError(RuntimeError):
    def __init__(self, *, error_code: str, error_message: str) -> None:
        super().__init__(error_message or error_code or "worker command failed")
        self.error_code = error_code
        self.error_message = error_message or error_code or "worker command failed"


class PluginWorkerClient:
    def __init__(
        self,
        *,
        plugin_id: str,
        step_id: str,
        event_handler: EventHandler,
    ) -> None:
        self._plugin_id = plugin_id
        self._step_id = step_id
        self._event_handler = event_handler
        self._ctx = zmq.asyncio.Context.instance()
        self._process: asyncio.subprocess.Process | None = None
        self._req_socket: zmq.asyncio.Socket | None = None
        self._sub_socket: zmq.asyncio.Socket | None = None
        self._command_endpoint = ""
        self._event_endpoint = ""
        self._socket_paths: list[Path] = []
        self._event_task: asyncio.Task | None = None
        self._stdout_task: asyncio.Task | None = None
        self._stderr_task: asyncio.Task | None = None
        self._startup_lock = asyncio.Lock()
        self._request_lock = asyncio.Lock()
        self._closed = False
        self._started = False

    async def start(self) -> None:
        async with self._startup_lock:
            if self._started:
                return
            self._closed = False
            self._prepare_endpoints()
            await self._spawn_worker()
            self._open_sockets()
            self._start_background_tasks()
            self._started = True
            try:
                await self._wait_ready()
            except Exception:
                self._started = False
                await self.terminate()
                raise

    async def request(
        self,
        *,
        action: str,
        payload: dict[str, Any],
        timeout_sec: int | None = None,
    ) -> protocol.WorkerReplyEnvelope:
        if self._closed:
            raise RuntimeError("worker client is closed")
        if not self._started:
            await self.start()
        if self._req_socket is None:
            raise RuntimeError("worker request socket is not initialized")

        async with self._request_lock:
            request_id = str(uuid.uuid4())
            cmd = protocol.WorkerCommandEnvelope(
                request_id=request_id,
                action=action,
                step_id=self._step_id,
            )
            command_payload = protocol.build_command_payload(
                envelope=cmd,
                payload=payload,
            )
            await self._req_socket.send_json(command_payload)
            raw_reply = await self._recv_reply_or_raise(timeout_sec=timeout_sec)
            reply = protocol.WorkerReplyEnvelope.from_dict(raw_reply)
            if not reply.ok:
                raise WorkerCommandError(
                    error_code=reply.error_code,
                    error_message=reply.error_message,
                )
            return reply

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True

        try:
            await self._shutdown_gracefully()
        except Exception:
            pass
        await self._terminate_worker()
        self._stop_background_tasks()
        self._close_sockets()
        self._cleanup_socket_paths()
        self._started = False

    async def terminate(self) -> None:
        self._closed = True
        await self._terminate_worker()
        self._stop_background_tasks()
        self._close_sockets()
        self._cleanup_socket_paths()
        self._started = False

    @property
    def command_endpoint(self) -> str:
        return self._command_endpoint

    @property
    def event_endpoint(self) -> str:
        return self._event_endpoint

    def _prepare_endpoints(self) -> None:
        raw_dir = Path(settings.PLUGIN_WORKER_IPC_DIR)
        raw_dir.mkdir(parents=True, exist_ok=True)
        short_id = hashlib.md5(self._step_id.encode("utf-8")).hexdigest()[:8]
        cmd_path = raw_dir / f"s_{short_id}_c.sock"
        evt_path = raw_dir / f"s_{short_id}_e.sock"
        self._socket_paths = [cmd_path, evt_path]
        self._cleanup_socket_paths()
        self._command_endpoint = f"ipc://{cmd_path}"
        self._event_endpoint = f"ipc://{evt_path}"
        logger.debug(
            "IPC endpoints prepared step_id={} cmd={} evt={}",
            self._step_id,
            self._command_endpoint,
            self._event_endpoint,
        )

    async def _spawn_worker(self) -> None:
        env = dict(os.environ)
        env["PYTHONUNBUFFERED"] = "1"
        env["OBJC_DISABLE_INITIALIZE_FORK_SAFETY"] = "YES"
        command = [
            sys.executable,
            "-m",
            "saki_executor.plugins.ipc.worker_main",
            "--plugin-id",
            self._plugin_id,
            "--step-id",
            self._step_id,
            "--command-endpoint",
            self._command_endpoint,
            "--event-endpoint",
            self._event_endpoint,
        ]
        self._process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )

    def _open_sockets(self) -> None:
        self._req_socket = self._ctx.socket(zmq.REQ)
        self._req_socket.connect(self._command_endpoint)
        self._sub_socket = self._ctx.socket(zmq.SUB)
        for topic in protocol.WORKER_EVENT_TOPICS:
            self._sub_socket.setsockopt(zmq.SUBSCRIBE, topic.encode("utf-8"))
        self._sub_socket.connect(self._event_endpoint)

    def _start_background_tasks(self) -> None:
        self._event_task = asyncio.create_task(
            self._event_loop(),
            name=f"worker-events-{self._step_id}",
        )
        process = self._process
        if process and process.stdout:
            self._stdout_task = asyncio.create_task(
                self._stream_log_loop(process.stdout, "INFO"),
                name=f"worker-stdout-{self._step_id}",
            )
        if process and process.stderr:
            self._stderr_task = asyncio.create_task(
                self._stream_log_loop(process.stderr, "ERROR"),
                name=f"worker-stderr-{self._step_id}",
            )

    async def _wait_ready(self) -> None:
        timeout = max(1, int(settings.PLUGIN_WORKER_STARTUP_TIMEOUT_SEC))
        poll_sec = max(0.05, int(settings.PLUGIN_WORKER_REQ_POLL_INTERVAL_MS) / 1000.0)
        deadline = asyncio.get_running_loop().time() + timeout
        last_error = ""
        while asyncio.get_running_loop().time() < deadline:
            if self._process and self._process.returncode is not None:
                raise RuntimeError(
                    f"worker exited before ready plugin_id={self._plugin_id} "
                    f"step_id={self._step_id} return_code={self._process.returncode}"
                )
            try:
                await self.request(action="ping", payload={}, timeout_sec=1)
                return
            except Exception as exc:
                last_error = str(exc)
                await asyncio.sleep(poll_sec)
        raise RuntimeError(
            f"worker startup timeout plugin_id={self._plugin_id} "
            f"command_endpoint={self._command_endpoint} "
            f"event_endpoint={self._event_endpoint} error={last_error}"
        )

    async def _recv_reply_or_raise(self, *, timeout_sec: int | None) -> dict[str, Any]:
        if self._req_socket is None:
            raise RuntimeError("worker request socket is missing")
        if timeout_sec is None:
            raw = await self._req_socket.recv_json()
        else:
            try:
                raw = await asyncio.wait_for(
                    self._req_socket.recv_json(),
                    timeout=max(1, int(timeout_sec)),
                )
            except asyncio.TimeoutError as exc:
                if self._process and self._process.returncode is not None:
                    raise RuntimeError(
                        f"worker process exited plugin_id={self._plugin_id} "
                        f"return_code={self._process.returncode}"
                    ) from exc
                raise RuntimeError(f"worker request timeout action endpoint={self._command_endpoint}") from exc
        if not isinstance(raw, dict):
            raise RuntimeError("invalid worker reply payload")
        return raw

    async def _shutdown_gracefully(self) -> None:
        if not self._started:
            return
        try:
            await self.request(
                action="shutdown",
                payload={},
                timeout_sec=max(1, int(settings.PLUGIN_WORKER_TERM_TIMEOUT_SEC)),
            )
        except Exception:
            pass

    async def _terminate_worker(self) -> None:
        process = self._process
        self._process = None
        if process is None:
            return
        if process.returncode is not None:
            return
        process.terminate()
        timeout = max(1, int(settings.PLUGIN_WORKER_TERM_TIMEOUT_SEC))
        try:
            await asyncio.wait_for(process.wait(), timeout=timeout)
            return
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()

    async def _event_loop(self) -> None:
        if self._sub_socket is None:
            return
        try:
            while True:
                frames = await self._sub_socket.recv_multipart()
                topic, envelope, payload = protocol.parse_event_frames(frames)
                if envelope.step_id and envelope.step_id != self._step_id:
                    continue
                if not isinstance(payload, dict):
                    continue
                event_type = envelope.event_type or topic
                try:
                    await self._event_handler(event_type, payload)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("worker event handler error step_id={} event_type={}", self._step_id, event_type)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("worker event loop failed step_id={}", self._step_id)

    async def _stream_log_loop(self, stream: asyncio.StreamReader, level: str) -> None:
        try:
            while True:
                raw = await stream.readline()
                if not raw:
                    break
                message = raw.decode("utf-8", errors="replace").strip()
                if not message:
                    continue
                payload = {
                    "level": level,
                    "message": f"[worker:{self._plugin_id}] {message}",
                }
                try:
                    await self._event_handler("log", payload)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("worker stream log forward failed step_id={}", self._step_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("worker stream read failed step_id={} level={}", self._step_id, level)

    def _stop_background_tasks(self) -> None:
        for task in (self._event_task, self._stdout_task, self._stderr_task):
            if task and not task.done():
                task.cancel()
        self._event_task = None
        self._stdout_task = None
        self._stderr_task = None

    def _close_sockets(self) -> None:
        if self._req_socket is not None:
            self._req_socket.close(linger=0)
            self._req_socket = None
        if self._sub_socket is not None:
            self._sub_socket.close(linger=0)
            self._sub_socket = None

    def _cleanup_socket_paths(self) -> None:
        for path in self._socket_paths:
            try:
                if path.exists():
                    path.unlink()
                    logger.debug("cleaned legacy socket file: {}", path)
            except Exception as exc:
                logger.warning("failed to cleanup socket {}: {}", path, exc)
