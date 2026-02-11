#!/usr/bin/env bash

# Docker 镜像加速器配置脚本（Linux）
# 使用方法: ./configure-docker-mirror.sh

set -Eeuo pipefail

log_info() { printf "[INFO] %s\n" "$*"; }
log_warn() { printf "[WARN] %s\n" "$*" >&2; }
log_error() { printf "[ERROR] %s\n" "$*" >&2; }

if [[ "${OSTYPE:-}" != linux* ]]; then
    log_error "当前脚本仅支持 Linux。"
    exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
    log_error "未找到 Docker，请先安装 Docker。"
    exit 1
fi

SUDO=""
if [[ "$(id -u)" -ne 0 ]]; then
    if command -v sudo >/dev/null 2>&1; then
        SUDO="sudo"
    else
        log_error "需要 root 权限写入 /etc/docker/daemon.json，请以 root 执行或安装 sudo。"
        exit 1
    fi
fi

TMP_FILE="$(mktemp)"
cat >"$TMP_FILE" <<'EOF'
{
  "registry-mirrors": [
    "https://docker.mirrors.ustc.edu.cn",
    "https://hub-mirror.c.163.com",
    "https://mirror.baidubce.com"
  ]
}
EOF

$SUDO mkdir -p /etc/docker
if [[ -f /etc/docker/daemon.json ]]; then
    backup="/etc/docker/daemon.json.bak.$(date +%Y%m%d%H%M%S)"
    log_info "检测到已有 daemon.json，正在备份到 $backup"
    $SUDO cp /etc/docker/daemon.json "$backup"
fi

log_info "写入镜像加速配置到 /etc/docker/daemon.json"
$SUDO cp "$TMP_FILE" /etc/docker/daemon.json
rm -f "$TMP_FILE"

if command -v systemctl >/dev/null 2>&1; then
    $SUDO systemctl daemon-reload || true
    $SUDO systemctl restart docker
else
    $SUDO service docker restart
fi

log_info "当前 Docker 镜像加速配置："
docker info 2>/dev/null | sed -n '/Registry Mirrors/,+4p' || log_warn "未能读取 docker info，请手动检查服务状态。"

log_info "镜像加速配置完成。"
