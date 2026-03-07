import pytest

from saki_executor.plugins.ipc.log_coalescer import LogCoalescer
from saki_executor.plugins.ipc.log_normalizer import normalize_stdio_log_line


def test_stderr_loguru_debug_should_keep_debug_level():
    line = (
        "2026-03-01 23:44:06.866 | DEBUG    | saki_plugin_sdk.logger:debug:53"
        " - [yolo_det_v1|step-1] Step completed"
    )
    payload = normalize_stdio_log_line(raw_line=line, plugin_id="yolo_det_v1", stream="stderr")
    assert payload is not None
    assert payload["level"] == "DEBUG"
    assert payload["message"].endswith("Step completed")


def test_stdio_log_normalizer_should_strip_ansi_and_control_sequences():
    line = "\x1b[K\x1b[34m\x1b[1mval:\x1b[0m Fast image access ✅\x1b[0m"
    payload = normalize_stdio_log_line(raw_line=line, plugin_id="yolo_det_v1", stream="stdout")
    assert payload is not None
    assert "\x1b" not in payload["message"]
    assert "[0m" not in payload["message"]
    assert payload["message"].startswith("val:")


def test_stdio_log_normalizer_should_keep_leading_spaces_for_progress_lines():
    line = "\x1b[K      30/30         0G      1.248      4.694      1.192"
    payload = normalize_stdio_log_line(raw_line=line, plugin_id="yolo_det_v1", stream="stdout")
    assert payload is not None
    assert payload["message"].startswith("      30/30")


def test_stdio_log_normalizer_should_use_last_carriage_return_segment():
    line = "30/30 ... 0%\r      30/30 ... 50%\r      30/30 ... 100%\n"
    payload = normalize_stdio_log_line(raw_line=line, plugin_id="yolo_det_v1", stream="stdout")
    assert payload is not None
    assert payload["message"] == "      30/30 ... 100%"


@pytest.mark.anyio
async def test_log_coalescer_should_group_lines_with_group_meta():
    emitted: list[dict] = []

    async def _emit(payload: dict) -> None:
        emitted.append(payload)

    coalescer = LogCoalescer(emit=_emit, idle_timeout_sec=10.0)

    base_meta = {"source": "worker_stdio", "stream": "stdout", "plugin_id": "yolo_det_v1"}
    await coalescer.add(
        {
            "level": "INFO",
            "message": "line-1",
            "raw_message": "line-1",
            "meta": dict(base_meta),
        }
    )
    await coalescer.add(
        {
            "level": "INFO",
            "message": "line-2",
            "raw_message": "line-2",
            "meta": dict(base_meta),
        }
    )
    await coalescer.flush()

    assert len(emitted) == 1
    row = emitted[0]
    assert row["message"] == "line-1\nline-2"
    assert row["raw_message"] == "line-1\nline-2"
    assert row["meta"]["collapsed"] is True
    assert row["meta"]["line_count"] == 2
    assert str(row["meta"].get("group_id") or "").strip() != ""


@pytest.mark.anyio
async def test_log_coalescer_should_split_on_different_producer_group_id():
    emitted: list[dict] = []

    async def _emit(payload: dict) -> None:
        emitted.append(payload)

    coalescer = LogCoalescer(emit=_emit, idle_timeout_sec=10.0)
    await coalescer.add(
        {
            "level": "INFO",
            "message": "part-1",
            "raw_message": "part-1",
            "meta": {"source": "worker_stdio", "stream": "stdout", "group_id": "g1"},
        }
    )
    await coalescer.add(
        {
            "level": "INFO",
            "message": "part-2",
            "raw_message": "part-2",
            "meta": {"source": "worker_stdio", "stream": "stdout", "group_id": "g2"},
        }
    )
    await coalescer.flush()

    assert len(emitted) == 2
    assert emitted[0]["message"] == "part-1"
    assert emitted[1]["message"] == "part-2"


@pytest.mark.anyio
async def test_log_coalescer_should_preserve_producer_group_id_for_merged_rows():
    emitted: list[dict] = []

    async def _emit(payload: dict) -> None:
        emitted.append(payload)

    coalescer = LogCoalescer(emit=_emit, idle_timeout_sec=10.0)
    await coalescer.add(
        {
            "level": "INFO",
            "message": "line-1",
            "raw_message": "line-1",
            "meta": {"source": "worker_stdio", "stream": "stdout", "group_id": "producer-g"},
        }
    )
    await coalescer.add(
        {
            "level": "INFO",
            "message": "line-2",
            "raw_message": "line-2",
            "meta": {"source": "worker_stdio", "stream": "stdout", "group_id": "producer-g"},
        }
    )
    await coalescer.flush()

    assert len(emitted) == 1
    assert emitted[0]["meta"]["group_id"] == "producer-g"
    assert emitted[0]["meta"]["line_count"] == 2


@pytest.mark.anyio
async def test_log_coalescer_should_carry_trailing_tabular_header_to_next_chunk():
    emitted: list[dict] = []

    async def _emit(payload: dict) -> None:
        emitted.append(payload)

    coalescer = LogCoalescer(emit=_emit, idle_timeout_sec=10.0)
    base_meta = {"source": "worker_stdio", "stream": "stdout"}

    await coalescer.add(
        {
            "level": "INFO",
            "message": "Class     Images  Instances      Box(P          R      mAP50  mAP50-95)",
            "raw_message": "Class     Images  Instances      Box(P          R      mAP50  mAP50-95)",
            "meta": dict(base_meta),
        }
    )
    await coalescer.add(
        {
            "level": "INFO",
            "message": "all         13         94          0          0          0          0",
            "raw_message": "all         13         94          0          0          0          0",
            "meta": dict(base_meta),
        }
    )
    await coalescer.add(
        {
            "level": "INFO",
            "message": "Epoch    GPU_mem   box_loss   cls_loss   dfl_loss  Instances       Size",
            "raw_message": "Epoch    GPU_mem   box_loss   cls_loss   dfl_loss  Instances       Size",
            "meta": dict(base_meta),
        }
    )
    await coalescer.flush()

    await coalescer.add(
        {
            "level": "INFO",
            "message": "4/30         0G      1.187       4.85        1.2         50        640",
            "raw_message": "4/30         0G      1.187       4.85        1.2         50        640",
            "meta": dict(base_meta),
        }
    )
    await coalescer.flush()

    assert len(emitted) == 2
    assert emitted[0]["message"].endswith("all         13         94          0          0          0          0")
    assert "Epoch    GPU_mem" not in emitted[0]["message"]
    assert emitted[1]["message"].startswith("Epoch    GPU_mem")
    assert "4/30" in emitted[1]["message"]


@pytest.mark.anyio
async def test_log_coalescer_should_not_drop_carried_header_without_following_rows():
    emitted: list[dict] = []

    async def _emit(payload: dict) -> None:
        emitted.append(payload)

    coalescer = LogCoalescer(emit=_emit, idle_timeout_sec=10.0)
    await coalescer.add(
        {
            "level": "INFO",
            "message": "Epoch    GPU_mem   box_loss   cls_loss   dfl_loss  Instances       Size",
            "raw_message": "Epoch    GPU_mem   box_loss   cls_loss   dfl_loss  Instances       Size",
            "meta": {"source": "worker_stdio", "stream": "stdout"},
        }
    )
    await coalescer.close()

    assert len(emitted) == 1
    assert emitted[0]["message"].startswith("Epoch    GPU_mem")
