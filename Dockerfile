FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# CPU-only torch first (avoids multi-GB CUDA wheels), then the app's dependencies.
RUN pip install torch --index-url https://download.pytorch.org/whl/cpu
COPY pyproject.toml ./
COPY app ./app
RUN pip install .

# Model weights are downloaded on first start into a named volume (see docker-compose.yml).
ENV HF_HOME=/app/.cache/huggingface

RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/storage /app/models /app/.cache/huggingface \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
