from saki_api.grpc.runtime_control import _map_status
from saki_api.models.enums import TrainingJobStatus


def test_runtime_status_mapping():
    assert _map_status("created") == TrainingJobStatus.PENDING
    assert _map_status("running") == TrainingJobStatus.RUNNING
    assert _map_status("succeeded") == TrainingJobStatus.SUCCESS
    assert _map_status("failed") == TrainingJobStatus.FAILED
    assert _map_status("stopped") == TrainingJobStatus.CANCELLED
