# Multi-stage Dockerfile for TonGPT production deployment
FROM python:3.11-slim as builder

# Set build arguments
ARG BUILD_ENV=production
ARG APP_VERSION=1.0.0

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create app directory
WORKDIR /app

# Copy requirements first (for better caching)
COPY requirements.txt .
COPY requirements-prod.txt .

# Install Python dependencies
RUN pip install --upgrade pip && \
    pip install -r requirements.txt && \
    pip install -r requirements-prod.txt

# Production stage
FROM python:3.11-slim as production

# Install runtime dependencies
RUN apt-get update && apt-get install -y \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Create non-root user for security
RUN groupadd -r tongpt && useradd -r -g tongpt tongpt

# Create app directory and set ownership
WORKDIR /app
RUN chown tongpt:tongpt /app

# Copy Python packages from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Create necessary directories
RUN mkdir -p logs miniapp static && \
    chown -R tongpt:tongpt /app

# Copy application code
COPY --chown=tongpt:tongpt . .

# Switch to non-root user
USER tongpt

# Create volume mount points
VOLUME ["/app/logs", "/app/static"]

# Expose ports
EXPOSE 8000 8001

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || exit 1

# Default command
CMD ["python", "main.py"]

# Labels for metadata
LABEL maintainer="tongpt@example.com" \
      version="${APP_VERSION}" \
      description="TonGPT Telegram Bot for TON Memecoin Analysis" \
      build_env="${BUILD_ENV}"