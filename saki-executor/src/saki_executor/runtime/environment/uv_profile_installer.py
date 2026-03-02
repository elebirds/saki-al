from __future__ import annotations

import os
import subprocess
from pathlib import Path


def sync_profile_env(
    *,
    plugin_dir: Path,
    venv_dir: Path,
    dependency_groups: list[str],
    timeout_sec: int = 900,
) -> None:
    command = ["uv", "sync"]
    for group in dependency_groups:
        value = str(group or "").strip()
        if not value:
            continue
        command.extend(["--extra", value])

    env = dict(os.environ)
    env["UV_PROJECT_ENVIRONMENT"] = str(venv_dir)
    result = subprocess.run(
        command,
        cwd=str(plugin_dir),
        capture_output=True,
        text=True,
        timeout=timeout_sec,
        env=env,
        check=False,
    )
    if int(result.returncode or 0) != 0:
        raise RuntimeError(
            f"PROFILE_UNSATISFIED: uv sync failed for profile env plugin_dir={plugin_dir} "
            f"venv={venv_dir} exit_code={result.returncode} stderr={(result.stderr or '').strip()[:500]}"
        )
