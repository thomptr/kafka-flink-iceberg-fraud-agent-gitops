# syntax=docker/dockerfile:1
FROM python:3.11-slim-bookworm

WORKDIR /app
RUN useradd --create-home --uid 10001 appuser
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY main.py .

USER appuser
ENV PYTHONUNBUFFERED=1
ENTRYPOINT ["python", "/app/main.py"]
