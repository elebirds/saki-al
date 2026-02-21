"""Plugin virtual environment manager.

Ensures each external plugin directory has a synced venv via ``uv sync``,
and exposes the path to the plugin's Python interpreter.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from loguru import logger


def ensure_plugin_venv(plugin_dir: Path, *, auto_sync: bool = True) -> Path:
    """Return the Python interpreter path inside the plugin's venv.

    If ``auto_sync`` is True and the venv does not exist (or a
    ``pyproject.toml`` is present), ``uv sync`` will be executed to
    create / update the environment.

    Returns the absolute path to ``.venv/bin/python`` inside
    *plugin_dir*.  The symlink is intentionally **not** resolved so
    that Python keeps the venv context (pyvenv.cfg / site-packages).
    """
    # Make plugin_dir absolute (resolve parent dirs, but keep python
    # symlink intact later).
    plugin_dir = Path(os.path.abspath(plugin_dir))

    venv_dir = plugin_dir / ".venv"
    python_path = venv_dir / "bin" / "python"

    pyproject = plugin_dir / "pyproject.toml"
    needs_sync = auto_sync and (not python_path.exists() or not venv_dir.exists())

    if needs_sync and pyproject.exists():
        logger.info("syncing plugin venv dir={}", plugin_dir)
        result = subprocess.run(
            ["uv", "sync"],
            cwd=str(plugin_dir),
            capture_output=True,
            text=True,
            timeout=600,
        )
        if result.returncode != 0:
            stderr = (result.stderr or "").strip()
            raise RuntimeError(
                f"uv sync failed for plugin at {plugin_dir}: "
                f"exit_code={result.returncode} stderr={stderr[:500]}"
            )
        logger.info("plugin venv synced dir={}", plugin_dir)

    if not python_path.exists():
        raise RuntimeError(
            f"plugin Python interpreter not found at {python_path}. "
            f"Run 'uv sync' in {plugin_dir} first."
        )

    # Do NOT call .resolve() — it follows the symlink and
    # the resulting system-python path loses venv site-packages.
    return python_path
