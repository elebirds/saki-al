#!/usr/bin/env bash

# Saki 快速部署脚本
# 使用方法: ./deploy.sh

set -Eeuo pipefail

log_info() { printf "[INFO] %s\n" "$*"; }
log_warn() { printf "[WARN] %s\n" "$*" >&2; }
log_error() { printf "[ERROR] %s\n" "$*" >&2; }

read_env_value() {
    local key="$1"
    local default_value="$2"
    local raw
    raw="$(grep -E "^[[:space:]]*${key}=" .env | tail -n1 || true)"
    if [[ -z "$raw" ]]; then
        printf "%s" "$default_value"
        return
    fi
    raw="${raw#*=}"
    raw="$(printf "%s" "$raw" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
    raw="${raw%\"}"
    raw="${raw#\"}"
    raw="${raw%\'}"
    raw="${raw#\'}"
    if [[ -z "$raw" ]]; then
        printf "%s" "$default_value"
    else
        printf "%s" "$raw"
    fi
}

set_env_value() {
    local key="$1"
    local value="$2"
    local tmp_file
    tmp_file="$(mktemp)"
    awk -v key="$key" -v value="$value" '
        BEGIN { done = 0 }
        $0 ~ "^[[:space:]]*" key "=" {
            print key "=" value
            done = 1
            next
        }
        { print }
        END {
            if (!done) {
                print key "=" value
            }
        }
    ' .env >"$tmp_file"
    mv "$tmp_file" .env
}

prompt_with_default() {
    local label="$1"
    local default_value="$2"
    local input
    read -r -p "$label [$default_value]: " input
    if [[ -z "$input" ]]; then
        printf "%s" "$default_value"
    else
        printf "%s" "$input"
    fi
}

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

init_env_file() {
    cp env.example .env
    if [[ ! -t 0 ]]; then
        log_warn "检测到非交互终端，已按 env.example 生成默认 .env。"
        return
    fi

    log_info "开始引导配置 .env（直接回车使用默认值）"

    local db_host db_port db_name db_user db_password database_url
    db_host="$(prompt_with_default "PostgreSQL 主机" "postgres")"
    db_port="$(prompt_with_default "PostgreSQL 端口" "5432")"
    db_name="$(prompt_with_default "PostgreSQL 数据库名" "saki")"
    db_user="$(prompt_with_default "PostgreSQL 用户名" "postgres")"
    db_password="$(prompt_with_default "PostgreSQL 密码" "postgres")"
    database_url="postgresql://${db_user}:${db_password}@${db_host}:${db_port}/${db_name}"
    set_env_value "DATABASE_URL" "$database_url"

    local secret_default secret_key cors_origins vite_api_base
    secret_default="$(generate_secret_key)"
    secret_key="$(prompt_with_default "SECRET_KEY" "$secret_default")"
    set_env_value "SECRET_KEY" "$secret_key"

    cors_origins="$(prompt_with_default "BACKEND_CORS_ORIGINS(JSON 数组)" "[\"http://localhost\",\"http://localhost:80\",\"http://localhost:3000\",\"http://localhost:5173\"]")"
    set_env_value "BACKEND_CORS_ORIGINS" "$cors_origins"

    vite_api_base="$(prompt_with_default "VITE_API_BASE_URL" "/api/v1")"
    set_env_value "VITE_API_BASE_URL" "$vite_api_base"

    local enable_minio endpoint access_key secret_key_storage minio_secure minio_bucket
    enable_minio="$(prompt_with_default "是否启用内置 MinIO(true/false)" "true")"
    set_env_value "ENABLE_MINIO" "$enable_minio"
    if is_true "$enable_minio"; then
        endpoint="$(prompt_with_default "MINIO_ENDPOINT" "minio:9000")"
        minio_secure="$(prompt_with_default "MINIO_SECURE(true/false)" "false")"
        access_key="$(prompt_with_default "MINIO_ACCESS_KEY" "minioadmin")"
        secret_key_storage="$(prompt_with_default "MINIO_SECRET_KEY" "minioadmin")"
        minio_bucket="$(prompt_with_default "MINIO_BUCKET_NAME" "saki-data")"
    else
        endpoint="$(prompt_with_default "外部对象存储 Endpoint（不带 http/https）" "oss-cn-hangzhou.aliyuncs.com")"
        minio_secure="$(prompt_with_default "MINIO_SECURE(true/false)" "true")"
        access_key="$(prompt_with_default "对象存储 Access Key" "change_me")"
        secret_key_storage="$(prompt_with_default "对象存储 Secret Key" "change_me")"
        minio_bucket="$(prompt_with_default "对象存储 Bucket" "saki-data")"
    fi

    set_env_value "MINIO_ENDPOINT" "$endpoint"
    set_env_value "MINIO_SECURE" "$minio_secure"
    set_env_value "MINIO_ACCESS_KEY" "$access_key"
    set_env_value "MINIO_SECRET_KEY" "$secret_key_storage"
    set_env_value "MINIO_BUCKET_NAME" "$minio_bucket"

    log_info ".env 引导配置完成。"
}

is_true() {
    case "${1,,}" in
        1|true|yes|y|on) return 0 ;;
        *) return 1 ;;
    esac
}

detect_compose_cmd() {
    if docker compose version >/dev/null 2>&1; then
        COMPOSE_CMD=(docker compose)
        return
    fi
    if command -v docker-compose >/dev/null 2>&1; then
        COMPOSE_CMD=(docker-compose)
        return
    fi
    log_error "未找到 Docker Compose，请安装 docker compose 或 docker-compose。"
    exit 1
}

run_compose() {
    "${COMPOSE_CMD[@]}" "${COMPOSE_PROFILE_ARGS[@]}" "$@"
}

build_with_optional_timeout() {
    if command -v timeout >/dev/null 2>&1; then
        timeout 600 "${COMPOSE_CMD[@]}" "${COMPOSE_PROFILE_ARGS[@]}" build
    else
        log_warn "未检测到 timeout，直接执行构建（无超时保护）。"
        "${COMPOSE_CMD[@]}" "${COMPOSE_PROFILE_ARGS[@]}" build
    fi
}

wait_container_ready() {
    local container="$1"
    local timeout_sec="${2:-180}"
    local elapsed=0

    while (( elapsed < timeout_sec )); do
        local exists
        exists="$(docker ps -aq -f "name=^${container}$" || true)"
        if [[ -z "$exists" ]]; then
            sleep 2
            elapsed=$((elapsed + 2))
            continue
        fi

        local status
        status="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$container" 2>/dev/null || true)"
        if [[ "$status" == "healthy" || "$status" == "running" ]]; then
            return 0
        fi
        sleep 2
        elapsed=$((elapsed + 2))
    done

    return 1
}

http_probe() {
    local url="$1"
    if command -v curl >/dev/null 2>&1; then
        curl -fsS "$url" >/dev/null 2>&1
        return $?
    fi
    if command -v wget >/dev/null 2>&1; then
        wget --quiet --tries=1 --spider "$url" >/dev/null 2>&1
        return $?
    fi
    log_warn "主机缺少 curl/wget，跳过 HTTP 探活：$url"
    return 0
}

get_host_ip() {
    if command -v hostname >/dev/null 2>&1; then
        local ip
        ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
        if [[ -n "$ip" ]]; then
            printf "%s" "$ip"
            return
        fi
    fi
    printf "localhost"
}

log_info "开始部署 Saki..."

if ! command -v docker >/dev/null 2>&1; then
    log_error "未找到 Docker，请先安装 Docker。"
    exit 1
fi

if ! docker info >/dev/null 2>&1; then
    log_error "Docker 当前不可用（可能是权限或 daemon 未启动）。"
    printf "建议执行：\n"
    printf "  sudo usermod -aG docker %s\n" "${USER:-$LOGNAME}"
    printf "  然后重新登录，或执行 newgrp docker\n"
    exit 1
fi

if [[ ! -f docker-compose.yml ]]; then
    log_error "当前目录未找到 docker-compose.yml，请在仓库根目录执行本脚本。"
    exit 1
fi

detect_compose_cmd
log_info "使用 Compose 命令：${COMPOSE_CMD[*]}"
COMPOSE_PROFILE_ARGS=()

if [[ ! -f .env ]]; then
    log_info "检测到 .env 缺失，开始引导配置。"
    if [[ ! -f env.example ]]; then
        log_error "未找到 env.example，无法生成 .env。"
        exit 1
    fi
    init_env_file
fi

if grep -q "YOUR_SUPER_SECRET_KEY_CHANGE_ME" .env; then
    log_warn "SECRET_KEY 仍为默认值，生产环境存在安全风险。"
    if [[ -t 0 ]]; then
        read -r -p "是否继续部署? (y/N): " reply
        if [[ ! "$reply" =~ ^[Yy]$ ]]; then
            exit 1
        fi
    else
        log_error "当前非交互终端，且 SECRET_KEY 仍为默认值，拒绝继续部署。"
        exit 1
    fi
fi

DATABASE_URL_VALUE="$(read_env_value DATABASE_URL "")"
case "$DATABASE_URL_VALUE" in
    postgresql://*|postgresql+psycopg://*|postgres://*)
        ;;
    sqlite://*|sqlite+aiosqlite://*)
        log_error "检测到 SQLite 配置，当前版本仅支持 PostgreSQL。请修改 .env 的 DATABASE_URL。"
        exit 1
        ;;
    *)
        log_error "DATABASE_URL 非法：$DATABASE_URL_VALUE"
        log_error "必须使用 postgresql:// 或 postgresql+psycopg://。"
        exit 1
        ;;
esac

ENABLE_MINIO_VALUE="$(read_env_value ENABLE_MINIO true)"
MINIO_ENDPOINT_VALUE="$(read_env_value MINIO_ENDPOINT minio:9000)"
if is_true "$ENABLE_MINIO_VALUE"; then
    COMPOSE_PROFILE_ARGS+=(--profile minio)
    log_info "内置 MinIO：启用（profile=minio）"
else
    log_info "内置 MinIO：关闭（使用外部对象存储）"
    if [[ "$MINIO_ENDPOINT_VALUE" == "minio:9000" || "$MINIO_ENDPOINT_VALUE" == "localhost:9000" ]]; then
        log_warn "ENABLE_MINIO=false，但 MINIO_ENDPOINT 仍是本地默认值：$MINIO_ENDPOINT_VALUE"
        log_warn "请将 MINIO_ENDPOINT 改为外部 OSS/S3 兼容端点。"
    fi
fi

mkdir -p \
    data/postgres \
    saki-api/data \
    saki-api/logs \
    saki-executor/runs \
    saki-executor/cache \
    saki-executor/logs
if is_true "$ENABLE_MINIO_VALUE"; then
    mkdir -p data/minio
fi

log_info "校验 Compose 配置..."
run_compose config >/dev/null

log_info "构建 Docker 镜像..."
if ! build_with_optional_timeout; then
    log_error "镜像构建失败。可先运行 ./configure-docker-mirror.sh 配置镜像加速后重试。"
    exit 1
fi

log_info "启动服务..."
run_compose up -d

log_info "等待核心容器就绪..."
critical_not_ready=0
containers=(saki-postgres saki-redis saki-api saki-web saki-executor)
if is_true "$ENABLE_MINIO_VALUE"; then
    containers=(saki-postgres saki-redis saki-minio saki-api saki-web saki-executor)
fi
for c in "${containers[@]}"; do
    if wait_container_ready "$c" 240; then
        log_info "容器就绪：$c"
    else
        log_warn "容器未在预期时间内就绪：$c"
        if [[ "$c" == "saki-api" || "$c" == "saki-web" ]]; then
            critical_not_ready=1
        fi
    fi
done

if [[ "$critical_not_ready" -eq 1 ]]; then
    log_error "关键容器未就绪（saki-api 或 saki-web），部署失败。"
    log_error "请执行：${COMPOSE_CMD[*]} ${COMPOSE_PROFILE_ARGS[*]} logs --tail=200"
    exit 1
fi

log_info "当前服务状态："
run_compose ps

log_info "执行主机侧健康检查..."
if http_probe "http://localhost:8000/"; then
    log_info "API 服务探活成功"
else
    log_warn "API 服务探活失败，请检查日志：${COMPOSE_CMD[*]} ${COMPOSE_PROFILE_ARGS[*]} logs saki-api"
fi

if http_probe "http://localhost/"; then
    log_info "Web 服务探活成功"
else
    log_warn "Web 服务探活失败，请检查日志：${COMPOSE_CMD[*]} ${COMPOSE_PROFILE_ARGS[*]} logs saki-web"
fi

host_ip="$(get_host_ip)"
printf "\n部署完成。\n"
printf "常用命令:\n"
printf "  查看日志: %s %s logs -f\n" "${COMPOSE_CMD[*]}" "${COMPOSE_PROFILE_ARGS[*]}"
printf "  停止服务: %s %s stop\n" "${COMPOSE_CMD[*]}" "${COMPOSE_PROFILE_ARGS[*]}"
printf "  重启服务: %s %s restart\n" "${COMPOSE_CMD[*]}" "${COMPOSE_PROFILE_ARGS[*]}"
printf "  查看状态: %s %s ps\n" "${COMPOSE_CMD[*]}" "${COMPOSE_PROFILE_ARGS[*]}"
printf "\n访问地址:\n"
printf "  前端: http://%s\n" "$host_ip"
printf "  API: http://%s:8000\n" "$host_ip"
printf "  API 文档: http://%s:8000/docs\n" "$host_ip"
