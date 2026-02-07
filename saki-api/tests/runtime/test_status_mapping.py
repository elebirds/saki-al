from saki_api.grpc.runtime_control import _map_status
from saki_api.grpc_gen import runtime_control_pb2 as pb
from saki_api.models.enums import TrainingJobStatus


def test_runtime_status_mapping():
    assert _map_status(pb.CREATED) == TrainingJobStatus.PENDING
    assert _map_status(pb.RUNNING) == TrainingJobStatus.RUNNING
    assert _map_status(pb.SUCCEEDED) == TrainingJobStatus.SUCCESS
    assert _map_status(pb.FAILED) == TrainingJobStatus.FAILED
    assert _map_status(pb.STOPPED) == TrainingJobStatus.CANCELLED
