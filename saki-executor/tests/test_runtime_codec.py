from saki_executor.agent import codec
from saki_executor.grpc_gen import runtime_control_pb2 as pb


def test_runtime_message_roundtrip_for_ack():
    message = {
        "type": "ack",
        "request_id": "r1",
        "ack_for": "r0",
        "status": "ok",
        "message": "accepted",
    }
    pb_message = codec.dict_to_runtime_message(message)
    decoded = codec.runtime_message_to_dict(pb_message)
    assert decoded["type"] == "ack"
    assert decoded["ack_for"] == "r0"
    assert decoded["status"] == "ok"


def test_decode_assign_job_payload():
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
            ),
        )
    )
    decoded = codec.runtime_message_to_dict(runtime_message)
    assert decoded["type"] == "assign_job"
    assert decoded["job"]["job_id"] == "job1"
    assert decoded["job"]["params"]["epochs"] == 5
    assert decoded["job"]["job_type"] == "train_detection"
    assert decoded["job"]["mode"] == "active_learning"


def test_data_request_query_type_mapping():
    message = {
        "type": "data_request",
        "request_id": "r1",
        "job_id": "job1",
        "query_type": "annotations",
        "project_id": "project1",
        "commit_id": "commit1",
        "cursor": "",
        "limit": 100,
    }
    pb_message = codec.dict_to_runtime_message(message)
    assert pb_message.data_request.query_type == pb.ANNOTATIONS


def test_error_message_decoding_includes_reply_to_and_error():
    runtime_message = pb.RuntimeMessage(
        error=pb.Error(
            request_id="err-1",
            code="INTERNAL",
            message="boom",
            details=codec.dict_to_struct({"reply_to": "req-1", "reason": "boom"}),
        )
    )
    decoded = codec.runtime_message_to_dict(runtime_message)
    assert decoded["type"] == "error"
    assert decoded["reply_to"] == "req-1"
    assert decoded["error"] == "boom"
