# syntax=docker/dockerfile:1
# Backend: Litestar API served by granian (Python 3.14, managed with uv).
# IMPORTANT: build with the repo ROOT as context so executables/ (the parser
# clone that EXECUTE_FILE_PATH points at) can be copied beside backend/:
#   docker build -f backend/Dockerfile -t amt-backend .
FROM python:3.14-slim-bookworm

# uv (pinned binary from the official image)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

# Create a non-root user/group up front (C3). The app, venv and writable
# directories are chowned to this user below so it can read the venv and
# executables and write to /app/output and /app/backend/uploads.
RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid 10001 --no-create-home --home-dir /app app

WORKDIR /app/backend

# 1) Dependency layer — cached unless pyproject/lock change.
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev

# 2) Application code + parser clone (app.py resolves EXECUTE_FILE_PATH as ../executables).
COPY backend/ ./
COPY executables/ /app/executables/
RUN chmod +x /app/executables/GWMReader.exe

# 3) Machine spec catalog (REFERENCE_DATA_PATH=/app/reference_data). Lets the model
# generator enrich haulers with real CAT specs from machines.json.
COPY reference_data/ /app/reference_data/

ENV PATH="/app/backend/.venv/bin:$PATH" \
    HOST=0.0.0.0 \
    PORT=5001 \
    DUCKDB_PATH=/app/db/haulsim.duckdb \
    EXECUTE_FILE_PATH=/app/executables/GWMReader.exe \
    OUTPUT_PATH=/app/output \
    REFERENCE_DATA_PATH=/app/reference_data

# 4) Embedded DuckDB database baked into the image, built from the shared catalog
# so the Export path has sample sites/telemetry with no external DB service.
COPY db/ /app/db/
RUN python /app/db/generate_seed.py

# Output dir (also a compose volume mount target) must be writable by the
# non-root user; chown the whole app tree so the venv/executables are readable.
RUN mkdir -p /app/output /app/backend/uploads \
    && chown -R 10001:10001 /app

# Drop privileges: run as the non-root user from here on (C3).
USER 10001:10001

EXPOSE 5001
# Production ASGI server: granian (Rust). SINGLE worker (the app keeps in-memory
# status and uses SSE — multiple workers would break both); the async event loop
# handles concurrent status polling / SSE streams within that one worker.
CMD ["granian", "--interface", "asgi", "--host", "0.0.0.0", "--port", "5001", "--workers", "1", "app:app"]
