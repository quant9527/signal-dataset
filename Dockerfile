# signalview Streamlit 应用，对应 ops/app/compose.yaml 中的 signalview 服务（端口 8501）
FROM python:3.12-slim

WORKDIR /app

# 安装依赖（先只复制 pyproject.toml 以利用层缓存）
COPY pyproject.toml .
RUN pip install --no-cache-dir .

# 应用代码与默认配置（.streamlit 可通过 volume 挂载覆盖，如 secrets.toml）
COPY . .

EXPOSE 8501
CMD ["streamlit", "run", "streamlit_app.py", "--server.port=8501", "--server.address=0.0.0.0", "--server.enableStaticServing=true"]
