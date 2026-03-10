from __future__ import annotations

import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from saki_plugin_yolo_det.prepare_pipeline import link_or_copy_file


def test_link_or_copy_file_prefers_hardlink(tmp_path: Path) -> None:
    src = tmp_path / "src.jpg"
    dst = tmp_path / "nested" / "dst.jpg"
    src.write_bytes(b"image-bytes")

    link_or_copy_file(src, dst)

    assert dst.read_bytes() == b"image-bytes"
    assert os.stat(src).st_ino == os.stat(dst).st_ino


def test_link_or_copy_file_falls_back_to_copy(monkeypatch, tmp_path: Path) -> None:
    src = tmp_path / "src.jpg"
    dst = tmp_path / "nested" / "dst.jpg"
    src.write_bytes(b"image-bytes")

    def _fail_link(source: Path, target: Path) -> None:
        del source, target
        raise OSError("cross-device link")

    monkeypatch.setattr("saki_plugin_yolo_det.prepare_pipeline.os.link", _fail_link)

    link_or_copy_file(src, dst)

    assert dst.read_bytes() == b"image-bytes"
    assert os.stat(src).st_ino != os.stat(dst).st_ino
