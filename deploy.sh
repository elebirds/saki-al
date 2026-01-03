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
docker compose build

# 启动服务
echo "🚀 启动服务..."
docker compose up -d

# 等待服务启动
echo "⏳ 等待服务启动..."
sleep 5

# 检查服务状态
echo "📊 检查服务状态..."
docker compose ps

# 检查健康状态
echo ""
echo "🏥 检查服务健康状态..."
if docker compose exec -T saki-api curl -f http://localhost:8000/ > /dev/null 2>&1; then
    echo "✅ API 服务运行正常"
else
    echo "⚠️  API 服务可能未就绪，请检查日志: docker compose logs saki-api"
fi

if docker compose exec -T saki-web wget --quiet --tries=1 --spider http://localhost/ > /dev/null 2>&1; then
    echo "✅ Web 服务运行正常"
else
    echo "⚠️  Web 服务可能未就绪，请检查日志: docker compose logs saki-web"
fi

echo ""
echo "✨ 部署完成！"
echo ""
echo "📝 有用的命令:"
echo "   查看日志: docker compose logs -f"
echo "   停止服务: docker compose stop"
echo "   重启服务: docker compose restart"
echo "   查看状态: docker compose ps"
echo ""
echo "🌐 访问地址:"
echo "   前端: http://$(hostname -I | awk '{print $1}')"
echo "   API: http://$(hostname -I | awk '{print $1}'):8000"
echo "   API 文档: http://$(hostname -I | awk '{print $1}'):8000/docs"

