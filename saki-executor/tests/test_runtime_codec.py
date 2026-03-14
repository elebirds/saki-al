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
            task=pb.TaskPayload(
                task_id="task1",
                round_id="job1",
                project_id="project1",
                loop_id="loop1",
                input_commit_id="commit1",
                task_type=pb.TRAIN,
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
    payload = codec.parse_assign_task(runtime_message.assign_task)
    assert payload["task_id"] == "task1"
    assert payload["task_id"] == "task1"
    assert payload["round_id"] == "job1"
    assert payload["resolved_params"]["epochs"] == 5
    assert payload["task_type"] == "train"
    assert payload["dispatch_kind"] == "orchestrator"
    assert payload["mode"] == "active_learning"
    assert payload["round_index"] == 3


def test_parse_assign_task_unknown_runtime_enums_keep_empty_fields():
    runtime_message = pb.RuntimeMessage(
        assign_task=pb.AssignTask(
            request_id="req1",
            task=pb.TaskPayload(
                task_id="task1",
                round_id="job1",
                project_id="project1",
                loop_id="loop1",
                input_commit_id="commit1",
                task_type=pb.RUNTIME_TASK_TYPE_UNSPECIFIED,
                dispatch_kind=pb.RUNTIME_TASK_DISPATCH_KIND_UNSPECIFIED,
                plugin_id="demo_det_v1",
                mode=pb.RUNTIME_LOOP_MODE_UNSPECIFIED,
                query_strategy="uncertainty_1_minus_max_conf",
                resolved_params=codec.dict_to_struct({"epochs": 5}),
                round_index=3,
            ),
        )
    )
    payload = codec.parse_assign_task(runtime_message.assign_task)
    assert payload["task_type"] == ""
    assert payload["dispatch_kind"] == ""
    assert payload["mode"] == ""


def test_parse_assign_task_unsupported_task_type_is_not_mapped():
    runtime_message = pb.RuntimeMessage(
        assign_task=pb.AssignTask(
            request_id="req-unsupported-step",
            task=pb.TaskPayload(
                task_id="task-unsupported-step",
                round_id="job-unsupported-step",
                project_id="project1",
                loop_id="loop1",
                input_commit_id="commit1",
                task_type=pb.RUNTIME_TASK_TYPE_UNSPECIFIED,
                dispatch_kind=pb.ORCHESTRATOR,
                plugin_id="demo_det_v1",
                mode=pb.MANUAL,
                query_strategy="uncertainty_1_minus_max_conf",
                resolved_params=codec.dict_to_struct({}),
                round_index=1,
            ),
        )
    )
    payload = codec.parse_assign_task(runtime_message.assign_task)
    assert payload["task_type"] == ""
    assert payload["dispatch_kind"] == "orchestrator"
    assert payload["mode"] == "manual"


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
        task_id="task-1",
        query_type=pb.LABELS,
    )
    parsed = codec.parse_error(error_payload)
    assert parsed["reply_to"] == "req-1"
    assert parsed["task_id"] == "task-1"
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
            "host_capability": {
                "platform": "linux",
                "arch": "x86_64",
                "cpu_workers": 4,
                "memory_mb": 1024,
                "gpus": [
                    {
                        "id": "0",
                        "name": "RTX 4090",
                        "memory_mb": 24564,
                        "compute_capability": "8.9",
                        "fp32_tflops": 82.6,
                    }
                ],
                "driver_info": {
                    "driver_version": "550.54.15",
                    "cuda_version": "12.4",
                },
            },
        },
    )
    assert message.WhichOneof("payload") == "register"
    assert list(message.register.plugins[0].supported_accelerators) == [pb.CPU, pb.CUDA]
    assert message.register.plugins[0].supports_auto_fallback is True
    assert len(message.register.resources.accelerators) >= 2
    assert message.register.resources.host_capability.fields["platform"].string_value == "linux"
    assert message.register.resources.host_capability.fields["gpus"].list_value.values[0].struct_value.fields["compute_capability"].string_value == "8.9"


def test_parse_assign_task_resource_summary_keeps_host_capability():
    runtime_message = pb.RuntimeMessage(
        assign_task=pb.AssignTask(
            request_id="req-with-host",
            task=pb.TaskPayload(
                task_id="task-with-host",
                round_id="round-1",
                project_id="project-1",
                loop_id="loop-1",
                task_type=pb.TRAIN,
                plugin_id="demo_det_v1",
                mode=pb.ACTIVE_LEARNING,
                resources=pb.ResourceSummary(
                    gpu_count=1,
                    gpu_device_ids=[0],
                    cpu_workers=16,
                    memory_mb=64000,
                    host_capability=codec.dict_to_struct(
                        {
                            "platform": "linux",
                            "arch": "x86_64",
                            "gpus": [{"id": "0", "name": "RTX 4090"}],
                            "driver_info": {"cuda_version": "12.4"},
                        }
                    ),
                ),
            ),
        )
    )

    payload = codec.parse_assign_task(runtime_message.assign_task)
    assert payload["resources"]["host_capability"]["platform"] == "linux"
    assert payload["resources"]["host_capability"]["driver_info"]["cuda_version"] == "12.4"


def test_task_status_codec_mapping():
    messages = codec.build_task_result_message(
        request_id="result-1",
        task_id="task-1",
        status="failed",
        metrics={},
        artifacts={},
        candidates=[],
        error_message="task failed",
    )
    assert len(messages) == 1
    assert messages[0].task_result.status == pb.FAILED
    assert codec.status_enum_to_text(pb.FAILED) == "failed"
    assert codec.task_status_to_enum("syncing_env") == pb.SYNCING_ENV
    assert codec.task_status_to_enum("probing_runtime") == pb.PROBING_RUNTIME
    assert codec.task_status_to_enum("binding_device") == pb.BINDING_DEVICE
    assert codec.status_enum_to_text(pb.SYNCING_ENV) == "syncing_env"
    assert codec.status_enum_to_text(pb.PROBING_RUNTIME) == "probing_runtime"
    assert codec.status_enum_to_text(pb.BINDING_DEVICE) == "binding_device"


def test_build_task_result_message_keeps_small_payload_inline():
    messages = codec.build_task_result_message(
        request_id="result-inline-1",
        task_id="task-inline-1",
        execution_id="execution-inline-1",
        status="succeeded",
        metrics={"map50": 0.5},
        artifacts={"report.json": {"kind": "report", "uri": "s3://bucket/report.json"}},
        candidates=[
            {
                "sample_id": "sample-1",
                "score": 0.9,
                "reason": {"prediction_snapshot": {"base_predictions": [{"confidence": 0.9}]}},
            }
        ],
    )

    assert len(messages) == 1
    assert messages[0].WhichOneof("payload") == "task_result"
    assert messages[0].task_result.task_id == "task-inline-1"
    assert len(messages[0].task_result.candidates) == 1


def test_build_task_result_message_splits_large_payload_into_chunks():
    large_suffix = "x" * 768
    candidates = []
    for index in range(6000):
        candidates.append(
            {
                "sample_id": f"sample-{index}-{large_suffix}",
                "score": 0.8,
                "reason": {
                    "prediction_snapshot": {
                        "base_predictions": [
                            {
                                "class_index": 0,
                                "class_name": "target",
                                "confidence": 0.8,
                                "geometry": {
                                    "obb": {
                                        "cx": 0.5,
                                        "cy": 0.5,
                                        "w": 0.2,
                                        "h": 0.1,
                                        "angle": 15.0,
                                    }
                                },
                                "qbox": [0.1, 0.1, 0.2, 0.1, 0.2, 0.2, 0.1, 0.2],
                            }
                        ]
                    }
                },
            }
        )

    messages = codec.build_task_result_message(
        request_id="result-chunked-1",
        task_id="task-chunked-1",
        execution_id="execution-chunked-1",
        status="succeeded",
        metrics={},
        artifacts={},
        candidates=candidates,
    )

    assert len(messages) > 1
    assert all(message.WhichOneof("payload") == "task_result_chunk" for message in messages)
    first = messages[0].task_result_chunk
    last = messages[-1].task_result_chunk
    assert first.task_id == "task-chunked-1"
    assert first.execution_id == "execution-chunked-1"
    assert first.chunk_count == len(messages)
    assert first.chunk_index == 0
    assert last.is_last_chunk is True
    assert last.chunk_index == len(messages) - 1


def test_build_task_event_message_log_supports_structured_fields():
    message = codec.build_task_event_message(
        request_id="req-log-1",
        task_id="step-log-1",
        seq=10,
        ts=123456,
        event_type="log",
        payload={
            "level": "DEBUG",
            "message": "display text",
            "raw_message": "raw text",
            "message_key": "runtime.status.running",
            "message_args": {"step": 3},
            "meta": {"source": "worker_stdio", "stream": "stderr", "line_count": 2},
        },
    )
    assert message.WhichOneof("payload") == "task_event"
    log_event = message.task_event.log_event
    assert log_event.level == "DEBUG"
    assert log_event.message == "display text"
    assert log_event.raw_message == "raw text"
    assert log_event.message_key == "runtime.status.running"
    assert log_event.message_args.fields["step"].number_value == 3
    assert log_event.meta.fields["source"].string_value == "worker_stdio"
    assert log_event.meta.fields["line_count"].number_value == 2
