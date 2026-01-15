# Use a lightweight Python base image
FROM python:3.13-slim-bookworm

# Install uv for fast dependency management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Set working directory
WORKDIR /app

# Enable bytecode compilation and set UV cache directory
ENV UV_COMPILE_BYTECODE=1
ENV UV_CACHE_DIR=/app/.cache/uv

# Copy project files
COPY pyproject.toml uv.lock ./

# Install dependencies into the system environment
# This allows us to run 'python main.py' directly without 'uv run' if desired,
# but 'uv run' is still recommended for consistency.
RUN uv sync --frozen --no-install-project --no-dev

# Copy the rest of the application
COPY . .

# Create directory for persistent logs, database, and uv cache
RUN mkdir -p /app/data /app/.cache/uv && chown -R 1000:1000 /app

# Environment variable defaults (can be overridden by .env file or docker-compose)
ENV IA_BUCKET=mingpao-canada-backup
ENV MAX_WORKERS=5
# Note: START_DATE and END_DATE should be set via .env file or docker-compose environment

# Use a non-root user for security
USER 1000

# Command to run the archiver
CMD ["uv", "run", "main.py"]
