# Insurance Quote Comparison Tool — container image.
# Works on Railway / Render / Fly / any Docker host (and Hetzner later).
#
#   docker build -t quote-tool .
#   docker run -p 8000:8000 --env-file .env -v quote_data:/data quote-tool
#
# The open-source OCR stack (Docling + PyTorch, several GB) is NOT
# installed by default — scanned PDFs then need Azure keys, or rebuild
# with:  docker build --build-arg INSTALL_OCR=1 .

FROM python:3.12-slim

WORKDIR /srv

# Patch base-image OS packages so the image ships without known fixable
# HIGH/CRITICAL CVEs (enforced by the Trivy scan in CI).
RUN apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

ARG INSTALL_OCR=0
COPY backend/requirements-ocr.txt backend/requirements-ocr.txt
RUN if [ "$INSTALL_OCR" = "1" ]; then \
      pip install --no-cache-dir -r backend/requirements-ocr.txt; \
    fi

COPY backend backend
COPY frontend frontend
COPY entrypoint.sh entrypoint.sh

# Make the `app` package importable for gunicorn AND `python -m app.backup`.
ENV PYTHONPATH=/srv/backend
# SQLite DB + retained documents + exports — mount a persistent volume here.
ENV DATA_DIR=/data
RUN mkdir -p /data && chmod +x entrypoint.sh

EXPOSE 8000
# entrypoint.sh takes a pre-start safety backup, then launches gunicorn with
# several Uvicorn workers (--timeout 180 because an extraction waits 1-2 min
# on the LLM; the default 30s would kill the worker mid-request). WORKERS
# falls back to WEB_CONCURRENCY, then 2.
CMD ["sh", "entrypoint.sh"]
