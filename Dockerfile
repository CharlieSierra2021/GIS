FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
COPY registry ./registry
COPY alembic.ini ./
COPY migrations ./migrations

ENV PI_REGISTRY_PATH=/app/registry/volusia.yaml

RUN pip install --no-cache-dir .

EXPOSE 8000

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
