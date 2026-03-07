#!/bin/sh
# PostgreSQL 数据库备份脚本
# 将数据库备份到 COS/S3 兼容存储

set -e

# 加载环境变量
if [ -f /backup/.env ]; then
    . /backup/.env
else
    echo "错误: /backup/.env 文件不存在"
    exit 1
fi

# 默认值
: "${POSTGRES_HOST:=postgres}"
: "${POSTGRES_PORT:=5432}"
: "${POSTGRES_DB:=saki}"
: "${POSTGRES_USER:=postgres}"
: "${POSTGRES_PASSWORD:=postgres}"
: "${MINIO_ENDPOINT:=minio:9000}"
: "${MINIO_ACCESS_KEY:=minioadmin}"
: "${MINIO_SECRET_KEY:=minioadmin}"
: "${MINIO_SECURE:=false}"
: "${MINIO_BUCKET_NAME:=saki-data}"
: "${BACKUP_COS_PREFIX:=saki-backups/db}"
: "${BACKUP_RETENTION_DAYS:=7}"

# 生成备份文件名
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILENAME="${POSTGRES_DB}_${TIMESTAMP}.sql.gz"
BACKUP_FILE="/tmp/${BACKUP_FILENAME}"

echo "=========================================="
echo "数据库备份开始: $(date)"
echo "=========================================="
echo "数据库: ${POSTGRES_HOST}:${POSTGRES_PORT}/${POSTGRES_DB}"
echo "备份文件: ${BACKUP_FILENAME}"

# 执行备份
echo "正在执行 pg_dump..."
PGPASSWORD="${POSTGRES_PASSWORD}" pg_dump \
    -h "${POSTGRES_HOST}" \
    -p "${POSTGRES_PORT}" \
    -U "${POSTGRES_USER}" \
    -d "${POSTGRES_DB}" \
    --no-owner \
    --no-acl \
    --format=plain | gzip > "${BACKUP_FILE}"

# 检查备份文件
if [ ! -s "${BACKUP_FILE}" ]; then
    echo "错误: 备份文件为空"
    exit 1
fi

BACKUP_SIZE=$(du -h "${BACKUP_FILE}" | cut -f1)
echo "备份完成: ${BACKUP_SIZE}"

# 上传到 COS/S3
echo "正在上传到对象存储..."

# 使用 AWS CLI (兼容腾讯云 COS、阿里云 OSS)
if command -v aws >/dev/null 2>&1; then
    ENDPOINT="https://${MINIO_ENDPOINT}"
    if [ "${MINIO_SECURE}" = "false" ]; then
        ENDPOINT="http://${MINIO_ENDPOINT}"
    fi

    aws s3 cp "${BACKUP_FILE}" \
        "s3://${MINIO_BUCKET_NAME}/${BACKUP_COS_PREFIX}/${BACKUP_FILENAME}" \
        --endpoint-url "${ENDPOINT}" \
        --region "${AWS_REGION:-us-east-1}" \
        --no-verify-ssl

    echo "上传完成"
else
    echo "警告: awscli 未安装，跳过上传"
    echo "备份文件保存在容器内: ${BACKUP_FILE}"
fi

# 清理本地备份文件
rm -f "${BACKUP_FILE}"

# 清理过期备份
echo "正在清理超过 ${BACKUP_RETENTION_DAYS} 天的旧备份..."
if command -v aws >/dev/null 2>&1; then
    # 获取备份列表并删除过期文件
    EXPIRE_DATE=$(date -d "${BACKUP_RETENTION_DAYS} days ago" +%Y%m%d%H%M%S 2>/dev/null || date -v-${BACKUP_RETENTION_DAYS}d +%Y%m%d%H%M%S)

    aws s3 ls "s3://${MINIO_BUCKET_NAME}/${BACKUP_COS_PREFIX}/" \
        --endpoint-url "${ENDPOINT}" \
        --recursive | while read -r line; do
        FILE_DATE=$(echo "$line" | grep -oP '\d{8}_\d{6}' | head -1 | tr -d '_')
        if [ -n "$FILE_DATE" ] && [ "$FILE_DATE" -lt "$EXPIRE_DATE" ]; then
            FILE_KEY=$(echo "$line" | awk '{print $4}')
            echo "删除过期备份: ${FILE_KEY}"
            aws s3 rm "s3://${MINIO_BUCKET_NAME}/${FILE_KEY}" \
                --endpoint-url "${ENDPOINT}"
        fi
    done
fi

echo "=========================================="
echo "备份任务完成: $(date)"
echo "=========================================="
