# Hydrology Data Pipeline - Local Server Docker Image
FROM python:3.11-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV GOOGLE_APPLICATION_CREDENTIALS=/app/credentials/gcs-key.json

# Set working directory
WORKDIR /app

# Copy requirements first (for better caching)
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Copy application code and configuration
COPY ftp_to_gcs_sync.py .
COPY .env .
COPY credentials/ ./credentials/

# Create necessary directories
RUN mkdir -p /app/logs /tmp/hydrology

# Create non-root user for security
RUN useradd -m -u 1000 hydrology && \
    chown -R hydrology:hydrology /app /tmp/hydrology

USER hydrology

# Health check
HEALTHCHECK --interval=5m --timeout=30s --start-period=2m --retries=3 \
    CMD python -c "import ftp_to_gcs_sync; print('OK')" || exit 1

# Default command - run the sync once
CMD ["python", "ftp_to_gcs_sync.py"]