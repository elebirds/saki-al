from pathlib import Path
import subprocess
import tomllib

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _load_pyproject(env_name: str) -> dict:
    pyproject_path = ROOT / "envs" / env_name / "pyproject.toml"
    with pyproject_path.open("rb") as f:
        return tomllib.load(f)


def _normalize_dep(dep: str) -> str:
    return "".join(dep.split())


def _assert_dep_exact(deps: list[str], expected: str) -> None:
    normalized_expected = _normalize_dep(expected)
    normalized_deps = {_normalize_dep(dep) for dep in deps}
    assert normalized_expected in normalized_deps, (
        f"missing dependency: {expected}, got: {deps}"
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

    _assert_dep_exact(mmrotate_deps, "torch==2.9.1")
    _assert_dep_exact(mmrotate_deps, "torchvision==0.24.1")
    _assert_dep_exact(mmrotate_deps, "onedl-mmengine==0.10.9")
    _assert_dep_exact(mmrotate_deps, "onedl-mmcv==2.3.2.post2")
    _assert_dep_exact(mmrotate_deps, "onedl-mmdetection==3.4.5")
    _assert_dep_exact(mmrotate_deps, "onedl-mmrotate==1.1.0.post1")
    _assert_dep_exact(mmrotate_deps, "pyyaml>=6.0")

    _assert_dep_exact(yolo_deps, "torch==2.10.0")
    _assert_dep_exact(yolo_deps, "torchvision==0.25.0")
    _assert_dep_exact(yolo_deps, "ultralytics==8.4.14")
    _assert_dep_exact(yolo_deps, "pyyaml>=6.0")


def test_env_lock_files_exist() -> None:
    mmrotate_lock = ROOT / "envs" / "mmrotate" / "uv.lock"
    yolo_lock = ROOT / "envs" / "yolo" / "uv.lock"
    assert mmrotate_lock.exists()
    assert yolo_lock.exists()


def test_root_path_is_absolute() -> None:
    assert ROOT.is_absolute()


def _run_uv_lock_check(env_name: str) -> None:
    env_dir = ROOT / "envs" / env_name
    cmd = ["uv", "lock", "--check", "--project", str(env_dir)]
    try:
        result = subprocess.run(
            cmd,
            cwd=ROOT.parent.parent,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        pytest.fail(
            f"uv command not found while checking {env_name} lock sync. "
            f"command={cmd}, cwd={ROOT.parent.parent}, error={exc}"
        )

    assert result.returncode == 0, (
        f"{env_name} lock check failed:\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )


def test_lock_files_in_sync_with_pyproject() -> None:
    for env_name in ("mmrotate", "yolo"):
        _run_uv_lock_check(env_name)


def test_dep_match_rejects_prefix_collision() -> None:
    with pytest.raises(AssertionError):
        _assert_dep_exact([" torch==2.9.10 "], "torch==2.9.1")


def test_lock_check_reports_missing_uv(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise_missing_uv(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError("uv")

    monkeypatch.setattr(subprocess, "run", _raise_missing_uv)

    with pytest.raises(pytest.fail.Exception, match="uv"):
        test_lock_files_in_sync_with_pyproject()
