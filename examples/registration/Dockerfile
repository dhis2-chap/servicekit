# Registration Demo Dockerfile
FROM ghcr.io/astral-sh/uv:0.9-python3.13-bookworm-slim AS builder

WORKDIR /app

ARG USER=servicekit UID=10001
RUN useradd -u ${UID} -m -s /bin/bash ${USER}

# UV configuration for better build performance
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

# Copy and build parent servicekit project
COPY pyproject.toml uv.lock README.md /servicekit/
COPY src /servicekit/src/
WORKDIR /servicekit
RUN uv build

# Install servicekit wheel and demo dependencies in app directory
WORKDIR /app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv venv && \
    uv pip install /servicekit/dist/*.whl "valkey>=6.1.1"

# Copy demo files
COPY examples/registration/main.py examples/registration/main_custom.py examples/registration/orchestrator.py ./

# Cleanup Python cache files
RUN find /app/.venv -type d -name '__pycache__' -prune -exec rm -rf {} + && \
    find /app/.venv -type f -name '*.py[co]' -delete || true

# ---- runtime ----
FROM python:3.13-slim AS runtime

# OCI labels for container metadata
LABEL org.opencontainers.image.title="Servicekit Registration Demo"
LABEL org.opencontainers.image.description="Service registration demo with orchestrator"
LABEL org.opencontainers.image.vendor="Servicekit"
LABEL org.opencontainers.image.source="https://github.com/dhis2-chap/servicekit"

WORKDIR /app

ARG USER=servicekit UID=10001
RUN useradd -u ${UID} -m -s /bin/bash ${USER}

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get upgrade -y && \
    apt-get install -y --no-install-recommends ca-certificates tini && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Copy venv and application from builder
COPY --from=builder --chown=${USER}:${USER} /app/.venv /app/.venv
COPY --from=builder --chown=${USER}:${USER} /app/main.py /app/main.py
COPY --from=builder --chown=${USER}:${USER} /app/main_custom.py /app/main_custom.py
COPY --from=builder --chown=${USER}:${USER} /app/orchestrator.py /app/orchestrator.py

ENV VIRTUAL_ENV=/app/.venv
ENV PATH=/app/.venv/bin:${PATH}
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONFAULTHANDLER=1

# Server configuration
ENV PORT=8000
ENV TIMEOUT=60
ENV GRACEFUL_TIMEOUT=30
ENV KEEPALIVE=5
ENV FORWARDED_ALLOW_IPS="*"

# Worker configuration
ENV MAX_REQUESTS=1000
ENV MAX_REQUESTS_JITTER=200

# Logging configuration
ENV LOG_FORMAT=json
ENV LOG_LEVEL=INFO

USER ${USER}
EXPOSE 8000

# Health check to verify the API is responding
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:${PORT}/health').read()" || exit 1

ENTRYPOINT ["/usr/bin/tini", "--"]
# Use uvicorn directly for reliable lifespan execution (required for registration)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

# ---- orchestrator ----
FROM runtime AS orchestrator

# Override healthcheck for orchestrator (port 9000)
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:9000/health').read()" || exit 1

EXPOSE 9000

# Run orchestrator with uvicorn (single worker for in-memory registry)
CMD ["uvicorn", "orchestrator:app", "--host", "0.0.0.0", "--port", "9000"]
