"""
FastAPI application — AI Extraction Module.

Run locally:
    uvicorn app.main:app --reload

Endpoint:
    POST /extract-quote
        multipart/form-data with field `file` = the PDF
        optional query param `engine` = auto | digital | azure  (default auto)
    -> ExtractionResponse JSON (see app/schemas.py)
"""

import logging
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from openai import APIError as OpenAIAPIError
from azure.core.exceptions import AzureError

from app.config import get_settings
from app.pipeline import EngineOverride, run_extraction_pipeline
from app.schemas import ExtractionResponse

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Insurance Quote Extraction API",
    description=(
        "AI Extraction Module for the Insurance Quote Comparison Tool. "
        "Accepts insurer quote PDFs / credit limit schedules and returns "
        "normalized, source-linked structured JSON."
    ),
    version="0.1.0",
)

# ── Frontend (wireframe-faithful SPA in /static) ─────────────────────────
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
async def health() -> dict:
    """Liveness probe + config sanity check (no secrets exposed)."""
    settings = get_settings()
    return {
        "status": "ok",
        "openai_configured": bool(settings.openai_api_key),
        "azure_configured": bool(settings.azure_endpoint and settings.azure_key),
    }


@app.post("/extract-quote", response_model=ExtractionResponse)
async def extract_quote(
    file: UploadFile = File(..., description="Insurer quote or credit limit schedule (PDF)"),
    engine: EngineOverride = Query(
        "auto",
        description=(
            "Extraction engine: 'auto' detects digital vs scanned, "
            "'digital' forces PyMuPDF, 'azure' forces Azure Document "
            "Intelligence OCR."
        ),
    ),
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

    pdf_bytes = await file.read()
    if not pdf_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    max_bytes = settings.max_upload_mb * 1024 * 1024
    if len(pdf_bytes) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds the {settings.max_upload_mb} MB upload limit.",
        )

    # ── Pipeline ─────────────────────────────────────────────────────────
    try:
        return await run_extraction_pipeline(pdf_bytes, filename, engine)
    except ValueError as exc:
        # Bad/encrypted/empty PDFs, no extractable text, etc.
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        # Missing configuration (keys) or LLM refused/incomplete output.
        logger.error("Pipeline runtime error for %s: %s", filename, exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except AzureError as exc:
        logger.exception("Azure Document Intelligence failed for %s", filename)
        raise HTTPException(
            status_code=502,
            detail=f"Azure Document Intelligence error: {exc.__class__.__name__}",
        ) from exc
    except OpenAIAPIError as exc:
        logger.exception("OpenAI API failed for %s", filename)
        raise HTTPException(
            status_code=502,
            detail=f"OpenAI API error: {exc.__class__.__name__}",
        ) from exc
