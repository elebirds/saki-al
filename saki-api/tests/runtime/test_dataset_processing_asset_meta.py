from __future__ import annotations

import io
import uuid
from types import SimpleNamespace

import pytest
from fastapi import UploadFile
from PIL import Image

from saki_api.core.config import settings
from saki_api.modules.annotation.extensions.data_formats.fedo.processor import FedoData
from saki_api.modules.annotation.extensions.dataset_processing.base import UploadContext
from saki_api.modules.annotation.extensions.dataset_processing.processors.classic import ClassicProcessor
from saki_api.modules.annotation.extensions.dataset_processing.processors.fedo import FedoDatasetProcessor


class _FakeAssetService:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def upload_file(self, file: UploadFile, storage_type=None, meta_info=None):
        normalized_meta = dict(meta_info or {})
        self.calls.append(
            {
                "filename": file.filename,
                "meta_info": normalized_meta,
            }
        )
        return SimpleNamespace(
            id=uuid.uuid4(),
            meta_info=normalized_meta,
            path=f"assets/{uuid.uuid4().hex}",
            original_filename=file.filename,
            size=0,
        )


def _build_png_bytes(width: int, height: int) -> bytes:
    image = Image.new("RGB", (width, height), color=(255, 0, 0))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", dpi=(72, 72))
    return buffer.getvalue()


@pytest.mark.anyio
async def test_classic_processor_writes_image_size_meta_to_asset_and_sample(tmp_path):
    processor = ClassicProcessor(session=None)
    fake_asset_service = _FakeAssetService()
    processor.asset_service = fake_asset_service

    upload = UploadFile(
        filename="sample.png",
        file=io.BytesIO(_build_png_bytes(64, 48)),
        headers={"content-type": "image/png"},
    )
    context = UploadContext(dataset_id=str(uuid.uuid4()), upload_dir=tmp_path)

    result = await processor.process_upload(upload, context)

    assert result.success is True
    asset_meta = fake_asset_service.calls[0]["meta_info"]
    assert asset_meta["width"] == 64
    assert asset_meta["height"] == 48

    sample_meta = result.sample_fields.get("meta_info", {})
    assert sample_meta["width"] == 64
    assert sample_meta["height"] == 48


@pytest.mark.anyio
async def test_fedo_processor_writes_generated_image_size_meta_to_asset_and_sample(tmp_path, monkeypatch):
    processor = FedoDatasetProcessor(session=None)
    fake_asset_service = _FakeAssetService()
    processor.asset_service = fake_asset_service

    monkeypatch.setattr(settings, "LUT_CACHE_DIR", str(tmp_path / "lut-cache"))

    fake_fedo_data = FedoData(
        data_bytes=b"npz-data",
        time_energy_image_bytes=_build_png_bytes(20, 20),
        l_wd_image_bytes=_build_png_bytes(20, 20),
        lookup_table_bytes=b"lookup-data",
        metadata={"source": "unit-test"},
    )
    monkeypatch.setattr(
        processor,
        "_process_file_with_processor",
        lambda *, file_content, fedo_config: fake_fedo_data,
    )

    upload = UploadFile(
        filename="sample.txt",
        file=io.BytesIO(b"2024-01-01 00:00:00 1 2 3\n"),
        headers={"content-type": "text/plain"},
    )
    context = UploadContext(
        dataset_id=str(uuid.uuid4()),
        upload_dir=tmp_path,
        config={"fedo": {"figsize": [2.0, 3.0], "dpi": 100}},
    )

    result = await processor.process_upload(upload, context)

    assert result.success is True

    visual_meta_list = [
        call["meta_info"]
        for call in fake_asset_service.calls
        if call["meta_info"].get("type") == "fedo_visualization"
    ]
    assert len(visual_meta_list) == 2
    for visual_meta in visual_meta_list:
        assert visual_meta["width"] == 200
        assert visual_meta["height"] == 300

    sample_meta = result.sample_fields.get("meta_info", {})
    assert sample_meta["width"] == 200
    assert sample_meta["height"] == 300
