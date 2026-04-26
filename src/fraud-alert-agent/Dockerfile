FROM python:3.11-slim AS builder

WORKDIR /build
COPY pyproject.toml setup.cfg ./
RUN pip install --upgrade pip && pip install --no-cache-dir -e ".[dev]" 2>/dev/null || pip install --no-cache-dir -e .

FROM python:3.11-slim

RUN useradd -r -u 1000 -m appuser
WORKDIR /app

COPY --from=builder /usr/local/lib/python3.11 /usr/local/lib/python3.11
COPY --from=builder /usr/local/bin /usr/local/bin

COPY pyproject.toml setup.cfg alembic.ini ./
COPY app/ ./app/

RUN chown -R appuser:appuser /app
USER appuser

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
