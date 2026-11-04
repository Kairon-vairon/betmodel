# syntax=docker/dockerfile:1
# Edgewise backend: API (default command) and worker (`edgewise worker`) share this image.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
RUN useradd --create-home --uid 10001 edgewise

COPY pyproject.toml alembic.ini ./
COPY alembic ./alembic
COPY edgewise ./edgewise
RUN pip install .

USER edgewise
EXPOSE 8000

# Apply database migrations, then serve the API. Only the api service runs this; the
# worker starts after the api is healthy, so migrations never run twice at once.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn --factory edgewise.api.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*'"]
