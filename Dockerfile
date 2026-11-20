# 只要解释器里有 fastapi / uvicorn / langgraph 就能跑
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml README.md LICENSE config.toml run.py ./
COPY src ./src
# 就业示例的数据表要带上，否则 /api/ask 在容器里找不到默认 CSV
COPY examples ./examples

RUN pip install --no-cache-dir . \
    && mkdir -p runs

EXPOSE 8765

# 需要模型 key：docker run -e AUTOFLUX_API_KEY=sk-... -p 8765:8765 autoflux
CMD ["autoflux", "serve", "--host", "0.0.0.0", "--port", "8765"]
