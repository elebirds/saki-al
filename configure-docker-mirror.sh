#!/bin/bash

# Docker 镜像加速器配置脚本
# 用于配置国内 Docker 镜像源，解决拉取镜像超时问题

set -e

echo "🔧 配置 Docker 镜像加速器..."

# 检查是否以 root 权限运行
if [ "$EUID" -ne 0 ]; then 
    echo "⚠️  此脚本需要 root 权限，将使用 sudo"
    SUDO_CMD="sudo"
else
    SUDO_CMD=""
fi

# Docker daemon 配置文件路径
DOCKER_DAEMON_JSON="/etc/docker/daemon.json"
DOCKER_DAEMON_JSON_BACKUP="/etc/docker/daemon.json.backup.$(date +%Y%m%d_%H%M%S)"

# 国内常用的 Docker 镜像加速器
MIRRORS=(
    "https://docker.mirrors.ustc.edu.cn"
    "https://hub-mirror.c.163.com"
    "https://mirror.baidubce.com"
    "https://registry.docker-cn.com"
)

echo ""
echo "可用的镜像加速器："
for i in "${!MIRRORS[@]}"; do
    echo "  $((i+1)). ${MIRRORS[$i]}"
done
echo "  5. 使用多个镜像源（推荐）"
echo "  6. 自定义镜像源"
echo ""

read -p "请选择镜像加速器 (1-6，默认 5): " choice
choice=${choice:-5}

case $choice in
    1|2|3|4)
        selected_mirror="${MIRRORS[$((choice-1))]}"
        registry_mirrors="[\"$selected_mirror\"]"
        ;;
    5)
        # 使用多个镜像源
        registry_mirrors="["
        for i in "${!MIRRORS[@]}"; do
            if [ $i -gt 0 ]; then
                registry_mirrors+=", "
            fi
            registry_mirrors+="\"${MIRRORS[$i]}\""
        done
        registry_mirrors+="]"
        ;;
    6)
        read -p "请输入自定义镜像源 URL: " custom_mirror
        registry_mirrors="[\"$custom_mirror\"]"
        ;;
    *)
        echo "❌ 无效的选择"
        exit 1
        ;;
esac

# 备份现有配置
if [ -f "$DOCKER_DAEMON_JSON" ]; then
    echo "📋 备份现有配置到 $DOCKER_DAEMON_JSON_BACKUP"
    $SUDO_CMD cp "$DOCKER_DAEMON_JSON" "$DOCKER_DAEMON_JSON_BACKUP"
fi

# 创建配置目录
$SUDO_CMD mkdir -p /etc/docker

# 读取现有配置或创建新配置
if [ -f "$DOCKER_DAEMON_JSON" ]; then
    # 使用 jq 更新配置（如果可用）
    if command -v jq &> /dev/null; then
        echo "📝 更新现有配置..."
        $SUDO_CMD jq ". + {\"registry-mirrors\": $registry_mirrors}" "$DOCKER_DAEMON_JSON" > /tmp/daemon.json.tmp
        $SUDO_CMD mv /tmp/daemon.json.tmp "$DOCKER_DAEMON_JSON"
    else
        # 如果没有 jq，使用 Python 更新配置
        if command -v python3 &> /dev/null; then
            echo "📝 使用 Python 更新现有配置..."
            $SUDO_CMD python3 <<PYTHON_SCRIPT
import json
import sys

try:
    with open("$DOCKER_DAEMON_JSON", 'r') as f:
        config = json.load(f)
except:
    config = {}

config["registry-mirrors"] = $registry_mirrors

with open("$DOCKER_DAEMON_JSON", 'w') as f:
    json.dump(config, f, indent=2)
PYTHON_SCRIPT
        else
            # 如果都没有，创建新配置
            echo "⚠️  未找到 jq 或 python3，将创建新配置（原配置已备份）"
            $SUDO_CMD tee "$DOCKER_DAEMON_JSON" > /dev/null <<EOF
{
  "registry-mirrors": $registry_mirrors
}
EOF
        fi
    fi
else
    # 创建新配置
    echo "📝 创建新配置..."
    $SUDO_CMD tee "$DOCKER_DAEMON_JSON" > /dev/null <<EOF
{
  "registry-mirrors": $registry_mirrors
}
EOF
fi

# 重启 Docker 服务
echo "🔄 重启 Docker 服务..."
$SUDO_CMD systemctl daemon-reload
$SUDO_CMD systemctl restart docker

# 等待 Docker 启动
sleep 2

# 验证配置
echo ""
echo "✅ 配置完成！"
echo ""
echo "📋 当前 Docker 配置："
if command -v python3 &> /dev/null; then
    $SUDO_CMD cat "$DOCKER_DAEMON_JSON" | python3 -m json.tool 2>/dev/null || $SUDO_CMD cat "$DOCKER_DAEMON_JSON"
elif command -v jq &> /dev/null; then
    $SUDO_CMD cat "$DOCKER_DAEMON_JSON" | jq . 2>/dev/null || $SUDO_CMD cat "$DOCKER_DAEMON_JSON"
else
    $SUDO_CMD cat "$DOCKER_DAEMON_JSON"
fi

echo ""
echo "🧪 测试镜像拉取..."
if $SUDO_CMD docker pull alpine:latest > /dev/null 2>&1; then
    echo "✅ 镜像拉取测试成功！"
    $SUDO_CMD docker rmi alpine:latest > /dev/null 2>&1
else
    echo "⚠️  镜像拉取测试失败，请检查网络连接和镜像源配置"
fi

echo ""
echo "✨ 配置完成！现在可以重新运行部署脚本了。"

