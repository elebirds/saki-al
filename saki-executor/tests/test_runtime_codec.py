from saki_executor.agent import codec
from saki_executor.grpc_gen import runtime_control_pb2 as pb


def test_build_ack_message():
    message = codec.build_ack_message(
        request_id="r1",
        ack_for="r0",
        ok=True,
        message="accepted",
    )
    assert message.WhichOneof("payload") == "ack"
    assert message.ack.request_id == "r1"
    assert message.ack.ack_for == "r0"
    assert message.ack.status == pb.OK


def test_parse_assign_job_payload():
    runtime_message = pb.RuntimeMessage(
        assign_job=pb.AssignJob(
            request_id="req1",
            job=pb.JobPayload(
                job_id="job1",
                project_id="project1",
                loop_id="loop1",
                source_commit_id="commit1",
                job_type=pb.TRAIN_DETECTION,
                plugin_id="demo_det_v1",
                mode=pb.ACTIVE_LEARNING,
                query_strategy="uncertainty_1_minus_max_conf",
                params=codec.dict_to_struct({"epochs": 5}),
                resources=pb.ResourceSummary(gpu_count=1, gpu_device_ids=[0], cpu_workers=4, memory_mb=0),
                iteration=3,
            ),
        )
    )
    payload = codec.parse_assign_job(runtime_message.assign_job)
    assert payload["job_id"] == "job1"
    assert payload["params"]["epochs"] == 5
    assert payload["job_type"] == "train_detection"
    assert payload["mode"] == "active_learning"
    assert payload["iteration"] == 3


def test_build_data_request_query_type_mapping():
    message = codec.build_data_request_message(
        request_id="r1",
        job_id="job1",
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
        details=codec.dict_to_struct({"reply_to": "req-1", "reason": "boom"}),
    )
    parsed = codec.parse_error(error_payload)
    assert parsed["reply_to"] == "req-1"
    assert parsed["error"] == "boom"


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
                "supported_job_types": ["train_detection"],
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
