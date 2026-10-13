FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv

WORKDIR /app

RUN pip install --no-cache-dir uv==0.12.0
RUN groupadd --system app && useradd --system --gid app --home-dir /app app

COPY --chown=app:app backend/pyproject.toml backend/uv.lock /app/backend/
COPY --chown=app:app backend/src /app/backend/src
COPY --chown=app:app data /app/data

RUN uv sync --project /app/backend --locked --no-dev --no-editable --extra azure --extra foundry \
    && chown -R app:app /app

USER app

EXPOSE 8000

CMD ["/opt/venv/bin/uvicorn", "matchlens.api.app:app", "--app-dir", "/app/backend/src", "--host", "0.0.0.0", "--port", "8000"]
