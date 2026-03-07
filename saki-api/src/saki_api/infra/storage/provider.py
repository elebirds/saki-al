"""
存储抽象层实现，支持 MinIO 对象存储。

此模块提供了一个抽象的存储接口，以便在不同的存储后端之间进行切换。
当前实现支持 MinIO，但可以轻松扩展以支持其他存储系统（如 S3、Azure Blob 等）。
"""

from abc import ABC, abstractmethod
from datetime import timedelta
from pathlib import Path
from typing import List, Optional, Any

from minio import Minio
from minio.datatypes import Part
from minio.error import S3Error


class StorageObject:
    """存储对象的元数据表示"""

    def __init__(
            self,
            name: str,
            size: int,
            last_modified: Optional[str] = None,
            etag: Optional[str] = None,
    ):
        self.name = name
        self.size = size
        self.last_modified = last_modified
        self.etag = etag


class BaseStorageProvider(ABC):
    """
    存储提供者的抽象基类。
    
    定义了存储系统必须实现的核心接口，包括文件上传、下载、
    URL 生成和对象列表等功能。
    """

    @abstractmethod
    def upload_file(
            self,
            local_path: Path,
            object_name: str,
            content_type: Optional[str] = None,
    ) -> str:
        """
        上传本地文件到存储系统。
        
        Args:
            local_path: 本地文件路径
            object_name: 目标对象名称（在存储系统中的路径）
            content_type: 可选的 MIME 类型
            
        Returns:
            对象名称或 URL
            
        Raises:
            FileNotFoundError: 本地文件不存在
            StorageError: 上传失败
        """
        pass

    @abstractmethod
    def put_object(
            self,
            data: Any,
            object_name: str,
            length: int,
            content_type: Optional[str] = None,
    ) -> str:
        """
        上传字节流到存储系统。
        
        Args:
            data: 字节流对象 (BytesIO 或 类似文件对象)
            object_name: 目标对象名称
            length: 数据长度
            content_type: 可选的 MIME 类型
            
        Returns:
            对象名称
        """
        pass

    @abstractmethod
    def get_presigned_url(
            self,
            object_name: str,
            expires_delta: timedelta = timedelta(hours=1),
    ) -> str:
        """
        生成预签名 URL，允许临时访问存储对象。
        
        这是前端访问私有对象的关键方法，无需暴露存储凭证。
        
        Args:
            object_name: 对象名称
            expires_delta: URL 过期时间，默认 1 小时
            
        Returns:
            预签名 URL 字符串
            
        Raises:
            StorageError: URL 生成失败
        """
        pass

    @abstractmethod
    def get_presigned_put_url(
            self,
            object_name: str,
            expires_delta: timedelta = timedelta(hours=1),
    ) -> str:
        """
        生成用于上传的预签名 URL。

        Args:
            object_name: 目标对象名称
            expires_delta: URL 过期时间

        Returns:
            预签名 PUT URL
        """
        pass

    @abstractmethod
    def init_multipart_upload(
            self,
            object_name: str,
            content_type: Optional[str] = None,
    ) -> str:
        """
        初始化 multipart 上传并返回 upload_id。
        """
        pass

    @abstractmethod
    def presign_upload_part(
            self,
            object_name: str,
            upload_id: str,
            part_number: int,
            expires_delta: timedelta = timedelta(hours=1),
    ) -> str:
        """
        生成 multipart 分片上传 URL。
        """
        pass

    @abstractmethod
    def complete_multipart_upload(
            self,
            object_name: str,
            upload_id: str,
            parts: List[tuple[int, str]],
    ) -> None:
        """
        完成 multipart 上传。
        """
        pass

    @abstractmethod
    def abort_multipart_upload(
            self,
            object_name: str,
            upload_id: str,
    ) -> None:
        """
        中止 multipart 上传。
        """
        pass

    @abstractmethod
    def download_file(
            self,
            object_name: str,
            local_path: Path,
    ) -> None:
        """
        从存储系统下载文件到本地。
        
        主要用于下载 LUT 文件等需要本地缓存的资源。
        
        Args:
            object_name: 对象名称
            local_path: 本地保存路径
            
        Raises:
            StorageError: 下载失败
        """
        pass

    @abstractmethod
    def list_objects(
            self,
            prefix: str = "",
            recursive: bool = True,
    ) -> List[StorageObject]:
        """
        列出存储系统中的对象。
        
        Args:
            prefix: 对象名称前缀，用于过滤
            recursive: 是否递归列出子目录
            
        Returns:
            StorageObject 列表
            
        Raises:
            StorageError: 列表操作失败
        """
        pass

    @abstractmethod
    def delete_object(self, object_name: str) -> None:
        """
        删除存储对象。
        
        Args:
            object_name: 要删除的对象名称
            
        Raises:
            StorageError: 删除失败
        """
        pass

    @abstractmethod
    def object_exists(self, object_name: str) -> bool:
        """
        检查对象是否存在。
        
        Args:
            object_name: 对象名称
            
        Returns:
            True 如果对象存在，否则 False
        """
        pass

    @abstractmethod
    def get_object_bytes(self, object_name: str) -> bytes:
        """
        读取对象内容为字节数组。
        
        Args:
            object_name: 对象名称
            
        Returns:
            对象内容字节数组
        """
        pass

    @abstractmethod
    def head_object(self, object_name: str) -> StorageObject:
        """
        获取对象元数据（size/etag/last_modified）。
        """
        pass


class MinioStorageProvider(BaseStorageProvider):
    """
    MinIO 存储提供者实现。
    
    MinIO 是一个高性能的对象存储系统，兼容 Amazon S3 API。
    此实现提供了完整的文件上传、下载、URL 生成等功能。
    """

    def __init__(
            self,
            endpoint: str,
            access_key: str,
            secret_key: str,
            bucket_name: str,
            secure: bool = True,
    ):
        """
        初始化 MinIO 客户端。
        
        Args:
            endpoint: MinIO 服务器地址（不包含 http:// 或 https://）
            access_key: 访问密钥
            secret_key: 私密密钥
            bucket_name: 默认存储桶名称
            secure: 是否使用 HTTPS
        """
        self.endpoint = endpoint
        self.bucket_name = bucket_name
        self.secure = secure

        # 初始化 MinIO 客户端
        self.client = Minio(
            endpoint=endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=secure,
        )

        # 确保 bucket 存在
        self._ensure_bucket_exists()

    def _ensure_bucket_exists(self) -> None:
        """
        确保存储桶存在，如果不存在则创建。
        
        Raises:
            StorageError: 创建存储桶失败
        """
        try:
            if not self.client.bucket_exists(self.bucket_name):
                self.client.make_bucket(self.bucket_name)
        except S3Error as e:
            raise StorageError(f"Failed to ensure bucket exists: {e}") from e

    def upload_file(
            self,
            local_path: Path,
            object_name: str,
            content_type: Optional[str] = None,
    ) -> str:
        """
        上传本地文件到 MinIO。
        
        自动确保 bucket 存在，并上传文件。
        
        Args:
            local_path: 本地文件路径
            object_name: 目标对象名称
            content_type: 可选的 MIME 类型
            
        Returns:
            对象名称
            
        Raises:
            FileNotFoundError: 本地文件不存在
            StorageError: 上传失败
        """
        if not local_path.exists():
            raise FileNotFoundError(f"Local file not found: {local_path}")

        try:
            # 确保 bucket 存在
            self._ensure_bucket_exists()

            # 上传文件
            self.client.fput_object(
                bucket_name=self.bucket_name,
                object_name=object_name,
                file_path=str(local_path),
                content_type=content_type,
            )

            return object_name

        except S3Error as e:
            raise StorageError(f"Failed to upload file: {e}") from e

    def put_object(
            self,
            data: Any,
            object_name: str,
            length: int,
            content_type: Optional[str] = None,
    ) -> str:
        """
        上传字节流到 MinIO。
        """
        try:
            self._ensure_bucket_exists()
            self.client.put_object(
                bucket_name=self.bucket_name,
                object_name=object_name,
                data=data,
                length=length,
                content_type=content_type
            )
            return object_name
        except S3Error as e:
            raise StorageError(f"Failed to put object: {e}") from e

    def get_presigned_url(
            self,
            object_name: str,
            expires_delta: timedelta = timedelta(hours=1),
    ) -> str:
        """
        生成 MinIO 预签名 URL。
        
        这是前端访问私有对象的关键方法。URL 会在指定时间后过期。
        
        Args:
            object_name: 对象名称
            expires_delta: URL 过期时间，默认 1 小时
            
        Returns:
            预签名 URL 字符串
            
        Raises:
            StorageError: URL 生成失败
        """
        try:
            url = self.client.presigned_get_object(
                bucket_name=self.bucket_name,
                object_name=object_name,
                expires=expires_delta,
            )

            return url

        except S3Error as e:
            raise StorageError(f"Failed to generate presigned URL: {e}") from e

    def get_presigned_put_url(
            self,
            object_name: str,
            expires_delta: timedelta = timedelta(hours=1),
    ) -> str:
        """
        生成 MinIO 预签名 PUT URL。
        """
        try:
            return self.client.get_presigned_url(
                method="PUT",
                bucket_name=self.bucket_name,
                object_name=object_name,
                expires=expires_delta,
            )
        except S3Error as e:
            raise StorageError(f"Failed to generate presigned PUT URL: {e}") from e

    def init_multipart_upload(
            self,
            object_name: str,
            content_type: Optional[str] = None,
    ) -> str:
        try:
            self._ensure_bucket_exists()
            headers = {"Content-Type": content_type or "application/octet-stream"}
            return self.client._create_multipart_upload(
                bucket_name=self.bucket_name,
                object_name=object_name,
                headers=headers,
            )
        except S3Error as e:
            raise StorageError(f"Failed to init multipart upload: {e}") from e

    def presign_upload_part(
            self,
            object_name: str,
            upload_id: str,
            part_number: int,
            expires_delta: timedelta = timedelta(hours=1),
    ) -> str:
        try:
            return self.client.get_presigned_url(
                method="PUT",
                bucket_name=self.bucket_name,
                object_name=object_name,
                expires=expires_delta,
                extra_query_params={
                    "partNumber": str(int(part_number)),
                    "uploadId": upload_id,
                },
            )
        except S3Error as e:
            raise StorageError(f"Failed to presign multipart upload part: {e}") from e

    def complete_multipart_upload(
            self,
            object_name: str,
            upload_id: str,
            parts: List[tuple[int, str]],
    ) -> None:
        try:
            normalized_parts = [
                Part(part_number=int(part_number), etag=str(etag).strip('"'))
                for part_number, etag in parts
            ]
            self.client._complete_multipart_upload(
                bucket_name=self.bucket_name,
                object_name=object_name,
                upload_id=upload_id,
                parts=normalized_parts,
            )
        except S3Error as e:
            raise StorageError(f"Failed to complete multipart upload: {e}") from e

    def abort_multipart_upload(
            self,
            object_name: str,
            upload_id: str,
    ) -> None:
        try:
            self.client._abort_multipart_upload(
                bucket_name=self.bucket_name,
                object_name=object_name,
                upload_id=upload_id,
            )
        except S3Error as e:
            raise StorageError(f"Failed to abort multipart upload: {e}") from e

    def download_file(
            self,
            object_name: str,
            local_path: Path,
    ) -> None:
        """
        从 MinIO 下载文件到本地。
        
        主要用于下载 LUT 文件等需要本地缓存的资源。
        
        Args:
            object_name: 对象名称
            local_path: 本地保存路径
            
        Raises:
            StorageError: 下载失败
        """
        try:
            # 确保父目录存在
            local_path.parent.mkdir(parents=True, exist_ok=True)

            # 下载文件
            self.client.fget_object(
                bucket_name=self.bucket_name,
                object_name=object_name,
                file_path=str(local_path),
            )

        except S3Error as e:
            raise StorageError(f"Failed to download file: {e}") from e

    def list_objects(
            self,
            prefix: str = "",
            recursive: bool = True,
    ) -> List[StorageObject]:
        """
        列出 MinIO 中的对象。
        
        Args:
            prefix: 对象名称前缀，用于过滤
            recursive: 是否递归列出子目录
            
        Returns:
            StorageObject 列表
            
        Raises:
            StorageError: 列表操作失败
        """
        try:
            objects = self.client.list_objects(
                bucket_name=self.bucket_name,
                prefix=prefix,
                recursive=recursive,
            )

            result = []
            for obj in objects:
                storage_obj = StorageObject(
                    name=obj.object_name,
                    size=obj.size,
                    last_modified=obj.last_modified.isoformat() if obj.last_modified else None,
                    etag=obj.etag,
                )
                result.append(storage_obj)

            return result

        except S3Error as e:
            raise StorageError(f"Failed to list objects: {e}") from e

    def delete_object(self, object_name: str) -> None:
        """
        删除 MinIO 中的对象。
        
        Args:
            object_name: 要删除的对象名称
            
        Raises:
            StorageError: 删除失败
        """
        try:
            self.client.remove_object(
                bucket_name=self.bucket_name,
                object_name=object_name,
            )
        except S3Error as e:
            raise StorageError(f"Failed to delete object: {e}") from e

    def object_exists(self, object_name: str) -> bool:
        """
        检查 MinIO 中的对象是否存在。
        
        Args:
            object_name: 对象名称
            
        Returns:
            True 如果对象存在，否则 False
        """
        try:
            self.client.stat_object(
                bucket_name=self.bucket_name,
                object_name=object_name,
            )
            return True
        except S3Error as e:
            if e.code == "NoSuchKey":
                return False
            raise StorageError(f"Failed to check object existence: {e}") from e

    def get_object_bytes(self, object_name: str) -> bytes:
        """
        读取对象内容为字节数组。
        
        Args:
            object_name: 对象名称
            
        Returns:
            对象内容字节数组
        """
        try:
            response = self.client.get_object(
                bucket_name=self.bucket_name,
                object_name=object_name,
            )
            try:
                return response.read()
            finally:
                response.close()
                response.release_conn()
        except S3Error as e:
            raise StorageError(f"Failed to get object bytes: {e}") from e

    def head_object(self, object_name: str) -> StorageObject:
        try:
            stat = self.client.stat_object(
                bucket_name=self.bucket_name,
                object_name=object_name,
            )
            return StorageObject(
                name=object_name,
                size=int(getattr(stat, "size", 0) or 0),
                last_modified=stat.last_modified.isoformat() if getattr(stat, "last_modified", None) else None,
                etag=getattr(stat, "etag", None),
            )
        except S3Error as e:
            raise StorageError(f"Failed to stat object: {e}") from e


class StorageError(Exception):
    """存储操作相关的异常"""
    pass


# ==================== Storage Factory ====================

# 全局存储提供者实例（单例模式）
_storage_provider: Optional[BaseStorageProvider] = None


def get_storage_provider() -> BaseStorageProvider:
    """
    获取存储提供者实例（单例模式）。
    
    根据配置返回相应的存储提供者。目前支持 MinIO。
    
    Returns:
        存储提供者实例
        
    Raises:
        StorageError: 配置错误或初始化失败
    """
    global _storage_provider

    if _storage_provider is None:
        # 延迟导入以避免循环依赖
        from saki_api.core.config import settings

        # 目前只支持 MinIO，未来可以根据配置选择不同的存储后端
        _storage_provider = MinioStorageProvider(
            endpoint=settings.MINIO_ENDPOINT,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            bucket_name=settings.MINIO_BUCKET_NAME,
            secure=settings.MINIO_SECURE,
        )

    return _storage_provider


def reset_storage_provider() -> None:
    """
    重置存储提供者实例。
    
    主要用于测试或配置更新后重新初始化。
    """
    global _storage_provider
    _storage_provider = None
