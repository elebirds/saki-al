from __future__ import annotations

import mimetypes
import shutil
import tempfile
import uuid
import zipfile
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import UploadFile
from starlette.datastructures import Headers
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.core.exceptions import BadRequestAppException
from saki_api.modules.importing.schema import ImportImageEntry
from saki_api.modules.project.service.dataset import DatasetService
from saki_api.modules.project.service.sample import SampleService
from saki_api.modules.shared.modeling.enums import DatasetType
from saki_api.modules.storage.domain.sample import Sample
from saki_api.modules.storage.service.asset import AssetService


class SampleBulkService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.dataset_service = DatasetService(session)
        self.sample_service = SampleService(session)
        self.asset_service = AssetService(session)

    async def iter_bulk_upload_local_files(
        self,
        *,
        dataset_id: uuid.UUID,
        files: list[dict[str, str]],
    ) -> AsyncIterator[dict[str, Any]]:
        dataset = await self.dataset_service.get_by_id_or_raise(dataset_id)
        if dataset.type != DatasetType.CLASSIC:
            raise BadRequestAppException("Bulk upload only supports classic dataset")

        upload_files: list[UploadFile] = []
        try:
            for item in files:
                filename = str(item.get("filename") or "")
                local_path = Path(str(item.get("path") or "")).resolve()
                if not filename or not local_path.exists() or not local_path.is_file():
                    continue
                file_handle = local_path.open("rb")
                upload_files.append(
                    UploadFile(
                        file=file_handle,
                        filename=filename,
                        headers=Headers({"content-type": str(item.get("content_type") or "application/octet-stream")}),
                    )
                )

            facade = self.sample_service._initialize_handler(dataset.type)
            process_context = self.sample_service._build_processing_context(dataset.id)

            total = len(upload_files)
            yield {
                "event": "start",
                "phase": "sample_bulk_upload",
                "message": "bulk sample ingest started",
                "current": 0,
                "total": total,
            }

            uploaded = 0
            failed = 0
            async for event in self.sample_service.iter_sample_process_events(
                dataset=dataset,
                files=upload_files,
                facade=facade,
                process_context=process_context,
            ):
                et = str(event.get("event") or "")
                if et == "sample_complete":
                    uploaded += 1
                    current = uploaded + failed
                    if current % 100 == 0 or current == total:
                        yield {
                            "event": "phase",
                            "phase": "sample_bulk_upload",
                            "message": f"processed {current}/{total}",
                            "current": current,
                            "total": total,
                        }
                elif et == "sample_error":
                    failed += 1
                    current = uploaded + failed
                    yield {
                        "event": "error",
                        "phase": "sample_bulk_upload",
                        "message": str(event.get("error") or "upload failed"),
                        "item_key": str(event.get("filename") or ""),
                        "current": current,
                        "total": total,
                        "detail": {"code": "SAMPLE_UPLOAD_FAILED"},
                    }

            yield {
                "event": "complete",
                "message": "bulk sample ingest completed",
                "detail": {
                    "dataset_id": str(dataset_id),
                    "uploaded_samples": uploaded,
                    "failed_samples": failed,
                },
            }
        finally:
            for item in upload_files:
                try:
                    item.file.close()
                except Exception:  # noqa: BLE001
                    pass

    async def iter_bulk_import_zip_entries(
        self,
        *,
        dataset_id: uuid.UUID,
        zip_asset_id: uuid.UUID,
        image_entries: list[ImportImageEntry],
        batch_size: int = 256,
    ) -> AsyncIterator[dict[str, Any]]:
        dataset = await self.dataset_service.get_by_id_or_raise(dataset_id)
        if dataset.type != DatasetType.CLASSIC:
            raise BadRequestAppException("Import only supports classic dataset in this release")

        allow_duplicate_names = bool(dataset.allow_duplicate_sample_names)
        sample_names = [] if allow_duplicate_names else await self._list_dataset_sample_names(dataset_id)
        existing = set(sample_names)

        total = len(image_entries)
        imported = 0
        reused = 0
        failed = 0

        yield {
            "event": "start",
            "phase": "dataset_images_execute",
            "message": "dataset image import started",
            "current": 0,
            "total": total,
        }

        with tempfile.TemporaryDirectory(prefix="saki-bulk-import-") as temp_dir:
            zip_local_path = Path(temp_dir) / "payload.zip"
            await self.asset_service.download_to_local(zip_asset_id, zip_local_path)

            facade = self.sample_service._initialize_handler(dataset.type)
            process_context = self.sample_service._build_processing_context(dataset.id)

            with zipfile.ZipFile(zip_local_path) as archive:
                batch_files: list[UploadFile] = []
                batch_entry_meta: list[ImportImageEntry] = []
                processed = 0

                for entry in image_entries:
                    processed += 1
                    zip_entry_path = self._normalize_name_key(entry.zip_entry_path)
                    resolved_sample_name = self._normalize_name_key(entry.resolved_sample_name)
                    original_relative_path = self._normalize_name_key(entry.original_relative_path) or zip_entry_path
                    if not zip_entry_path or not resolved_sample_name:
                        failed += 1
                        yield {
                            "event": "error",
                            "phase": "dataset_images_execute",
                            "message": "invalid image entry",
                            "item_key": zip_entry_path or resolved_sample_name or "",
                            "detail": {"code": "ZIP_ENTRY_INVALID"},
                            "current": processed,
                            "total": total,
                        }
                        continue

                    if (not allow_duplicate_names) and resolved_sample_name in existing:
                        reused += 1
                        if processed % 100 == 0 or processed == total:
                            yield {
                                "event": "phase",
                                "phase": "dataset_images_execute",
                                "message": f"processed {processed}/{total}",
                                "current": processed,
                                "total": total,
                            }
                        continue

                    try:
                        info = archive.getinfo(zip_entry_path)
                    except KeyError:
                        failed += 1
                        yield {
                            "event": "error",
                            "phase": "dataset_images_execute",
                            "message": f"zip entry missing: {zip_entry_path}",
                            "item_key": zip_entry_path,
                            "detail": {"code": "ZIP_ENTRY_MISSING"},
                            "current": processed,
                            "total": total,
                        }
                        continue

                    try:
                        upload = self._build_upload_from_zip_entry(
                            archive,
                            info,
                            resolved_sample_name=resolved_sample_name,
                            original_relative_path=original_relative_path,
                        )
                    except Exception as exc:  # noqa: BLE001
                        failed += 1
                        yield {
                            "event": "error",
                            "phase": "dataset_images_execute",
                            "message": str(exc),
                            "item_key": zip_entry_path,
                            "detail": {"code": "ZIP_ENTRY_INVALID"},
                            "current": processed,
                            "total": total,
                        }
                        continue

                    batch_files.append(upload)
                    batch_entry_meta.append(
                        ImportImageEntry(
                            zip_entry_path=zip_entry_path,
                            resolved_sample_name=resolved_sample_name,
                            original_relative_path=original_relative_path,
                            collision_action=str(entry.collision_action or "none"),
                        )
                    )
                    if not allow_duplicate_names:
                        existing.add(resolved_sample_name)

                    if len(batch_files) >= max(1, int(batch_size)):
                        async for event in self._flush_import_batch(
                            dataset=dataset,
                            files=batch_files,
                            entries=batch_entry_meta,
                            facade=facade,
                            process_context=process_context,
                        ):
                            et = str(event.get("event") or "")
                            if et == "sample_complete":
                                imported += 1
                            elif et == "sample_error":
                                failed += 1
                                yield {
                                    "event": "error",
                                    "phase": "dataset_images_execute",
                                    "message": str(event.get("error") or "sample import failed"),
                                    "item_key": str(event.get("filename") or ""),
                                    "detail": {"code": "SAMPLE_IMPORT_FAILED"},
                                }
                            elif et == "warning":
                                yield {
                                    "event": "warning",
                                    "phase": "dataset_images_execute",
                                    "message": str(event.get("message") or "metadata update warning"),
                                    "item_key": str(event.get("item_key") or ""),
                                    "detail": event.get("detail") or {"code": "SAMPLE_META_UPDATE_FAILED"},
                                }

                    if processed % 100 == 0 or processed == total:
                        yield {
                            "event": "phase",
                            "phase": "dataset_images_execute",
                            "message": f"processed {processed}/{total}",
                            "current": processed,
                            "total": total,
                        }

                if batch_files:
                    async for event in self._flush_import_batch(
                        dataset=dataset,
                        files=batch_files,
                        entries=batch_entry_meta,
                        facade=facade,
                        process_context=process_context,
                    ):
                        et = str(event.get("event") or "")
                        if et == "sample_complete":
                            imported += 1
                        elif et == "sample_error":
                            failed += 1
                            yield {
                                "event": "error",
                                "phase": "dataset_images_execute",
                                "message": str(event.get("error") or "sample import failed"),
                                "item_key": str(event.get("filename") or ""),
                                "detail": {"code": "SAMPLE_IMPORT_FAILED"},
                            }
                        elif et == "warning":
                            yield {
                                "event": "warning",
                                "phase": "dataset_images_execute",
                                "message": str(event.get("message") or "metadata update warning"),
                                "item_key": str(event.get("item_key") or ""),
                                "detail": event.get("detail") or {"code": "SAMPLE_META_UPDATE_FAILED"},
                            }

        yield {
            "event": "complete",
            "message": "bulk sample import completed",
            "detail": {
                "dataset_id": str(dataset_id),
                "allow_duplicate_sample_names": allow_duplicate_names,
                "total_entries": total,
                "imported_samples": imported,
                "reused_samples": reused,
                "failed_samples": failed,
            },
        }

    async def _flush_import_batch(
        self,
        *,
        dataset,
        files: list[UploadFile],
        entries: list[ImportImageEntry],
        facade,
        process_context,
    ) -> AsyncIterator[dict[str, Any]]:
        try:
            async for event in self.sample_service.iter_sample_process_events(
                dataset=dataset,
                files=files,
                facade=facade,
                process_context=process_context,
            ):
                et = str(event.get("event") or "")
                if et == "sample_complete":
                    index = int(event.get("index") or -1)
                    sample_id = str(event.get("sample_id") or "")
                    if sample_id and 0 <= index < len(entries):
                        try:
                            await self._update_sample_import_meta(
                                sample_id=sample_id,
                                entry=entries[index],
                            )
                        except Exception as exc:  # noqa: BLE001
                            yield {
                                "event": "warning",
                                "message": str(exc),
                                "item_key": entries[index].resolved_sample_name,
                                "detail": {"code": "SAMPLE_META_UPDATE_FAILED"},
                            }
                yield event
            await self.session.flush()
        finally:
            for item in files:
                try:
                    item.file.close()
                except Exception:  # noqa: BLE001
                    pass
            files.clear()
            entries.clear()

    async def _update_sample_import_meta(self, *, sample_id: str, entry: ImportImageEntry) -> None:
        sample = await self.session.get(Sample, uuid.UUID(sample_id))
        if sample is None:
            return

        meta_info = dict(sample.meta_info or {})
        import_meta = dict(meta_info.get("import") or {})
        import_meta.update(
            {
                "zip_entry_path": entry.zip_entry_path,
                "resolved_sample_name": entry.resolved_sample_name,
                "original_relative_path": entry.original_relative_path,
                "collision_action": entry.collision_action,
            }
        )
        meta_info["import"] = import_meta
        meta_info["original_relative_path"] = entry.original_relative_path
        sample.meta_info = meta_info
        self.session.add(sample)

    async def _list_dataset_sample_names(self, dataset_id: uuid.UUID) -> list[str]:
        stmt = select(Sample.name).where(Sample.dataset_id == dataset_id)
        rows = await self.session.exec(stmt)
        return [self._normalize_name_key(item) for item in rows.all() if self._normalize_name_key(item)]

    @staticmethod
    def _normalize_name_key(value: str) -> str:
        normalized = str(value or "").replace("\\", "/").strip()
        while normalized.startswith("./"):
            normalized = normalized[2:]
        return normalized

    @staticmethod
    def _build_upload_from_zip_entry(
        archive: zipfile.ZipFile,
        info: zipfile.ZipInfo,
        *,
        resolved_sample_name: str,
        original_relative_path: str,
    ) -> UploadFile:
        normalized = SampleBulkService._normalize_name_key(info.filename)
        sample_name = SampleBulkService._normalize_name_key(resolved_sample_name)
        source_path = SampleBulkService._normalize_name_key(original_relative_path) or normalized
        if not normalized:
            raise BadRequestAppException("invalid zip entry")
        if not sample_name:
            raise BadRequestAppException("invalid sample name")
        if normalized.startswith("/") or any(part == ".." for part in Path(normalized).parts):
            raise BadRequestAppException(f"invalid zip entry path: {info.filename}")
        mime_type = mimetypes.guess_type(sample_name)[0] or mimetypes.guess_type(normalized)[0] or "application/octet-stream"

        temp_file = tempfile.SpooledTemporaryFile(max_size=32 * 1024 * 1024)
        with archive.open(info) as src:
            shutil.copyfileobj(src, temp_file)
        temp_file.seek(0)

        return UploadFile(
            file=temp_file,
            filename=sample_name,
            headers=Headers(
                {
                    "content-type": mime_type,
                    "x-saki-original-relative-path": source_path,
                    "x-saki-zip-entry-path": normalized,
                }
            ),
        )
