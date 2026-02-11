"""
数据库审计字段自动填充。

使用 SQLAlchemy 事件监听器结合 ContextVars 来自动填充 create_by、update_by 和时间戳字段。
"""
from loguru import logger
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import event
from sqlmodel import SQLModel

from saki_api.core.context import get_current_user_id
from saki_api.models.base import AuditMixin, TimestampMixin



def setup_audit_listeners() -> None:
    """
    设置 SQLAlchemy 事件监听器，用于自动填充审计字段和时间戳。
    
    监听 before_insert 和 before_update 事件，自动填充：
    - created_by, updated_by (如果模型继承 AuditMixin)
    - created_at, updated_at (如果模型继承 TimestampMixin)
    """

    @event.listens_for(SQLModel, "before_insert", propagate=True)
    def receive_before_insert(mapper: Any, connection: Any, target: Any) -> None:
        """
        在插入记录之前，自动填充审计字段和时间戳。
        
        Args:
            mapper: SQLAlchemy mapper
            connection: 数据库连接
            target: 要插入的模型实例
        """
        now = datetime.now(UTC)

        # 处理时间戳字段
        if isinstance(target, TimestampMixin):
            # 如果 created_at 未设置，设置为当前时间
            if target.created_at is None:
                target.created_at = now
            # 如果 updated_at 未设置，设置为当前时间
            if target.updated_at is None:
                target.updated_at = now

        # 处理审计字段
        if isinstance(target, AuditMixin):
            user_id = get_current_user_id()
            logger.info(
                "插入前审计字段填充 model={} user_id={} created_by={} updated_by={}",
                target.__class__.__name__,
                user_id,
                getattr(target, "created_by", None),
                getattr(target, "updated_by", None),
            )
            if user_id is not None:
                # 只有在字段未设置时才自动填充
                if target.created_by is None:
                    target.created_by = user_id
                    logger.info("已自动设置 created_by model={} user_id={}", target.__class__.__name__, user_id)
                # 插入时也设置 updated_by
                if target.updated_by is None:
                    target.updated_by = user_id
                    logger.info("已自动设置 updated_by model={} user_id={}", target.__class__.__name__, user_id)
            else:
                logger.warning(
                    "未获取到当前用户 ID，跳过审计字段填充 model={}",
                    target.__class__.__name__,
                )

    @event.listens_for(SQLModel, "before_update", propagate=True)
    def receive_before_update(mapper: Any, connection: Any, target: Any) -> None:
        """
        在更新记录之前，自动更新 updated_at 和 updated_by 字段。
        
        Args:
            mapper: SQLAlchemy mapper
            connection: 数据库连接
            target: 要更新的模型实例
        """
        now = datetime.now(UTC)

        # 处理时间戳字段 - 更新时自动更新 updated_at
        if isinstance(target, TimestampMixin):
            target.updated_at = now

        # 处理审计字段
        if isinstance(target, AuditMixin):
            user_id = get_current_user_id()
            logger.info(
                "更新前审计字段填充 model={} user_id={} updated_by={}",
                target.__class__.__name__,
                user_id,
                getattr(target, "updated_by", None),
            )
            if user_id is not None:
                target.updated_by = user_id
                logger.info("已自动更新 updated_by model={} user_id={}", target.__class__.__name__, user_id)
            else:
                logger.warning(
                    "未获取到当前用户 ID，跳过审计字段填充 model={}",
                    target.__class__.__name__,
                )
