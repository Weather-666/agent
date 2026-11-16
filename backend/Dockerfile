FROM python:3.11-slim
ARG PIP_INDEX_URL=https://pypi.org/simple

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DEFAULT_TIMEOUT=120

WORKDIR /app

COPY pyproject.toml README.md ./
RUN pip install --no-cache-dir --no-build-isolation --index-url "${PIP_INDEX_URL}" .

COPY app ./app
COPY infra ./infra
COPY runtime ./runtime
COPY scripts ./scripts
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

EXPOSE 15000

ENTRYPOINT ["/docker-entrypoint.sh"]
