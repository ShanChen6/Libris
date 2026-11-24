# libris-ai (FastAPI + bge-m3 + bge-reranker-v2-m3), chạy trên CPU.
#   docker build -t libris-ai libris-ai                                   # tải mô hình khi khởi động
#   docker build -t libris-ai --build-arg BAKE_MODELS=true libris-ai      # đóng gói sẵn mô hình (~+4,5 GB)
# Cần ~5 GB RAM khi bật reranker, ~2,5 GB khi RERANKER_ENABLED=false (xem docs/DEPLOY.md).
FROM python:3.12-slim

# OCR bản scan (Tesseract tiếng Việt) và đọc file .doc (catdoc) – dùng cho tải văn bản và phân tích hợp đồng
# Mạng đi qua proxy có CA riêng: build với --secret id=ca_cert,src=<file CA>; không có thì bỏ qua
ARG CA=/run/secrets/ca_cert
RUN --mount=type=secret,id=ca_cert,required=false,mode=0444 \
    sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources \
    && if [ -f $CA ]; then echo "Acquire::https::CaInfo \"$CA\";" > /etc/apt/apt.conf.d/99ca; fi \
    && apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-vie catdoc \
    && rm -rf /var/lib/apt/lists/* /etc/apt/apt.conf.d/99ca

RUN --mount=type=secret,id=ca_cert,required=false,mode=0444 \
    PIP_CERT=$([ -f $CA ] && echo $CA) pip install --no-cache-dir uv==0.11.*

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_NO_CACHE=1 UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH=/app/.venv/bin:$PATH HF_HOME=/models PYTHONUNBUFFERED=1

# Cài thư viện trước (lớp cache riêng, chỉ build lại khi lockfile đổi); PyTorch bản CPU
COPY pyproject.toml uv.lock ./
RUN --mount=type=secret,id=ca_cert,required=false,mode=0444 \
    SSL_CERT_FILE=$([ -f $CA ] && echo $CA) uv sync --frozen --no-dev --no-install-project

ARG BAKE_MODELS=false
RUN --mount=type=secret,id=ca_cert,required=false,mode=0444 \
    if [ -f $CA ]; then export REQUESTS_CA_BUNDLE=$CA SSL_CERT_FILE=$CA; fi; \
    if [ "$BAKE_MODELS" = "true" ]; then \
      python -c "from huggingface_hub import snapshot_download as d; d('BAAI/bge-m3'); d('BAAI/bge-reranker-v2-m3')"; \
    fi

COPY app ./app
COPY crawler ./crawler

RUN useradd --create-home --uid 10001 libris && mkdir -p /models /app/data/uploads \
    && chown -R libris /models /app/data
USER libris

# Tải sẵn mô hình khi khởi động để request đầu tiên không phải chờ
ENV EMBEDDING_PRELOAD=true RERANKER_PRELOAD=true PORT=8000
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=300s \
    CMD python -c "import os,urllib.request; urllib.request.urlopen(f'http://localhost:{os.environ[\"PORT\"]}/health', timeout=4)"
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers"]
