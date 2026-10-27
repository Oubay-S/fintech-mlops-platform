# ------------------------------------------------------------------------------
# FastAPI ML Serving (Python 3.11) — Role 5
# Build from repository root:
#   docker build -f ml/serving/Dockerfile -t ml-serving:dev .
# ------------------------------------------------------------------------------
FROM python:3.11-slim AS runner

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

# Create dedicated non-root user (UID 1001)
RUN useradd -u 1001 -m -s /bin/bash mluser

# Install pinned Python dependencies first for optimal Docker layer caching
COPY ml/serving/requirements.txt ./ml/serving/requirements.txt
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r ml/serving/requirements.txt

# Copy shared preprocessing/schema package (ml/common) and serving application (ml/serving)
COPY ml/__init__.py ./ml/__init__.py
COPY ml/common ./ml/common
COPY ml/serving ./ml/serving
COPY docs/api/ml-predict-openapi.yaml ./docs/api/ml-predict-openapi.yaml

RUN chown -R mluser:mluser /app

# Run as non-root user
USER 1001

# FastAPI default port
EXPOSE 8000

# Container-level liveness healthcheck using Python stdlib urllib (no curl required)
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=3)"]

# Start Uvicorn production server
CMD ["uvicorn", "ml.serving.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
