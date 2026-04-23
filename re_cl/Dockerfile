# RE_CL Python services (API + Streamlit + pipeline)
FROM python:3.11-slim

WORKDIR /app

# System deps for PostGIS / GeoPandas / Playwright
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libgdal-dev \
    libpq-dev \
    gdal-bin \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Python deps (exclude prefect y playwright — no son necesarios en Docker)
COPY requirements.txt .
RUN grep -v "^prefect\|^playwright" requirements.txt > /tmp/requirements_docker.txt && \
    pip install --no-cache-dir -r /tmp/requirements_docker.txt

# Source code
COPY . .

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# Ports exposed by this image
EXPOSE 8000
EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=10s --retries=3 CMD curl -f http://localhost:8000/health || exit 1
