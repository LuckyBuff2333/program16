# 多阶段构建：减小最终镜像体积
FROM python:3.12-slim AS builder

WORKDIR /build

# 安装编译依赖（仅构建阶段需要）
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# 过滤掉版本声明行（Python >= 3.12），只保留可 pip install 的包
RUN grep -v '^Python' requirements.txt > pip_reqs.txt \
    && pip install --no-cache-dir --prefix=/install -r pip_reqs.txt

# ---- 运行阶段 ----
FROM python:3.12-slim

LABEL maintainer="Bug Doc Tool"

# 运行时系统依赖：OpenCV 和部分 Python 包需要的共享库
RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 从构建阶段复制已安装的 Python 包
COPY --from=builder /install /usr/local

WORKDIR /app

# 复制项目源码（.dockerignore 排除无关文件）
COPY src/ ./src/
COPY requirements.txt ./

# 创建持久化目录挂载点
RUN mkdir -p config data docs reports logs

# 声明挂载卷：配置文件 + 运行时数据
VOLUME ["/app/config", "/app/data", "/app/docs", "/app/reports", "/app/logs"]

# Web 服务端口
EXPOSE 8060

# 环境变量：Python 无缓冲输出 + UTF-8 编码
ENV PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    TZ=Asia/Shanghai

# 健康检查：探测 Web 服务根路径
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -sf http://127.0.0.1:8060/ || exit 1

# 入口脚本：初始化数据库 + 启动 uvicorn（绑定 0.0.0.0 以支持外部访问）
CMD ["sh", "-c", "python -c 'from src import db; db.init_db()' && exec uvicorn src.web.server:app --host 0.0.0.0 --port 8060 --log-level info"]
