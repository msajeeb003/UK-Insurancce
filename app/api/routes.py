"""
HTTP endpoints.

Error contract: the pipeline raises `PipelineError` subclasses whose
messages are client-safe and whose `status_code` maps directly onto the
HTTP response. Unexpected exceptions become an opaque 500 — details go to
the server log only, never to the client.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, File, HTTPException, Query, UploadFile

from app.core.config import get_settings
from app.core.errors import PipelineError
from app.models.schemas import ExtractionResponse
from app.services.pipeline import EngineOverride, run_extraction_pipeline

logger = logging.getLogger(__name__)

router = APIRouter()

_READ_CHUNK = 1024 * 1024  # 1 MB


@router.get("/health")
async def health() -> dict:
    """Liveness probe + config sanity check (no secrets exposed)."""
    settings = get_settings()
    return {
        "status": "ok",
        "openai_configured": bool(settings.openai_api_key.get_secret_value()),
        "azure_configured": bool(
            settings.azure_endpoint and settings.azure_key.get_secret_value()
        ),
    }


async def _read_capped(file: UploadFile, max_bytes: int) -> bytes:
    """Read the upload in chunks, aborting as soon as it exceeds the cap."""
    chunks: list[bytes] = []
    total = 0
    while chunk := await file.read(_READ_CHUNK):
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"File exceeds the {max_bytes // (1024 * 1024)} MB upload limit.",
            )
        chunks.append(chunk)
    return b"".join(chunks)


@router.post("/extract-quote", response_model=ExtractionResponse)
async def extract_quote(
    file: Annotated[
        UploadFile,
        File(description="Insurer quote or credit limit schedule (PDF)"),
    ],
    engine: Annotated[
        EngineOverride,
        Query(
            description=(
                "Extraction engine: 'auto' detects digital vs scanned, "
                "'digital' forces PyMuPDF, 'azure' forces Azure Document "
                "Intelligence OCR."
            ),
        ),
    ] = "auto",
) -> ExtractionResponse:
    settings = get_settings()

    # ── Upload validation ────────────────────────────────────────────────
    filename = file.filename or "upload.pdf"
    if not filename.lower().endswith(".pdf") and file.content_type != "application/pdf":
        raise HTTPException(
            status_code=415,
            detail="Only PDF files are accepted (got "
                   f"{file.content_type or 'unknown content type'}).",
        )

    pdf_bytes = await _read_capped(file, settings.max_upload_mb * 1024 * 1024)
    if not pdf_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    # ── Pipeline ─────────────────────────────────────────────────────────
    try:
        return await run_extraction_pipeline(pdf_bytes, filename, engine)
    except PipelineError as exc:
        # Message is client-safe by contract; anything sensitive was logged
        # where the error was raised.
        logger.warning("Extraction rejected for %s: %s", filename, exc)
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except Exception as exc:
        # Unknown failure (SDK errors, bugs): opaque to the client.
        logger.exception("Unexpected extraction failure for %s", filename)
        raise HTTPException(
            status_code=502,
            detail="Extraction failed unexpectedly. Check the server logs.",
        ) from exc
