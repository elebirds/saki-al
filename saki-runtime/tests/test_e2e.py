import asyncio
import json
import os
import shutil
import time
from pathlib import Path
from typing import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from saki_runtime.core.config import settings
from saki_runtime.main import app
from saki_runtime.schemas.enums import JobStatus
from saki_runtime.schemas.ir import DetAnnotationIR, LabelIR, SampleIR

# Mock SakiClient
@pytest.fixture
def mock_saki_client():
    with patch("saki_runtime.plugins.builtin.yolo_det_v1.plugin.saki_client") as mock:
        # Mock get_labels
        mock.get_labels = AsyncMock(return_value=[
            LabelIR(id=1, name="person", color="#ff0000"),
            LabelIR(id=2, name="car", color="#00ff00")
        ])

        # Mock iter_samples
        async def mock_iter_samples(dataset_version_id):
            yield SampleIR(id="s1", uri="file:///tmp/s1.jpg", width=100, height=100)
            yield SampleIR(id="s2", uri="file:///tmp/s2.jpg", width=100, height=100)
        mock.iter_samples = mock_iter_samples

        # Mock iter_annotations
        async def mock_iter_annotations(label_version_id):
            yield DetAnnotationIR(
                id="a1", sample_id="s1", category_id=1, bbox_xywh=[10, 10, 50, 50], source="manual"
            )
        mock.iter_annotations = mock_iter_annotations
        
        yield mock

@pytest.fixture
def client():
    return TestClient(app)

@pytest.fixture
def auth_headers():
    return {"X-Internal-Token": settings.INTERNAL_TOKEN}

@pytest.fixture(autouse=True)
def clean_runs():
    # Clean up runs directory before and after tests
    runs_dir = Path(settings.RUNS_DIR)
    
    # Ensure locks are released before cleanup
    from saki_runtime.api.v1.deps import job_manager
    job_manager.gpu_locks.release_all()
    
    if runs_dir.exists():
        try:
            shutil.rmtree(runs_dir)
        except PermissionError:
            # Retry once after short sleep if windows lock lingers
            time.sleep(0.5)
            shutil.rmtree(runs_dir, ignore_errors=True)
            
    yield
    
    job_manager.gpu_locks.release_all()
    if runs_dir.exists():
        try:
            shutil.rmtree(runs_dir)
        except PermissionError:
            time.sleep(0.5)
            shutil.rmtree(runs_dir, ignore_errors=True)

def test_e2e_job_lifecycle(client, auth_headers, mock_saki_client):
    # 1. List Plugins
    response = client.get("/api/v1/plugins", headers=auth_headers)
    assert response.status_code == 200
    plugins = response.json()["plugins"]
    assert any(p["id"] == "yolo_det_v1" for p in plugins)

    # 2. Create Job
    job_payload = {
        "job_type": "train_detection",
        "project_id": "p1",
        "plugin_id": "yolo_det_v1",
        "data_ref": {
            "dataset_version_id": "dv1",
            "label_version_id": "lv1"
        },
        "params": {
            "epochs": 2, # Short run
            "batch_size": 4
        },
        "resources": {
            "gpu": {"count": 1, "device_ids": [0]},
            "cpu": {"workers": 2},
            "memory_mb": 1024
        }
    }
    response = client.post("/api/v1/jobs", json=job_payload, headers=auth_headers)
    assert response.status_code == 200
    job_data = response.json()
    job_id = job_data["job_id"]
    assert job_data["status"] == "created"

    # 3. Start Job
    response = client.post(f"/api/v1/jobs/{job_id}:start", headers=auth_headers)
    assert response.status_code == 200

    # 4. Poll Job Status
    max_retries = 30
    succeeded = False
    
    for _ in range(max_retries):
        time.sleep(1)
        response = client.get(f"/api/v1/jobs/{job_id}", headers=auth_headers)
        assert response.status_code == 200
        status = response.json()["job"]["status"]
        
        if status == JobStatus.SUCCEEDED:
            succeeded = True
            break
        elif status == JobStatus.FAILED:
            # Try to read stderr
            runs_dir = Path(settings.RUNS_DIR)
            stderr_path = runs_dir / job_id / "artifacts" / "stderr.log"
            if stderr_path.exists():
                print(f"Job stderr: {stderr_path.read_text()}")
            pytest.fail("Job failed")
            
    if not succeeded:
        # Debug info
        runs_dir = Path(settings.RUNS_DIR)
        stderr_path = runs_dir / job_id / "artifacts" / "stderr.log"
        stdout_path = runs_dir / job_id / "artifacts" / "stdout.log"
        if stderr_path.exists():
            print(f"Job stderr: {stderr_path.read_text()}")
        if stdout_path.exists():
            print(f"Job stdout: {stdout_path.read_text()}")
            
    assert succeeded, "Job did not succeed in time"

    # 5. Check Artifacts
    response = client.get(f"/api/v1/jobs/{job_id}/artifacts", headers=auth_headers)
    assert response.status_code == 200
    artifacts = response.json()["artifacts"]
    
    # Check for best.pt
    best_pt = next((a for a in artifacts if a["name"] == "best.pt"), None)
    assert best_pt is not None
    assert best_pt["path"].startswith("file://")
    
    # Check for config.json and events.jsonl
    assert any(a["name"] == "config.json" for a in artifacts)
    assert any(a["name"] == "events.jsonl" for a in artifacts)

    # 6. Check Metrics
    response = client.get(f"/api/v1/jobs/{job_id}/metrics", headers=auth_headers)
    assert response.status_code == 200
    metrics = response.json()["metrics"]
    assert len(metrics) > 0
    assert "loss" in metrics[0]["metrics"]

def test_query_mock(client, auth_headers):
    # Mock SakiClient for query is needed if we want to test service logic
    # But here we can just test the endpoint with mocked service or just rely on the service using the mocked client
    # Since we patched saki_client globally in the module or via fixture, we need to apply it here too.
    
    with patch("saki_runtime.services.query.saki_client") as mock:
        async def mock_iter_unlabeled(dv, lv):
            for i in range(5):
                yield SampleIR(id=f"u{i}", uri=f"file:///tmp/u{i}.jpg", width=100, height=100)
        mock.iter_unlabeled_samples = mock_iter_unlabeled

        query_payload = {
            "project_id": "p1",
            "plugin_id": "yolo_det_v1",
            "model_ref": {"job_id": "j1", "artifact_name": "best.pt"},
            "unlabeled_ref": {"dataset_version_id": "dv1", "label_version_id": "lv1"},
            "unit": "image",
            "strategy": "uncertainty",
            "topk": 3,
            "params": {}
        }
        
        response = client.post("/api/v1/query", json=query_payload, headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert len(data["candidates"]) == 3
        # Check sorting
        scores = [c["score"] for c in data["candidates"]]
        assert scores == sorted(scores, reverse=True)
