"""
业务错误码枚举定义。
"""

from enum import IntEnum


class ErrorCode(IntEnum):
    """
    业务错误码枚举。
    
    错误码规则：
    - 0: 成功
    - 1xxx: 系统级错误
    - 2xxx: 认证授权相关错误
    - 3xxx: 数据相关错误
    - 4xxx: HTTP标准状态码映射（4000-4999）
    """
    # 成功
    SUCCESS = 0

    # HTTP标准状态码映射
    BAD_REQUEST = 4000
    UNAUTHORIZED = 4001
    FORBIDDEN = 4003
    NOT_FOUND = 4004
    METHOD_NOT_ALLOWED = 4005
    CONFLICT = 4009
    UNPROCESSABLE_ENTITY = 4220
    INTERNAL_SERVER_ERROR = 5000

    # 认证授权相关 (2xxx)
    AUTH_ERROR = 2000
    AUTH_INVALID_CREDENTIALS = 2001
    AUTH_INACTIVE_USER = 2002
    AUTH_INVALID_TOKEN = 2003
    AUTH_INCORRECT_PASSWORD = 2004
    AUTH_PERMISSION_DENIED = 2005

    # 数据相关 (3xxx)
    DATA_ERROR = 3000
    DATA_NOT_FOUND = 3001
    DATA_ALREADY_EXISTS = 3002
    DATA_VALIDATION_ERROR = 3003
    DATA_INVALID_FORMAT = 3004
