FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources 2>/dev/null; \
    sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list 2>/dev/null; \
    apt-get update \
    && apt-get install --no-install-recommends -y \
        build-essential \
        ffmpeg \
        fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app/backend
COPY pyproject.toml ./
RUN mkdir -p app \
    && touch app/__init__.py \
    && pip install --no-cache-dir \
        torch==2.12.1 torchvision==0.27.1 \
        --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir ".[ai]"
COPY app ./app

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
