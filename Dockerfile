FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Tokyo \
    POVO_DATA_DIR=/data

RUN pip install --no-cache-dir cryptography==50.0.1 \
    && useradd --uid 1000 --create-home --shell /usr/sbin/nologin app

WORKDIR /app
COPY --chown=app:app povo_api.py povo_worker.py povo_web.py healthcheck.py /app/

USER app
CMD ["python", "/app/povo_worker.py"]
