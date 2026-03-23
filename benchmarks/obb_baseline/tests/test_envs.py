from pathlib import Path
import subprocess
import tomllib


ROOT = Path(__file__).resolve().parents[1]


def _load_pyproject(env_name: str) -> dict:
    pyproject_path = ROOT / "envs" / env_name / "pyproject.toml"
    with pyproject_path.open("rb") as f:
        return tomllib.load(f)


def _assert_dep_with_prefix(deps: list[str], prefix: str) -> None:
    assert any(dep.strip().startswith(prefix) for dep in deps), (
        f"missing dependency prefix: {prefix}, got: {deps}"
    )


def test_env_pyproject_constraints() -> None:
    mmrotate = _load_pyproject("mmrotate")
    yolo = _load_pyproject("yolo")

    assert mmrotate["project"]["name"] == "obb-benchmark-mmrotate-env"
    assert yolo["project"]["name"] == "obb-benchmark-yolo-env"
    assert mmrotate["project"]["version"] == "0.1.0"
    assert yolo["project"]["version"] == "0.1.0"
    assert mmrotate["project"]["requires-python"] == "==3.12.*"
    assert yolo["project"]["requires-python"] == "==3.12.*"

    mmrotate_deps = mmrotate["project"]["dependencies"]
    yolo_deps = yolo["project"]["dependencies"]

    _assert_dep_with_prefix(mmrotate_deps, "torch==2.9.1")
    _assert_dep_with_prefix(mmrotate_deps, "torchvision==0.24.1")
    _assert_dep_with_prefix(mmrotate_deps, "onedl-mmengine==0.10.9")
    _assert_dep_with_prefix(mmrotate_deps, "onedl-mmcv==2.3.2.post2")
    _assert_dep_with_prefix(mmrotate_deps, "onedl-mmdetection==3.4.5")
    _assert_dep_with_prefix(mmrotate_deps, "onedl-mmrotate==1.1.0.post1")
    _assert_dep_with_prefix(mmrotate_deps, "pyyaml>=6.0")

    _assert_dep_with_prefix(yolo_deps, "torch==2.10.0")
    _assert_dep_with_prefix(yolo_deps, "torchvision==0.25.0")
    _assert_dep_with_prefix(yolo_deps, "ultralytics==8.4.14")
    _assert_dep_with_prefix(yolo_deps, "pyyaml>=6.0")


def test_env_lock_files_exist() -> None:
    mmrotate_lock = ROOT / "envs" / "mmrotate" / "uv.lock"
    yolo_lock = ROOT / "envs" / "yolo" / "uv.lock"
    assert mmrotate_lock.exists()
    assert yolo_lock.exists()


def test_root_path_is_absolute() -> None:
    assert ROOT.is_absolute()


def test_lock_files_in_sync_with_pyproject() -> None:
    for env_name in ("mmrotate", "yolo"):
        env_dir = ROOT / "envs" / env_name
        result = subprocess.run(
            ["uv", "lock", "--check", "--project", str(env_dir)],
            cwd=ROOT.parent.parent,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, (
            f"{env_name} lock check failed:\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )
