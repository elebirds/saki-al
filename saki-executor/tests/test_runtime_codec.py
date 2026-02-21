from saki_executor.agent import codec
from saki_executor.grpc_gen import runtime_control_pb2 as pb


def test_build_ack_message():
    message = codec.build_ack_message(
        request_id="r1",
        ack_for="r0",
        ok=True,
        ack_type="assign_step",
        ack_reason="accepted",
        detail="accepted",
    )
    assert message.WhichOneof("payload") == "ack"
    assert message.ack.request_id == "r1"
    assert message.ack.ack_for == "r0"
    assert message.ack.status == pb.OK
    assert message.ack.type == pb.ACK_TYPE_ASSIGN_STEP
    assert message.ack.reason == pb.ACK_REASON_ACCEPTED
    assert message.ack.detail == "accepted"


def test_parse_assign_step_payload():
    runtime_message = pb.RuntimeMessage(
        assign_step=pb.AssignStep(
            request_id="req1",
            step=pb.StepPayload(
                step_id="task1",
                round_id="job1",
                project_id="project1",
                loop_id="loop1",
                input_commit_id="commit1",
                step_type=pb.TRAIN,
                dispatch_kind=pb.ORCHESTRATOR,
                plugin_id="demo_det_v1",
                mode=pb.ACTIVE_LEARNING,
                query_strategy="uncertainty_1_minus_max_conf",
                resolved_params=codec.dict_to_struct({"epochs": 5}),
                resources=pb.ResourceSummary(gpu_count=1, gpu_device_ids=[0], cpu_workers=4, memory_mb=0),
                round_index=3,
            ),
        )
    )
    payload = codec.parse_assign_step(runtime_message.assign_step)
    assert payload["step_id"] == "task1"
    assert payload["round_id"] == "job1"
    assert payload["resolved_params"]["epochs"] == 5
    assert payload["step_type"] == "train"
    assert payload["dispatch_kind"] == "orchestrator"
    assert payload["mode"] == "active_learning"
    assert payload["round_index"] == 3


def test_parse_assign_step_unknown_runtime_enums_keep_empty_fields():
    runtime_message = pb.RuntimeMessage(
        assign_step=pb.AssignStep(
            request_id="req1",
            step=pb.StepPayload(
                step_id="task1",
                round_id="job1",
                project_id="project1",
                loop_id="loop1",
                input_commit_id="commit1",
                step_type=pb.RUNTIME_STEP_TYPE_UNSPECIFIED,
                dispatch_kind=pb.RUNTIME_STEP_DISPATCH_KIND_UNSPECIFIED,
                plugin_id="demo_det_v1",
                mode=pb.RUNTIME_LOOP_MODE_UNSPECIFIED,
                query_strategy="uncertainty_1_minus_max_conf",
                resolved_params=codec.dict_to_struct({"epochs": 5}),
                round_index=3,
            ),
        )
    )
    payload = codec.parse_assign_step(runtime_message.assign_step)
    assert payload["step_type"] == ""
    assert payload["dispatch_kind"] == ""
    assert payload["mode"] == ""


def test_parse_assign_step_unsupported_step_type_is_not_mapped():
    runtime_message = pb.RuntimeMessage(
        assign_step=pb.AssignStep(
            request_id="req-unsupported-step",
            step=pb.StepPayload(
                step_id="task-unsupported-step",
                round_id="job-unsupported-step",
                project_id="project1",
                loop_id="loop1",
                input_commit_id="commit1",
                step_type=pb.RUNTIME_STEP_TYPE_UNSPECIFIED,
                dispatch_kind=pb.ORCHESTRATOR,
                plugin_id="demo_det_v1",
                mode=pb.MANUAL,
                query_strategy="uncertainty_1_minus_max_conf",
                resolved_params=codec.dict_to_struct({}),
                round_index=1,
            ),
        )
    )
    payload = codec.parse_assign_step(runtime_message.assign_step)
    assert payload["step_type"] == ""
    assert payload["dispatch_kind"] == "orchestrator"
    assert payload["mode"] == "manual"


def test_build_data_request_query_type_mapping():
    message = codec.build_data_request_message(
        request_id="r1",
        step_id="task1",
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
                "supported_step_types": ["train"],
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
    message = codec.build_step_result_message(
        request_id="result-1",
        step_id="task-1",
        status="failed",
        metrics={},
        artifacts={},
        candidates=[],
        error_message="task failed",
    )
    assert message.step_result.status == pb.FAILED
    assert codec.status_enum_to_text(pb.FAILED) == "failed"
