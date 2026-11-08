# FastAPI (Python 3.11)
# Build from repository root:
#   docker build -f ml/serving/Dockerfile -t ml-serving:dev .

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

# Copy shared preprocessing/schema package (ml/common), MLOps pipeline + evaluation
# artifacts (ml/pipeline, ml/training/results, ml/training/package) for K8s/CI seeder jobs,
# and the serving application (ml/serving)
COPY ml/__init__.py ./ml/__init__.py
COPY ml/common ./ml/common
COPY ml/pipeline ./ml/pipeline
COPY ml/training/results ./ml/training/results
COPY ml/training/package ./ml/training/package
COPY ml/serving ./ml/serving
COPY docs/api/ml-predict-openapi.yaml ./docs/api/ml-predict-openapi.yaml

RUN mkdir -p /app/ml/data/processed && chown -R mluser:mluser /app

# Run as non-root user
USER 1001

# FastAPI default port
EXPOSE 8000

# Container-level liveness healthcheck using Python stdlib urllib
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=3)"]

# Start Uvicorn production server
CMD ["uvicorn", "ml.serving.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
