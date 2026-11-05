FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Slow or flaky networks: retry downloads instead of failing the build.
ENV PIP_DEFAULT_TIMEOUT=120 \
    PIP_RETRIES=10

# CPU-only torch first (avoids multi-GB CUDA wheels).
RUN pip install torch --index-url https://download.pytorch.org/whl/cpu

# Dependencies from pyproject.toml *before* copying the code, so a code change reuses this
# cached layer instead of re-downloading every package.
COPY pyproject.toml ./
RUN python -c "import tomllib; print('\n'.join(tomllib.load(open('pyproject.toml','rb'))['project']['dependencies']))" > /tmp/requirements.txt \
    && pip install -r /tmp/requirements.txt

COPY app ./app
RUN pip install --no-deps .

# Labelled questions: the question classifier is trained from these on first start.
COPY sample_data/classifier_examples.json ./sample_data/classifier_examples.json

# Model weights are downloaded on first start into a named volume (see docker-compose.yml).
ENV HF_HOME=/app/.cache/huggingface

RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/storage /app/models /app/.cache/huggingface \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
