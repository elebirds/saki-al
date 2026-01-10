import re
from datetime import datetime, timedelta
from typing import Any, Union

from jose import jwt
from passlib.context import CryptContext

from saki_api.core.config import settings

pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")


def create_access_token(subject: Union[str, Any], expires_delta: timedelta = None) -> str:
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode = {"exp": expire, "sub": str(subject)}
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt


def is_frontend_hashed_password(password: str) -> bool:
    """
    检查密码是否是前端哈希后的（SHA-256 哈希是 64 字符的十六进制字符串）
    """
    # SHA-256 哈希后的密码是 64 字符的十六进制字符串
    return len(password) == 64 and bool(re.match(r'^[0-9a-f]{64}$', password, re.IGNORECASE))


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    验证密码。
    
    只接受前端哈希后的密码（64字符十六进制），不再支持原始密码。
    """
    # 只接受前端哈希后的密码
    if not is_frontend_hashed_password(plain_password):
        return False

    # 数据库中的哈希值应该是前端哈希值经过 Argon2 哈希后的结果
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """
    对密码进行哈希。
    
    只接受前端哈希后的密码（64字符十六进制），不再支持原始密码。
    """
    # 只接受前端哈希后的密码
    if not is_frontend_hashed_password(password):
        raise ValueError("密码必须是前端哈希后的格式（64字符十六进制字符串）")

    # 对前端哈希后的密码进行 Argon2 哈希
    return pwd_context.hash(password)
