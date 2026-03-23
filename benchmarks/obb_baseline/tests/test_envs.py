from pathlib import Path
import subprocess
import tomllib

import pytest


ROOT = Path(__file__).resolve().parents[1]
PYTORCH_CU118_INDEX = "https://download.pytorch.org/whl/cu118"
OPENMMLAB_MMCV_CU118_TORCH200_WHEEL = (
    "https://download.openmmlab.com/mmcv/dist/cu118/torch2.0.0/"
    "mmcv-2.0.1-cp310-cp310-manylinux1_x86_64.whl"
)


def _load_pyproject(env_name: str) -> dict:
    pyproject_path = ROOT / "envs" / env_name / "pyproject.toml"
    with pyproject_path.open("rb") as f:
        return tomllib.load(f)


def _load_lock(env_name: str) -> dict:
    lock_path = ROOT / "envs" / env_name / "uv.lock"
    with lock_path.open("rb") as f:
        return tomllib.load(f)


def _normalize_dep(dep: str) -> str:
    return "".join(dep.split())


def _assert_dep_exact(deps: list[str], expected: str) -> None:
    normalized_expected = _normalize_dep(expected)
    normalized_deps = {_normalize_dep(dep) for dep in deps}
    assert normalized_expected in normalized_deps, (
        f"missing dependency: {expected}, got: {deps}"
    )


def _find_packages(lock_data: dict, name: str) -> list[dict]:
    return [package for package in lock_data["package"] if package["name"] == name]


def _find_package(
    lock_data: dict,
    name: str,
    *,
    version: str | None = None,
) -> dict:
    packages = _find_packages(lock_data, name)
    if version is None:
        if len(packages) == 1:
            return packages[0]
        raise AssertionError(f"expected one package entry for {name}, got {packages}")

    matches = [package for package in packages if package["version"] == version]
    if len(matches) == 1:
        return matches[0]
    raise AssertionError(
        f"expected one package entry for {name}=={version}, got {matches or packages}"
    )


def _wheel_urls(lock_data: dict, name: str) -> list[str]:
    urls: list[str] = []
    for package in _find_packages(lock_data, name):
        for wheel in package.get("wheels", []):
            urls.append(wheel["url"].replace("%2B", "+"))
    return urls


def test_env_pyproject_constraints() -> None:
    mmrotate = _load_pyproject("mmrotate")
    yolo = _load_pyproject("yolo")

    assert mmrotate["project"]["name"] == "obb-benchmark-mmrotate-env"
    assert yolo["project"]["name"] == "obb-benchmark-yolo-env"
    assert mmrotate["project"]["version"] == "0.1.0"
    assert yolo["project"]["version"] == "0.1.0"
    assert mmrotate["project"]["requires-python"] == "==3.10.*"
    assert yolo["project"]["requires-python"] == "==3.12.*"

    mmrotate_deps = mmrotate["project"]["dependencies"]
    yolo_deps = yolo["project"]["dependencies"]

    _assert_dep_exact(mmrotate_deps, "torch==2.0.0")
    _assert_dep_exact(mmrotate_deps, "torchvision==0.15.1")
    _assert_dep_exact(mmrotate_deps, "mmengine==0.8.5")
    _assert_dep_exact(mmrotate_deps, "mmcv==2.0.1")
    _assert_dep_exact(mmrotate_deps, "mmdet==3.0.0")
    _assert_dep_exact(mmrotate_deps, "mmrotate==1.0.0rc1")
    _assert_dep_exact(mmrotate_deps, "pyyaml>=6.0")
    assert all("onedl-" not in dep for dep in mmrotate_deps), mmrotate_deps

    _assert_dep_exact(yolo_deps, "torch==2.10.0")
    _assert_dep_exact(yolo_deps, "torchvision==0.25.0")
    _assert_dep_exact(yolo_deps, "ultralytics==8.4.14")
    _assert_dep_exact(yolo_deps, "pyyaml>=6.0")


def test_mmrotate_uv_source_indexes() -> None:
    mmrotate = _load_pyproject("mmrotate")
    uv_config = mmrotate["tool"]["uv"]

    index_map = {entry["name"]: entry["url"] for entry in uv_config["index"]}
    assert set(index_map) == {"pytorch-cu118"}
    assert index_map["pytorch-cu118"] == PYTORCH_CU118_INDEX

    uv_sources = uv_config["sources"]
    assert uv_sources["torch"] == [{"index": "pytorch-cu118"}]
    assert uv_sources["torchvision"] == [{"index": "pytorch-cu118"}]
    assert uv_sources["mmcv"] == {"url": OPENMMLAB_MMCV_CU118_TORCH200_WHEEL}


def test_env_lock_files_exist() -> None:
    mmrotate_lock = ROOT / "envs" / "mmrotate" / "uv.lock"
    yolo_lock = ROOT / "envs" / "yolo" / "uv.lock"
    assert mmrotate_lock.exists()
    assert yolo_lock.exists()


def test_root_path_is_absolute() -> None:
    assert ROOT.is_absolute()


def test_mmrotate_lock_constraints() -> None:
    mmrotate_lock = _load_lock("mmrotate")
    assert mmrotate_lock["requires-python"] == "==3.10.*"

    torch_urls = _wheel_urls(mmrotate_lock, "torch")
    torchvision_urls = _wheel_urls(mmrotate_lock, "torchvision")
    assert any(
        url.startswith("https://download.pytorch.org/whl/cu118/torch-2.0.0+cu118")
        and url.endswith("linux_x86_64.whl")
        for url in torch_urls
    ), torch_urls
    assert any(
        url.startswith(
            "https://download-r2.pytorch.org/whl/cu118/torchvision-0.15.1+cu118"
        )
        and url.endswith("linux_x86_64.whl")
        for url in torchvision_urls
    ), torchvision_urls

    mmcv_package = _find_package(mmrotate_lock, "mmcv", version="2.0.1")
    assert "sdist" not in mmcv_package, mmcv_package
    assert any(
        wheel["url"] == OPENMMLAB_MMCV_CU118_TORCH200_WHEEL
        for wheel in mmcv_package["wheels"]
    ), mmcv_package["wheels"]
    assert mmcv_package["source"]["url"] == OPENMMLAB_MMCV_CU118_TORCH200_WHEEL

    mmdet_package = _find_package(mmrotate_lock, "mmdet", version="3.0.0")
    mmengine_package = _find_package(mmrotate_lock, "mmengine", version="0.8.5")
    mmrotate_package = _find_package(mmrotate_lock, "mmrotate", version="1.0.0rc1")
    assert mmdet_package["version"] == "3.0.0"
    assert mmengine_package["version"] == "0.8.5"
    assert mmrotate_package["version"] == "1.0.0rc1"

    assert all(
        not package["name"].startswith("onedl-")
        for package in mmrotate_lock["package"]
    ), "lock file still contains onedl packages"


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
