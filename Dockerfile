FROM python:3.12-slim

WORKDIR /app

# Install uv
RUN pip install --no-cache-dir uv

# Copy project files
COPY pyproject.toml README.md ./
COPY src/ src/

# Install dependencies (no dev deps)
RUN uv sync --no-dev

# Persistent data lives on a mounted volume at /app/data
VOLUME ["/app/data"]

ENV GARMIN_DB_PATH=/app/data/garmin.db
ENV GARMIN_TOKEN_STORE=/app/data/.garminconnect

EXPOSE 8080

CMD ["uv", "run", "garmin-local", "serve", "streamable-http", "--host", "0.0.0.0", "--port", "8080"]
