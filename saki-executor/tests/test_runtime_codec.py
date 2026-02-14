from saki_executor.agent import codec
from saki_executor.grpc_gen import runtime_control_pb2 as pb


def test_build_ack_message():
    message = codec.build_ack_message(
        request_id="r1",
        ack_for="r0",
        ok=True,
        ack_type="assign_task",
        ack_reason="accepted",
        detail="accepted",
    )
    assert message.WhichOneof("payload") == "ack"
    assert message.ack.request_id == "r1"
    assert message.ack.ack_for == "r0"
    assert message.ack.status == pb.OK
    assert message.ack.type == pb.ACK_TYPE_ASSIGN_TASK
    assert message.ack.reason == pb.ACK_REASON_ACCEPTED
    assert message.ack.detail == "accepted"


def test_parse_assign_task_payload():
    runtime_message = pb.RuntimeMessage(
        assign_task=pb.AssignTask(
            request_id="req1",
            step=pb.TaskPayload(
                step_id="task1",
                round_id="job1",
                project_id="project1",
                loop_id="loop1",
                input_commit_id="commit1",
                step_type=pb.TRAIN,
                plugin_id="demo_det_v1",
                mode=pb.ACTIVE_LEARNING,
                query_strategy="uncertainty_1_minus_max_conf",
                resolved_params=codec.dict_to_struct({"epochs": 5}),
                resources=pb.ResourceSummary(gpu_count=1, gpu_device_ids=[0], cpu_workers=4, memory_mb=0),
                round_index=3,
            ),
        )
    )
    payload = codec.parse_assign_task(runtime_message.assign_task)
    assert payload["step_id"] == "task1"
    assert payload["round_id"] == "job1"
    assert payload["params"]["epochs"] == 5
    assert payload["task_type"] == "train"
    assert payload["mode"] == "active_learning"
    assert payload["round_index"] == 3


def test_build_data_request_query_type_mapping():
    message = codec.build_data_request_message(
        request_id="r1",
        task_id="task1",
        query_type="annotations",
        project_id="project1",
        commit_id="commit1",
        cursor="",
        limit=100,
    )
    assert message.WhichOneof("payload") == "data_request"
    assert message.data_request.query_type == pb.ANNOTATIONS


def test_parse_error_message_includes_reply_to_and_error():
    error_payload = pb.Error(
        request_id="err-1",
        code="INTERNAL",
        message="boom",
        reply_to="req-1",
        reason="boom",
        step_id="task-1",
        query_type=pb.LABELS,
    )
    parsed = codec.parse_error(error_payload)
    assert parsed["reply_to"] == "req-1"
    assert parsed["step_id"] == "task-1"
    assert parsed["error"] == "boom"
    assert parsed["query_type"] == "labels"


def test_build_register_message_with_accelerators():
    message = codec.build_register_message(
        request_id="reg-1",
        executor_id="executor-1",
        version="0.1.0",
        plugins=[
            {
                "plugin_id": "demo_det_v1",
                "version": "0.1.0",
                "display_name": "Demo",
                "supported_task_types": ["train"],
                "supported_strategies": ["random_baseline"],
                "supported_accelerators": ["cpu", "cuda"],
                "supports_auto_fallback": True,
            }
        ],
        resources={
            "gpu_count": 1,
            "gpu_device_ids": [0],
            "cpu_workers": 4,
            "memory_mb": 1024,
            "accelerators": [
                {"type": "cuda", "available": True, "device_count": 1, "device_ids": ["0"]},
                {"type": "cpu", "available": True, "device_count": 1, "device_ids": ["cpu"]},
            ],
        },
    )
    assert message.WhichOneof("payload") == "register"
    assert list(message.register.plugins[0].supported_accelerators) == [pb.CPU, pb.CUDA]
    assert message.register.plugins[0].supports_auto_fallback is True
    assert len(message.register.resources.accelerators) >= 2


def test_task_status_codec_mapping():
    message = codec.build_task_result_message(
        request_id="result-1",
        task_id="task-1",
        status="failed",
        metrics={},
        artifacts={},
        candidates=[],
        error_message="task failed",
    )
    assert message.task_result.status == pb.FAILED
    assert codec.status_enum_to_text(pb.FAILED) == "failed"
