from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(slots=True)
class ManifestLinkItem:
    source_path: str
    relative_target: str


def materialize_manifest_symlinks(
    *,
    workspace_root: str,
    links: Iterable[ManifestLinkItem],
) -> list[str]:
    """按 manifest 在工作区构建软链接，不移动源文件。"""

    root = Path(workspace_root).resolve()
    created: list[str] = []
    for item in links:
        source = Path(item.source_path).resolve()
        target = (root / item.relative_target).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() or target.is_symlink():
            target.unlink()
        os.symlink(source, target)
        created.append(str(target))
    return created
