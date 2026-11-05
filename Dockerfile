FROM python:3.13-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd --create-home --uid 10001 appuser \
    && install -d -m 0700 -o appuser -g appuser /var/lib/kms/file-cleanup

COPY --chown=appuser:appuser app ./app

COPY --chown=appuser:appuser alembic.ini ./
COPY --chown=appuser:appuser alembic ./alembic

USER appuser
EXPOSE 8000

CMD ["python", "app/start.py"]
