#!/bin/sh
# Saki Dispatcher Entrypoint - 处理 URL 编码

set -e

# URL 编码函数（使用 busybox httpd 或手动编码）
url_encode() {
    local string="$1"
    local encoded=""
    local c i n

    # 简单的 URL 编码 - 处理常见特殊字符
    echo "$string" | sed -e 's/%/%25/g' \
                      -e 's/ /%20/g' \
                      -e 's/!/%21/g' \
                      -e 's/#/%23/g' \
                      -e 's/\$/%24/g' \
                      -e 's/&/%26/g' \
                      -e 's/'\''/%27/g' \
                      -e 's/(/%28/g' \
                      -e 's/)/%29/g' \
                      -e 's/\*/%2A/g' \
                      -e 's/+/%2B/g' \
                      -e 's/,/%2C/g' \
                      -e 's/\//%2F/g' \
                      -e 's/:/%3A/g' \
                      -e 's/;/%3B/g' \
                      -e 's/=/%3D/g' \
                      -e 's/?/%3F/g' \
                      -e 's/@/%40/g'
}

# 如果 DATABASE_URL 未设置，从各组件构建（正确处理密码编码）
if [ -z "$DATABASE_URL" ] && [ -n "$SAKI_POSTGRES_PASSWORD" ]; then
    encoded_password=$(url_encode "$SAKI_POSTGRES_PASSWORD")
    export DATABASE_URL="postgresql://${SAKI_POSTGRES_USER:-postgres}:${encoded_password}@postgres:5432/${SAKI_POSTGRES_DB:-saki}"
fi

# 执行原来的命令
exec "$@"
