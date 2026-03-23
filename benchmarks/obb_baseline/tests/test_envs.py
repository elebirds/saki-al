from pathlib import Path
import tomllib


ROOT = Path("benchmarks/obb_baseline")


def _load_pyproject(env_name: str) -> dict:
    pyproject_path = ROOT / "envs" / env_name / "pyproject.toml"
    with pyproject_path.open("rb") as f:
        return tomllib.load(f)


def test_env_pyproject_constraints() -> None:
    mmrotate = _load_pyproject("mmrotate")
    yolo = _load_pyproject("yolo")

    assert mmrotate["project"]["name"] == "obb-benchmark-mmrotate-env"
    assert yolo["project"]["name"] == "obb-benchmark-yolo-env"
    assert mmrotate["project"]["version"] == "0.1.0"
    assert yolo["project"]["version"] == "0.1.0"
    assert mmrotate["project"]["requires-python"] == "==3.12.*"
    assert yolo["project"]["requires-python"] == "==3.12.*"

    mmrotate_deps = set(mmrotate["project"]["dependencies"])
    yolo_deps = set(yolo["project"]["dependencies"])

    assert "torch==2.9.1" in mmrotate_deps
    assert "torchvision==0.24.1" in mmrotate_deps
    assert "onedl-mmengine==0.10.9" in mmrotate_deps
    assert "onedl-mmcv==2.3.2.post2" in mmrotate_deps
    assert "onedl-mmdetection==3.4.5" in mmrotate_deps
    assert "onedl-mmrotate==1.1.0.post1" in mmrotate_deps
    assert "pyyaml>=6.0" in mmrotate_deps

    assert "torch==2.10.0" in yolo_deps
    assert "torchvision==0.25.0" in yolo_deps
    assert "ultralytics==8.4.14" in yolo_deps
    assert "pyyaml>=6.0" in yolo_deps


def test_env_lock_files_exist() -> None:
    mmrotate_lock = ROOT / "envs" / "mmrotate" / "uv.lock"
    yolo_lock = ROOT / "envs" / "yolo" / "uv.lock"
    assert mmrotate_lock.exists()
    assert yolo_lock.exists()
