FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv

WORKDIR /app

RUN pip install --no-cache-dir uv==0.12.0

COPY backend/pyproject.toml backend/uv.lock /app/backend/
COPY backend/src /app/backend/src
COPY data /app/data

RUN uv sync --project /app/backend --locked --no-dev

EXPOSE 8000

CMD ["/opt/venv/bin/uvicorn", "matchlens.api.app:app", "--app-dir", "/app/backend/src", "--host", "0.0.0.0", "--port", "8000"]
