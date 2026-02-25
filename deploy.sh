#!/usr/bin/env bash
# Saki 一键部署脚本

set -Eeuo pipefail

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() { printf "${GREEN}[INFO]${NC} %s\n" "$*"; }
log_warn() { printf "${YELLOW}[WARN]${NC} %s\n" "$*" >&2; }
log_error() { printf "${RED}[ERROR]${NC} %s\n" "$*" >&2; }
log_step() { printf "${BLUE}[STEP]${NC} %s\n" "$*"; }

# 生成随机密钥
generate_secret_key() {
    if command -v openssl >/dev/null 2>&1; then
        openssl rand -hex 32
    elif command -v sha256sum >/dev/null 2>&1; then
        date +%s%N | sha256sum | awk '{print $1}'
    elif command -v shasum >/dev/null 2>&1; then
        date +%s%N | shasum -a 256 | awk '{print $1}'
    else
        printf "saki-secret-%s" "$(date +%s)"
    fi
}

# 检查 Docker 环境
check_docker() {
    log_step "检查 Docker 环境..."

    if ! command -v docker >/dev/null 2>&1; then
        log_error "未找到 Docker，请先安装 Docker"
        printf "访问 https://docs.docker.com/get-docker/ 获取安装指南\n"
        exit 1
    fi

    if ! docker info >/dev/null 2>&1; then
        log_error "Docker 当前不可用（可能是权限或 daemon 未启动）"
        printf "建议执行：\n"
        printf "  sudo usermod -aG docker %s\n" "${USER:-$LOGNAME}"
        printf "  然后重新登录，或执行: newgrp docker\n"
        exit 1
    fi

    # 检查 docker compose
    if docker compose version >/dev/null 2>&1; then
        COMPOSE_CMD=(docker compose)
    elif command -v docker-compose >/dev/null 2>&1; then
        COMPOSE_CMD=(docker-compose)
    else
        log_error "未找到 Docker Compose，请安装 docker compose 或 docker-compose"
        exit 1
    fi

    log_info "使用 Compose 命令: ${COMPOSE_CMD[*]}"
}

# 生成 .env 配置
generate_env() {
    log_step "配置环境变量..."

    if [ -f .env ]; then
        log_warn ".env 文件已存在"
        read -r -p "是否重新配置? (y/N): " reply
        if [[ ! "$reply" =~ ^[Yy]$ ]]; then
            log_info "使用现有 .env 配置"
            return
        fi
        mv .env .env.backup."$(date +%s)"
        log_info "已备份现有 .env 文件"
    fi

    # 复制模板
    if [ -f .env.docker ]; then
        cp .env.docker .env
    else
        log_error "未找到 .env.docker 模板文件"
        exit 1
    fi

    # 数据库密码配置
    echo ""
    printf "========================================\n"
    printf "数据库配置\n"
    printf "========================================\n"
    read -r -p "数据库密码 [默认: 自动生成]: " db_password
    if [ -z "$db_password" ]; then
        db_password="$(generate_secret_key)"
        log_info "已生成数据库密码: $db_password"
    fi

    # SECRET_KEY 配置
    echo ""
    printf "========================================\n"
    printf "安全配置\n"
    printf "========================================\n"
    read -r -p "SECRET_KEY (留空自动生成): " secret_key
    if [ -z "$secret_key" ]; then
        secret_key="$(generate_secret_key)"
        log_info "已生成 SECRET_KEY: $secret_key"
    fi

    # 对象存储配置
    echo ""
    printf "========================================\n"
    printf "对象存储配置\n"
    printf "========================================\n"
    printf "选择对象存储类型:\n"
    printf "  1) 内置 MinIO (适合开发/测试)\n"
    printf "  2) 腾讯云 COS\n"
    printf "  3) 阿里云 OSS\n"
    printf "  4) AWS S3 或其他兼容 S3 的服务\n"
    printf "  5) 跳过 (手动配置)\n"
    read -r -p "请选择 [1-5, 默认: 1]: " storage_choice
    storage_choice="${storage_choice:-1}"

    case "$storage_choice" in
        2)
            # 腾讯云 COS
            read -r -p "COS Bucket名称 (如: saki-xxxxxx): " cos_bucket
            read -r -p "COS 地域 (如: ap-nanjing): " cos_region
            read -r -p "SecretId (AKID...): " cos_akid
            read -r -p "SecretKey: " cos_key

            # 更新配置
            if command -v sed >/dev/null 2>&1; then
                sed -i.bak "s|MINIO_ENDPOINT=.*|MINIO_ENDPOINT=${cos_bucket}.cos.${cos_region}.myqcloud.com|" .env
                sed -i.bak "s|MINIO_ACCESS_KEY=.*|MINIO_ACCESS_KEY=${cos_akid}|" .env
                sed -i.bak "s|MINIO_SECRET_KEY=.*|MINIO_SECRET_KEY=${cos_key}|" .env
                sed -i.bak "s|MINIO_SECURE=.*|MINIO_SECURE=true|" .env
                sed -i.bak "s|MINIO_BUCKET_NAME=.*|MINIO_BUCKET_NAME=${cos_bucket}|" .env
                rm -f .env.bak
            fi
            log_info "已配置腾讯云 COS"
            ;;
        3)
            # 阿里云 OSS
            read -r -p "OSS Bucket名称 (如: saki-xxxxxx): " oss_bucket
            read -r -p "OSS 地域 (如: oss-cn-hangzhou): " oss_region
            read -r -p "AccessKey ID: " oss_keyid
            read -r -p "AccessKey Secret: " oss_secret

            if command -v sed >/dev/null 2>&1; then
                sed -i.bak "s|MINIO_ENDPOINT=.*|MINIO_ENDPOINT=${oss_region}.aliyuncs.com|" .env
                sed -i.bak "s|MINIO_ACCESS_KEY=.*|MINIO_ACCESS_KEY=${oss_keyid}|" .env
                sed -i.bak "s|MINIO_SECRET_KEY=.*|MINIO_SECRET_KEY=${oss_secret}|" .env
                sed -i.bak "s|MINIO_SECURE=.*|MINIO_SECURE=true|" .env
                sed -i.bak "s|MINIO_BUCKET_NAME=.*|MINIO_BUCKET_NAME=${oss_bucket}|" .env
                rm -f .env.bak
            fi
            log_info "已配置阿里云 OSS"
            ;;
        4)
            # AWS S3 或其他
            read -r -p "S3 Endpoint (如: s3.amazonaws.com): " s3_endpoint
            read -r -p "Access Key ID: " s3_keyid
            read -r -p "Secret Access Key: " s3_secret
            read -r -p "Bucket Name: " s3_bucket
            read -r -p "使用 HTTPS? (Y/n): " s3_secure
            s3_secure="${s3_secure:-Y}"
            if [[ "$s3_secure" =~ ^[Yy]$ ]]; then
                s3_secure="true"
            else
                s3_secure="false"
            fi

            if command -v sed >/dev/null 2>&1; then
                sed -i.bak "s|MINIO_ENDPOINT=.*|MINIO_ENDPOINT=${s3_endpoint}|" .env
                sed -i.bak "s|MINIO_ACCESS_KEY=.*|MINIO_ACCESS_KEY=${s3_keyid}|" .env
                sed -i.bak "s|MINIO_SECRET_KEY=.*|MINIO_SECRET_KEY=${s3_secret}|" .env
                sed -i.bak "s|MINIO_SECURE=.*|MINIO_SECURE=${s3_secure}|" .env
                sed -i.bak "s|MINIO_BUCKET_NAME=.*|MINIO_BUCKET_NAME=${s3_bucket}|" .env
                rm -f .env.bak
            fi
            log_info "已配置 S3 兼容存储"
            ;;
        5)
            log_info "跳过对象存储配置，请手动编辑 .env 文件"
            ;;
        *)
            log_info "使用内置 MinIO 配置"
            ;;
    esac

    # 更新数据库密码和 SECRET_KEY
    if command -v sed >/dev/null 2>&1; then
        sed -i.bak "s/SAKI_POSTGRES_PASSWORD=.*/SAKI_POSTGRES_PASSWORD=$db_password/" .env
        sed -i.bak "s/SECRET_KEY=.*/SECRET_KEY=$secret_key/" .env
        rm -f .env.bak
    fi

    # 数据目录配置
    echo ""
    printf "========================================\n"
    printf "数据目录配置\n"
    printf "========================================\n"
    read -r -p "数据存储目录 [默认: ~/saki/data]: " data_dir
    if [ -z "$data_dir" ]; then
        data_dir="~/saki/data"
    fi
    # 展开 ~
    data_dir="${data_dir/#\~/$HOME}"
    if command -v sed >/dev/null 2>&1; then
        sed -i.bak "s|SAKI_DATA_DIR=.*|SAKI_DATA_DIR=$data_dir|" .env
        rm -f .env.bak
    fi
    log_info "数据目录: $data_dir"

    # 数据库备份配置
    echo ""
    printf "========================================\n"
    printf "数据库备份配置\n"
    printf "========================================\n"
    read -r -p "是否启用数据库自动备份到对象存储? (y/N): " enable_backup
    if [[ "$enable_backup" =~ ^[Yy]$ ]]; then
        read -r -p "备份周期 (cron 格式, 默认: 每天 2:00 AM): " backup_schedule
        backup_schedule="${backup_schedule:-0 2 * * *}"
        read -r -p "保留天数 [默认: 7]: " retention_days
        retention_days="${retention_days:-7}"

        if command -v sed >/dev/null 2>&1; then
            sed -i.bak "s/BACKUP_ENABLED=.*/BACKUP_ENABLED=true/" .env
            sed -i.bak "s/BACKUP_SCHEDULE=.*/BACKUP_SCHEDULE=$backup_schedule/" .env
            sed -i.bak "s/BACKUP_RETENTION_DAYS=.*/BACKUP_RETENTION_DAYS=$retention_days/" .env
            rm -f .env.bak
        fi
        log_info "已启用数据库自动备份"
        log_info "   备份周期: $backup_schedule"
        log_info "   保留天数: $retention_days 天"
    else
        if command -v sed >/dev/null 2>&1; then
            sed -i.bak "s/BACKUP_ENABLED=.*/BACKUP_ENABLED=false/" .env
            rm -f .env.bak
        fi
        log_info "未启用数据库备份"
    fi

    log_info ".env 配置完成"
}

# 创建数据目录
create_directories() {
    log_step "创建数据目录..."

    # 从 .env 读取 SAKI_DATA_DIR
    local data_dir="${SAKI_DATA_DIR:-./data}"
    # 展开 ~
    data_dir="${data_dir/#\~/$HOME}"

    mkdir -p "$data_dir/postgres"
    mkdir -p "$data_dir/minio"
    mkdir -p "$data_dir/saki-api/data"
    mkdir -p "$data_dir/saki-api/logs"
    mkdir -p "$data_dir/saki-executor/runs"
    mkdir -p "$data_dir/saki-executor/cache"
    mkdir -p "$data_dir/saki-executor/logs"

    log_info "数据目录创建完成: $data_dir"
}

# 构建 Docker 镜像
build_images() {
    log_step "构建 Docker 镜像（这可能需要几分钟）..."

    # 禁用 provenance metadata 以避免网络超时（特别是在国内服务器）
    export BUILDKIT_METADATA_PROVENANCE=none
    export DOCKER_BUILDKIT=1

    if ! "${COMPOSE_CMD[@]}" build; then
        log_error "镜像构建失败"
        log_warn "提示：如遇网络问题，可配置 Docker 镜像加速"
        exit 1
    fi

    log_info "镜像构建完成"
}

# 启动服务
start_services() {
    log_step "启动基础服务..."

    # 首先启动基础服务（postgres, redis）
    "${COMPOSE_CMD[@]}" up -d postgres redis

    # 检查是否需要启动内置 MinIO
    if grep -q "MINIO_ENDPOINT=minio:9000" .env 2>/dev/null; then
        log_info "检测到内置 MinIO 配置，启动 MinIO..."
        "${COMPOSE_CMD[@]}" --profile minio up -d minio
        log_info "MinIO 控制台: http://localhost:9001 (minioadmin/minioadmin)"
        # 等待 MinIO 就绪
        log_info "等待 MinIO 启动..."
        local max_wait=30
        local waited=0
        while [ $waited -lt $max_wait ]; do
            if docker ps | grep -q "saki-minio.*healthy"; then
                log_info "MinIO 已就绪"
                break
            fi
            sleep 2
            waited=$((waited + 2))
        done
    else
        log_info "使用外部对象存储，跳过内置 MinIO"
    fi

    log_step "启动应用服务..."
    # 启动应用服务（saki-api 依赖 MinIO，saki-dispatcher 依赖 saki-api）
    "${COMPOSE_CMD[@]}" up -d saki-api saki-dispatcher saki-web

    # 检查是否需要启动数据库备份服务
    if grep -q "BACKUP_ENABLED=true" .env 2>/dev/null; then
        log_info "检测到已启用数据库备份，启动备份服务..."
        "${COMPOSE_CMD[@]}" --profile backup up -d db-backup
        log_info "数据库备份服务已启动，日志: docker compose logs -f db-backup"
    fi

    log_info "核心服务启动完成"
}

# 等待服务就绪
wait_for_services() {
    log_step "等待服务启动..."

    local max_wait=60
    local waited=0

    while [ $waited -lt $max_wait ]; do
        if docker ps | grep -q "saki-api.*Up"; then
            log_info "saki-api 已启动"
            break
        fi
        sleep 2
        waited=$((waited + 2))
    done

    if [ $waited -ge $max_wait ]; then
        log_warn "saki-api 未能在预期时间内启动"
        log_warn "请检查日志: ${COMPOSE_CMD[*]} logs saki-api"
    fi
}

# 显示服务状态
show_status() {
    echo ""
    log_info "服务状态:"
    echo ""
    "${COMPOSE_CMD[@]}" ps
}

# 显示访问地址
show_access_info() {
    echo ""
    printf "========================================\n"
    printf "${GREEN}部署完成！${NC}\n"
    printf "========================================\n"
    echo ""
    printf "🌐 访问地址:\n"
    printf "   前端:       http://localhost\n"
    printf "   API:        http://localhost:8000\n"
    printf "   API 文档:   http://localhost:8000/docs\n"
    printf "   MinIO 控制台: http://localhost:9001 (如果已启动)\n"
    echo ""
    printf "📂 数据存储:\n"
    local data_dir="${SAKI_DATA_DIR:-~/saki/data}"
    data_dir="${data_dir/#\~/$HOME}"
    printf "   数据目录: $data_dir\n"
    printf "   请定期备份此目录，或启用自动备份服务\n"
    echo ""
    printf "📝 常用命令:\n"
    printf "   查看日志:   ${COMPOSE_CMD[*]} logs -f\n"
    printf "   查看日志:   ${COMPOSE_CMD[*]} logs -f [服务名]\n"
    printf "   停止服务:   ${COMPOSE_CMD[*]} stop\n"
    printf "   重启服务:   ${COMPOSE_CMD[*]} restart\n"
    printf "   删除服务:   ${COMPOSE_CMD[*]} down\n"
    printf "   启动 Executor: ${COMPOSE_CMD[*]} --profile saki-executor up -d saki-executor\n"
    if grep -q "BACKUP_ENABLED=true" .env 2>/dev/null; then
        printf "   备份日志:   ${COMPOSE_CMD[*]} logs -f db-backup\n"
        printf "   手动备份:  ${COMPOSE_CMD[*]} exec db-backup /backup/backup-db.sh\n"
    fi
    echo ""
    printf "========================================\n"
}

# 主流程
main() {
    clear
    printf "${BLUE}"
    cat << "EOF"
   ____  __  __          _____ _
  |  _ \|  \/  |   /\   / ____| |
  | |_) | \  / |  /  \ | |    | |      Saki Active Learning
  |  _ <| |\/| | / /\ \| |    | |      一键部署脚本
  | |_) | |  | |/ ____ \ |____| |____
  |____/|_|  |_/_/    \_\_____|______|

EOF
    printf "${NC}"

    # 检查是否在项目根目录
    if [ ! -f docker-compose.yml ]; then
        log_error "当前目录未找到 docker-compose.yml，请在项目根目录执行此脚本"
        exit 1
    fi

    check_docker
    generate_env
    create_directories
    build_images
    start_services
    wait_for_services
    show_status
    show_access_info
}

# 运行主流程
main
