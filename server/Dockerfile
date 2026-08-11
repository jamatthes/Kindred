# Kindred API image.
#
# Multi-stage: the build stage carries the compiler toolchain needed to build asyncpg and
# argon2-cffi wheels; the runtime stage carries only the resulting virtualenv, so none of
# that toolchain ships to production.
#
# Build context is `server/` (see deploy/docker-compose.yml).

# ---------------------------------------------------------------------------- build ------
FROM python:3.11-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN apt-get update \
 && apt-get install --no-install-recommends -y build-essential \
 && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /build
COPY pyproject.toml ./
COPY app ./app

# Install the project to resolve and install its dependencies, then drop the project itself:
# the runtime stage runs from the copied source tree at /app, and having a second copy in
# site-packages would make it ambiguous which one is executing.
RUN pip install . \
 && pip uninstall -y kindred-server

# -------------------------------------------------------------------------- runtime ------
FROM python:3.11-slim AS runtime

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./
COPY pyproject.toml ./

# Non-root. The uid is fixed so a bind-mounted attachments volume has predictable ownership.
RUN useradd --system --uid 10001 --create-home --home-dir /home/kindred kindred \
 && mkdir -p /data/attachments \
 && chown -R kindred:kindred /data /app

USER kindred

EXPOSE 8000

# Migrations and the seed run in the app lifespan before uvicorn accepts traffic, with the
# database connection retried for up to 60s (app/core/migrations.py). No entrypoint script
# is needed, and a failure there exits non-zero so the restart policy takes over.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
