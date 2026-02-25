#!/bin/sh
# Saki API Entrypoint - 处理 URL 编码

set -e

# 如果 DATABASE_URL 未设置，从各组件构建（正确处理密码编码）
if [ -z "$DATABASE_URL" ] && [ -n "$SAKI_POSTGRES_PASSWORD" ]; then
    # 使用 python 进行 URL 编码，确保密码中的特殊字符被正确处理
    encoded_password=$(python3 -c "import urllib.parse; print(urllib.parse.quote('$SAKI_POSTGRES_PASSWORD', safe=''))")
    export DATABASE_URL="postgresql://${SAKI_POSTGRES_USER:-postgres}:${encoded_password}@postgres:5432/${SAKI_POSTGRES_DB:-saki}"
fi

# 执行原来的命令
exec "$@"
