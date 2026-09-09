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

COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

ARG INSTALL_OCR=0
COPY backend/requirements-ocr.txt backend/requirements-ocr.txt
RUN if [ "$INSTALL_OCR" = "1" ]; then \
      pip install --no-cache-dir -r backend/requirements-ocr.txt; \
    fi

COPY backend backend
COPY frontend frontend

# SQLite DB + retained documents + exports — mount a volume here.
ENV DATA_DIR=/data
RUN mkdir -p /data

EXPOSE 8000
# $PORT is injected by Railway/Render; default 8000 elsewhere.
CMD ["sh", "-c", "uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port ${PORT:-8000}"]
