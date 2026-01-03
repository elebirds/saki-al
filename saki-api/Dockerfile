# saki-api Dockerfile
FROM python:3.14-slim

# 设置工作目录
WORKDIR /app

# 2. 设置环境变量，防止 apt 交互式弹窗
ENV DEBIAN_FRONTEND=noninteractive

# 3. 配置腾讯云 apt 镜像加速并安装系统依赖 (解决 libgl 问题)
RUN sed -i 's/deb.debian.org/mirrors.tencentyun.com/g' /etc/apt/sources.list.d/debian.sources && \
    apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    libgl1 \
    libglib2.0-0 \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# 安装 uv (Python 包管理器)
RUN pip install --no-cache-dir uv

# 复制项目文件
COPY pyproject.toml uv.lock README.md ./
COPY src ./src

# 安装依赖
RUN uv sync --frozen --no-dev

# 创建数据目录
RUN mkdir -p /app/data/uploads

# 暴露端口
EXPOSE 8000

# 启动命令
CMD ["uv", "run", "uvicorn", "saki_api.main:app", "--host", "0.0.0.0", "--port", "8000"]

