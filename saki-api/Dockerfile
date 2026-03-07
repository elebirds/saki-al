# saki-api Dockerfile
FROM python:3.14-slim

# 设置工作目录
WORKDIR /app

# 安装系统依赖 (解决 libgl 问题)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    libgl1 \
    libglib2.0-0 \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# 安装 uv (Python 包管理器)
RUN pip install --no-cache-dir uv

# 复制 saki-ir 本地依赖 (必须在 pyproject.toml 之前复制)
COPY shared/saki-ir/proto /tmp/saki-ir/proto
COPY shared/saki-ir/python /tmp/saki-ir/python
COPY shared/saki-ir/python/pyproject.toml /tmp/saki-ir/python/

# 复制项目文件
COPY saki-api/pyproject.toml ./pyproject.toml
COPY saki-api/uv.lock ./uv.lock
COPY saki-api/README.md ./README.md
COPY saki-api/src ./src

# 修改 pyproject.toml 中的本地依赖路径为 Docker 内路径
# Python 3.14 的 sed 命令语法
RUN if grep -q "../shared/saki-ir/python" pyproject.toml; then \
        sed -i 's|"../shared/saki-ir/python"|"/tmp/saki-ir/python"|' pyproject.toml; \
    fi

# 安装依赖 (不使用 --frozen，因为本地路径已修改)
RUN uv sync --no-dev

# 创建数据目录
RUN mkdir -p /app/data/uploads

# 复制 entrypoint 脚本
COPY saki-api/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# 暴露端口
EXPOSE 8000

# 使用 entrypoint 脚本
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]

# 启动命令
CMD ["uv", "run", "uvicorn", "saki_api.main:app", "--host", "0.0.0.0", "--port", "8000"]

