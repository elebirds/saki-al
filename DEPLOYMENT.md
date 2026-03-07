# Saki 部署指南

本文档介绍如何将 Saki API 和 Web 前端部署到服务器上。

## 目录

- [前置要求](#前置要求)
- [快速开始](#快速开始)
- [详细部署步骤](#详细部署步骤)
- [环境变量配置](#环境变量配置)
- [生产环境优化](#生产环境优化)
- [故障排查](#故障排查)

## 前置要求

### 服务器要求

- **操作系统**: Linux (推荐 Ubuntu 20.04+ 或 CentOS 7+)
- **Docker**: 20.10+
- **Docker Compose**: 1.29+
- **内存**: 至少 2GB RAM
- **磁盘空间**: 至少 10GB 可用空间

### 安装 Docker 和 Docker Compose

如果服务器上还没有安装 Docker，请按照以下步骤安装：

#### Ubuntu/Debian

```bash
# 更新包索引
sudo apt-get update

# 安装必要的依赖
sudo apt-get install -y \
    ca-certificates \
    curl \
    gnupg \
    lsb-release

# 添加 Docker 官方 GPG 密钥
sudo mkdir -p /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg

# 设置 Docker 仓库
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# 安装 Docker Engine
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

# 启动 Docker
sudo systemctl start docker
sudo systemctl enable docker

# 验证安装
sudo docker --version
sudo docker compose version

# 配置 Docker 权限（可选，但推荐）
# 将当前用户添加到 docker 组，这样就不需要每次都使用 sudo
sudo usermod -aG docker $USER
# 注意：需要注销并重新登录，或运行以下命令使更改生效
newgrp docker

# 验证权限配置
docker --version
docker compose version
```

#### CentOS/RHEL

```bash
# 安装必要的工具
sudo yum install -y yum-utils

# 添加 Docker 仓库
sudo yum-config-manager \
    --add-repo \
    https://download.docker.com/linux/centos/docker-ce.repo

# 安装 Docker Engine
sudo yum install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

# 启动 Docker
sudo systemctl start docker
sudo systemctl enable docker

# 验证安装
sudo docker --version
sudo docker compose version

# 配置 Docker 权限（可选，但推荐）
# 将当前用户添加到 docker 组，这样就不需要每次都使用 sudo
sudo usermod -aG docker $USER
# 注意：需要注销并重新登录，或运行以下命令使更改生效
newgrp docker

# 验证权限配置
docker --version
docker compose version
```

## 快速开始

### 0. 配置 Docker 镜像加速器（推荐，特别是中国大陆用户）

如果遇到镜像拉取超时问题，请先配置镜像加速器：

```bash
# 运行镜像加速器配置脚本
./configure-docker-mirror.sh

# 或手动配置
sudo mkdir -p /etc/docker
sudo tee /etc/docker/daemon.json <<-'EOF'
{
  "registry-mirrors": [
    "https://docker.mirrors.ustc.edu.cn",
    "https://hub-mirror.c.163.com",
    "https://mirror.baidubce.com"
  ]
}
EOF
sudo systemctl daemon-reload
sudo systemctl restart docker
```

### 1. 上传代码到服务器

将项目代码上传到服务器，可以使用 `git clone` 或 `scp`：

```bash
# 使用 git
git clone <your-repo-url> /opt/saki
cd /opt/saki

# 或使用 scp
scp -r /path/to/saki user@server:/opt/saki
```

### 2. 配置环境变量

```bash
# 复制环境变量示例文件
cp env.example .env

# 编辑环境变量（重要：修改 SECRET_KEY 和 CORS 配置）
nano .env
```

**必须修改的配置项：**

- `SECRET_KEY`: 生成一个安全的密钥
  ```bash
  openssl rand -hex 32
  ```
- `BACKEND_CORS_ORIGINS`: 设置为你的前端域名
  ```bash
  BACKEND_CORS_ORIGINS=["https://yourdomain.com"]
  ```
- `VITE_API_BASE_URL`: 如果使用 nginx 代理，设置为 `/api/v1`
- `ENABLE_MINIO`:  
  - `true`：启用内置 MinIO（需要使用 `--profile minio` 启动）  
  - `false`：不启用内置 MinIO，直接连接外部 OSS/S3 兼容对象存储
- `MINIO_ENDPOINT`: 当 `ENABLE_MINIO=false` 时，改成外部对象存储 endpoint（不带 `http://` / `https://`）

### 3. 构建和启动服务

```bash
# 方案 A：启用内置 MinIO（默认推荐本地部署）
docker compose --profile minio up -d --build

# 方案 B：不启用内置 MinIO（使用外部 OSS/S3）
docker compose up -d --build

# 查看服务状态
docker compose --profile minio ps   # 方案 A
# 或
docker compose ps                    # 方案 B

# 查看日志
docker compose --profile minio logs -f   # 方案 A
# 或
docker compose logs -f                   # 方案 B
```

### 4. 访问应用

- **前端**: http://your-server-ip 或 http://your-domain
- **API 文档**: http://your-server-ip:8000/docs

## 详细部署步骤

### 步骤 1: 准备服务器

1. **更新系统**
   ```bash
   sudo apt-get update && sudo apt-get upgrade -y
   ```

2. **安装必要的工具**
   ```bash
   sudo apt-get install -y git curl wget
   ```

3. **配置防火墙** (如果使用 UFW)
   ```bash
   sudo ufw allow 22/tcp    # SSH
   sudo ufw allow 80/tcp    # HTTP
   sudo ufw allow 443/tcp   # HTTPS (如果使用 SSL)
   sudo ufw enable
   ```

### 步骤 2: 克隆或上传代码

```bash
# 创建项目目录
sudo mkdir -p /opt/saki
sudo chown $USER:$USER /opt/saki

# 克隆代码
cd /opt/saki
git clone <your-repo-url> .

# 或上传代码后解压
```

### 步骤 3: 配置环境变量

```bash
cd /opt/saki

# 复制并编辑环境变量文件
cp env.example .env
nano .env
```

**重要配置说明：**

```bash
# 生成安全的 SECRET_KEY
SECRET_KEY=$(openssl rand -hex 32)
echo "SECRET_KEY=$SECRET_KEY" >> .env

# 设置 CORS（替换为你的实际域名）
echo 'BACKEND_CORS_ORIGINS=["https://yourdomain.com","https://www.yourdomain.com"]' >> .env

# 如果使用 nginx 代理，API 地址使用相对路径
echo "VITE_API_BASE_URL=/api/v1" >> .env
```

### 步骤 4: 构建 Docker 镜像

```bash
# 构建所有服务
docker compose build

# 或单独构建
docker compose build saki-api
docker compose build saki-web
```

### 步骤 5: 启动服务

```bash
# 启动所有服务（后台运行）
docker compose up -d

# 查看服务状态
docker compose ps

# 查看日志
docker compose logs -f saki-api
docker compose logs -f saki-web
```

### 步骤 6: 验证部署

1. **检查服务健康状态**
   ```bash
   docker compose ps
   # 所有服务应该显示 "Up" 状态
   ```

2. **测试 API**
   ```bash
   curl http://localhost:8000/
   # 应该返回 JSON 响应
   ```

3. **测试前端**
   ```bash
   curl http://localhost/
   # 应该返回 HTML 页面
   ```

## 环境变量配置

### 后端环境变量 (saki-api)

| 变量名 | 说明 | 默认值 | 必需 |
|--------|------|--------|------|
| `DATABASE_URL` | 数据库连接字符串（仅 PostgreSQL） | `postgresql://postgres:postgres@postgres:5432/saki` | **是** |
| `SECRET_KEY` | JWT 密钥 | `YOUR_SUPER_SECRET_KEY...` | **是** |
| `BACKEND_CORS_ORIGINS` | CORS 允许的源 | `["http://localhost:3000"]` | **是** |
| `UPLOAD_DIR` | 上传文件目录 | `./data/uploads` | 否 |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Token 过期时间（分钟） | `30` | 否 |

### 前端环境变量 (saki-web)

| 变量名 | 说明 | 默认值 | 必需 |
|--------|------|--------|------|
| `VITE_API_BASE_URL` | API 基础地址 | `http://localhost:8000/api/v1` | **是** |

**注意**: Vite 环境变量必须以 `VITE_` 开头才能在构建时使用。

## 生产环境优化

### 1. PostgreSQL 数据库配置（必选）

当前版本仅支持 PostgreSQL，建议在部署前明确数据库账号与连接串：

```yaml
# 在 docker-compose.yml 中添加 PostgreSQL 服务
services:
  postgres:
    image: postgres:15-alpine
    environment:
      POSTGRES_DB: saki_db
      POSTGRES_USER: saki_user
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    networks:
      - saki-network

volumes:
  postgres_data:
```

然后在 `.env` 中设置：

```bash
DATABASE_URL=postgresql://saki_user:${POSTGRES_PASSWORD}@postgres:5432/saki_db
```

### 2. 配置 HTTPS (使用 Nginx 反向代理)

#### 安装 Certbot (Let's Encrypt)

```bash
sudo apt-get install -y certbot python3-certbot-nginx
```

#### 配置 Nginx (在宿主机上)

创建 `/etc/nginx/sites-available/saki`:

```nginx
server {
    listen 80;
    server_name yourdomain.com www.yourdomain.com;

    location / {
        proxy_pass http://localhost:80;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

启用配置并获取 SSL 证书:

```bash
sudo ln -s /etc/nginx/sites-available/saki /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
sudo certbot --nginx -d yourdomain.com -d www.yourdomain.com
```

### 3. 数据备份

#### 备份数据库（PostgreSQL）

```bash
docker compose exec postgres pg_dump -U saki_user saki_db > backup_$(date +%Y%m%d).sql
```

#### 备份上传文件

```bash
tar -czf uploads_backup_$(date +%Y%m%d).tar.gz saki-api/data/uploads/
```

### 4. 监控和日志

#### 查看日志

```bash
# 查看所有服务日志
docker compose logs -f

# 查看特定服务日志
docker compose logs -f saki-api
docker compose logs -f saki-web

# 查看最近 100 行日志
docker compose logs --tail=100 saki-api
```

#### 设置日志轮转

创建 `/etc/docker/daemon.json`:

```json
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "10m",
    "max-file": "3"
  }
}
```

重启 Docker:

```bash
sudo systemctl restart docker
```

### 5. 性能优化

#### 增加资源限制

在 `docker-compose.yml` 中添加资源限制:

```yaml
services:
  saki-api:
    deploy:
      resources:
        limits:
          cpus: '2'
          memory: 2G
        reservations:
          cpus: '1'
          memory: 1G
```

## 故障排查

### 常见问题

#### 1. Docker 权限问题

如果遇到 `permission denied while trying to connect to the Docker daemon socket` 错误：

**解决方案 1: 将用户添加到 docker 组（推荐）**

```bash
# 将当前用户添加到 docker 组
sudo usermod -aG docker $USER

# 使更改生效（选择以下方式之一）
# 方式 1: 注销并重新登录
# 方式 2: 运行以下命令
newgrp docker

# 验证权限
docker --version
docker ps
```

**解决方案 2: 使用 sudo**

```bash
# 使用 sudo 运行部署脚本
sudo ./deploy.sh

# 或使用 sudo 运行 docker compose 命令
sudo docker compose up -d
```

**注意**: 如果使用 sudo，确保后续所有 docker 命令都使用 sudo，否则可能遇到权限问题。

#### 2. Docker 镜像拉取超时

如果遇到 `DeadlineExceeded` 或 `i/o timeout` 错误：

**解决方案：配置 Docker 镜像加速器**

```bash
# 使用配置脚本（推荐）
./configure-docker-mirror.sh

# 或手动配置
sudo mkdir -p /etc/docker
sudo tee /etc/docker/daemon.json <<-'EOF'
{
  "registry-mirrors": [
    "https://docker.mirrors.ustc.edu.cn",
    "https://hub-mirror.c.163.com",
    "https://mirror.baidubce.com"
  ]
}
EOF
sudo systemctl daemon-reload
sudo systemctl restart docker

# 验证配置
docker info | grep -A 10 "Registry Mirrors"
```

**其他解决方案：**

```bash
# 增加超时时间重试
docker compose build --progress=plain

# 或使用代理（如果有）
export HTTP_PROXY=http://your-proxy:port
export HTTPS_PROXY=http://your-proxy:port
docker compose build
```

#### 3. 服务无法启动

```bash
# 查看详细错误信息
docker compose logs saki-api
docker compose logs saki-web

# 检查端口是否被占用
sudo netstat -tulpn | grep :8000
sudo netstat -tulpn | grep :80

# 重启服务
docker compose restart
```

#### 4. 前端无法连接后端

- 检查 `VITE_API_BASE_URL` 配置是否正确
- 检查 CORS 配置是否包含前端域名
- 检查防火墙设置

#### 5. 数据库连接失败

```bash
# 检查数据库文件权限
ls -la saki-api/saki.db
ls -la saki-api/data/

# 修复权限
sudo chown -R $USER:$USER saki-api/data
sudo chown -R $USER:$USER saki-api/saki.db
```

#### 6. 上传文件失败

```bash
# 检查上传目录权限
ls -la saki-api/data/uploads/

# 修复权限
sudo chmod -R 755 saki-api/data/uploads/
```

#### 7. 内存不足

```bash
# 查看容器资源使用
docker stats

# 清理未使用的资源
docker system prune -a
```

### 调试命令

```bash
# 进入容器内部
docker compose exec saki-api bash
docker compose exec saki-web sh

# 查看环境变量
docker compose exec saki-api env

# 测试 API 连接
docker compose exec saki-api curl http://localhost:8000/

# 查看容器网络
docker network inspect saki_saki-network
```

## 更新部署

当需要更新代码时：

```bash
# 1. 拉取最新代码
git pull

# 2. 重新构建镜像
docker compose build

# 3. 重启服务（零停机时间）
docker compose up -d

# 或强制重新创建容器
docker compose up -d --force-recreate
```

## 停止和清理

```bash
# 停止服务
docker compose stop

# 停止并删除容器
docker compose down

# 停止并删除容器、网络、卷
docker compose down -v
```

## 安全建议

1. **更改默认密钥**: 务必在生产环境中更改 `SECRET_KEY`
2. **配置防火墙**: 只开放必要的端口
3. **使用 HTTPS**: 生产环境必须使用 HTTPS
4. **定期更新**: 保持 Docker 镜像和系统更新
5. **备份数据**: 定期备份数据库和上传文件
6. **限制访问**: 使用防火墙限制 API 端口的访问（如果不需要直接访问）

## 支持

如果遇到问题，请查看：
- 项目 README.md
- Docker 日志: `docker compose logs`
- GitHub Issues

---

**祝部署顺利！** 🚀
