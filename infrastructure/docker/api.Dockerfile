# Backend image: serves the ASGI app (daphne) and runs the Celery worker.
#
# daphne, not gunicorn: this app carries WebSocket traffic (the local-runner relay
# and live session streams). A WSGI server cannot upgrade a connection, so gunicorn
# would accept the request and then fail the handshake.
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    DJANGO_SETTINGS_MODULE=config.settings.prod

WORKDIR /app
# psycopg ships manylinux wheels and cryptography bundles its own OpenSSL, so no
# build toolchain is required in the image. Fewer packages, smaller attack surface.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Never run as root: a compromised app process should not own the filesystem.
RUN useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8080
# Fly overrides this for the worker with `processes`. Kept as the API default.
CMD ["daphne", "-b", "0.0.0.0", "-p", "8080", "config.asgi:application"]
