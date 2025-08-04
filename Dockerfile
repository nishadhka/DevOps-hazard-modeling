# Multi-stage Docker build for IGAD-ICPAC Hydrology Data Pipeline
FROM python:3.11-slim as base

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PREFECT_RESULTS_PERSIST_BY_DEFAULT=false \
    PREFECT_LOGGING_LEVEL=INFO

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd --create-home --shell /bin/bash prefect

# Set working directory
WORKDIR /app

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY ftp_to_gcs_sync.py .
COPY prefect.yaml .

# Create necessary directories
RUN mkdir -p logs && chown -R prefect:prefect /app

# Switch to non-root user
USER prefect

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import prefect; print('Prefect OK')" || exit 1

# Default command - can be overridden
CMD ["python", "ftp_to_gcs_sync.py"]

# Labels for metadata
LABEL maintainer="Hillary Koros <hkoros@icpac.net>" \
      version="3.0.0" \
      description="IGAD-ICPAC Hydrology Data Synchronization Pipeline" \
      org.opencontainers.image.source="https://github.com/IGAD-ICPAC/DevOps-hazard-modeling"