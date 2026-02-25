# Stage 1: Build stage
FROM python:3.12-slim AS builder

WORKDIR /app

# Install system dependencies for building Python packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    python3-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv
ADD https://astral.sh/uv/install.sh /uv-installer.sh
RUN sh /uv-installer.sh && rm /uv-installer.sh

ENV PATH="/root/.local/bin/:$PATH"

# Copy project files and install dependencies
COPY pyproject.toml .
RUN uv venv /app/.venv && \
    uv pip install --no-cache -r pyproject.toml

# Stage 2: Runtime stage
FROM python:3.12-slim

WORKDIR /app

# Copy virtual environment from builder
COPY --from=builder /app/.venv /app/.venv

# Copy version metadata
COPY pyproject.toml .

# Activate virtual environment
ENV PATH="/app/.venv/bin:$PATH"

# Copy application code
COPY bot/ ./bot/

# Run the bot
CMD ["python", "-m", "bot.main"]
