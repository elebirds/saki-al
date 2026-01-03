#!/bin/bash

# Saki 快速部署脚本
# 使用方法: ./deploy.sh

set -e

echo "🚀 开始部署 Saki..."

# 检查 Docker 是否安装
if ! command -v docker &> /dev/null; then
    echo "❌ 错误: 未找到 Docker，请先安装 Docker"
    exit 1
fi

if ! command -v docker compose &> /dev/null && ! command -v docker-compose &> /dev/null; then
    echo "❌ 错误: 未找到 Docker Compose，请先安装 Docker Compose"
    exit 1
fi

# 检测 Docker 权限问题
DOCKER_CMD="docker"
if ! docker info &> /dev/null; then
    echo "⚠️  检测到 Docker 权限问题"
    echo "   尝试使用 sudo..."
    if sudo docker info &> /dev/null; then
        DOCKER_CMD="sudo docker"
        echo "✅ 将使用 sudo 运行 Docker 命令"
    else
        echo ""
        echo "❌ Docker 权限问题，请选择以下解决方案之一："
        echo ""
        echo "方案 1: 将当前用户添加到 docker 组（推荐）"
        echo "   sudo usermod -aG docker $USER"
        echo "   然后注销并重新登录，或运行: newgrp docker"
        echo ""
        echo "方案 2: 使用 sudo 运行此脚本"
        echo "   sudo $0"
        echo ""
        exit 1
    fi
fi

# 根据检测到的命令设置 docker compose 命令
if command -v docker compose &> /dev/null; then
    DOCKER_COMPOSE_CMD="$DOCKER_CMD compose"
else
    DOCKER_COMPOSE_CMD="$DOCKER_CMD-compose"
fi

# 检查环境变量文件
if [ ! -f .env ]; then
    echo "📝 创建环境变量文件..."
    if [ -f env.example ]; then
        cp env.example .env
        echo "⚠️  请编辑 .env 文件，特别是 SECRET_KEY 和 CORS 配置"
        echo "   然后重新运行此脚本"
        exit 1
    else
        echo "❌ 错误: 未找到 env.example 文件"
        exit 1
    fi
fi

# 检查 SECRET_KEY 是否为默认值
if grep -q "YOUR_SUPER_SECRET_KEY_CHANGE_ME" .env; then
    echo "⚠️  警告: SECRET_KEY 仍为默认值，建议在生产环境中更改"
    read -p "是否继续部署? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# 构建镜像
echo "🔨 构建 Docker 镜像..."
if ! timeout 300 $DOCKER_COMPOSE_CMD build; then
    echo ""
    echo "❌ 构建失败，可能是网络超时问题"
    echo ""
    echo "💡 请尝试以下解决方案："
    echo ""
    echo "方案 1: 配置 Docker 镜像加速器（推荐）"
    echo "   ./configure-docker-mirror.sh"
    echo ""
    echo "方案 2: 增加超时时间并重试"
    echo "   $DOCKER_COMPOSE_CMD build --progress=plain"
    echo ""
    echo "方案 3: 检查网络连接"
    echo "   ping registry-1.docker.io"
    echo ""
    exit 1
fi

# 启动服务
echo "🚀 启动服务..."
$DOCKER_COMPOSE_CMD up -d

# 等待服务启动
echo "⏳ 等待服务启动..."
sleep 5

# 检查服务状态
echo "📊 检查服务状态..."
$DOCKER_COMPOSE_CMD ps

# 检查健康状态
echo ""
echo "🏥 检查服务健康状态..."
if $DOCKER_COMPOSE_CMD exec -T saki-api curl -f http://localhost:8000/ > /dev/null 2>&1; then
    echo "✅ API 服务运行正常"
else
    echo "⚠️  API 服务可能未就绪，请检查日志: $DOCKER_COMPOSE_CMD logs saki-api"
fi

if $DOCKER_COMPOSE_CMD exec -T saki-web wget --quiet --tries=1 --spider http://localhost/ > /dev/null 2>&1; then
    echo "✅ Web 服务运行正常"
else
    echo "⚠️  Web 服务可能未就绪，请检查日志: $DOCKER_COMPOSE_CMD logs saki-web"
fi

echo ""
echo "✨ 部署完成！"
echo ""
echo "📝 有用的命令:"
echo "   查看日志: $DOCKER_COMPOSE_CMD logs -f"
echo "   停止服务: $DOCKER_COMPOSE_CMD stop"
echo "   重启服务: $DOCKER_COMPOSE_CMD restart"
echo "   查看状态: $DOCKER_COMPOSE_CMD ps"
echo ""
echo "🌐 访问地址:"
echo "   前端: http://$(hostname -I | awk '{print $1}')"
echo "   API: http://$(hostname -I | awk '{print $1}'):8000"
echo "   API 文档: http://$(hostname -I | awk '{print $1}'):8000/docs"

