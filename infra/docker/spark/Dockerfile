FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    openjdk-17-jre-headless=17.* \
    procps \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd -g 1000 reconlake && useradd -u 1000 -g reconlake -m -s /bin/bash reconlake

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY contracts ./contracts
COPY generator ./generator
COPY pipelines ./pipelines
COPY security ./security
COPY quality ./quality
COPY scripts ./scripts

RUN pip install --no-cache-dir --upgrade pip==24.2 && \
    pip install --no-cache-dir ".[spark]"

USER 1000:1000
CMD ["python3", "-m", "pipelines.bronze.streaming_ingest"]
