"""
HTTP endpoints.

Error contract: the pipeline raises `PipelineError` subclasses whose
messages are client-safe and whose `status_code` maps directly onto the
HTTP response. Unexpected exceptions become an opaque 502 — details go to
the server log only, never to the client.
"""

import logging
from typing import Annotated, Literal

from fastapi import APIRouter, File, HTTPException, Query, Response, UploadFile

from app.core.config import get_settings
from app.core.errors import PipelineError
from app.models.presentation import PresentationRequest
from app.models.schemas import ExtractionResponse
from app.services.library import get_insurers
from app.services.pipeline import EngineOverride, FileKind, run_extraction_pipeline
from app.services.presentation import (
    build_limits_xlsx,
    build_pdf,
    build_pptx,
    suggested_filename,
)

logger = logging.getLogger(__name__)

router = APIRouter()

_READ_CHUNK = 1024 * 1024  # 1 MB

EXCEL_CONTENT_TYPES = {
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel.sheet.macroEnabled.12",
}


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


@router.get("/insurers")
async def insurers() -> dict:
    """
    The standing insurer list with the debt-collection rule (BRD 2.4).
    Served from config/insurers.json — configuration, not code, so edits
    take effect without a release.
    """
    return {"insurers": get_insurers()}


ExportFormat = Literal["pptx", "pdf", "limits-xlsx"]

_EXPORT_BUILDERS = {
    "pptx": (
        build_pptx, "pptx",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ),
    "pdf": (build_pdf, "pdf", "application/pdf"),
    "limits-xlsx": (
        build_limits_xlsx, "xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ),
}


@router.post("/generate-presentation")
async def generate_presentation(
    request: PresentationRequest,
    format: Annotated[
        ExportFormat,
        Query(description=(
            "'pptx' — editable PowerPoint (Google Slides compatible); "
            "'pdf' — the same presentation as PDF; 'limits-xlsx' — the "
            "buyer credit-limit table as an editable Excel file (BRD 2.6)."
        )),
    ] = "pptx",
) -> Response:
    """
    Render the BRD 2.8 presentation from the reviewed project state.

    The BRD 2.5 export gate is enforced server-side: a request whose
    `confirmed_fields` is missing any of the four key values gets a 409.
    Regenerating simply replaces the broker's previous download — no
    versioning in this build. Nothing is sent from the system.
    """
    builder, extension, media_type = _EXPORT_BUILDERS[format]
    try:
        content = builder(request)
    except PipelineError as exc:
        logger.warning("Export refused for %r: %s", request.client_name, exc)
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Presentation generation failed for %r", request.client_name)
        raise HTTPException(
            status_code=500,
            detail="Presentation generation failed unexpectedly. Check the server logs.",
        ) from exc

    filename = suggested_filename(request, extension)
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _resolve_file_kind(filename: str, content_type: str | None) -> FileKind:
    """Route by extension/content type; raise 415 for anything unsupported."""
    lowered = filename.lower()
    if lowered.endswith(".pdf") or content_type == "application/pdf":
        return "pdf"
    if lowered.endswith((".xlsx", ".xlsm")) or content_type in EXCEL_CONTENT_TYPES:
        return "excel"
    if lowered.endswith(".xls"):
        raise HTTPException(
            status_code=415,
            detail=(
                "Legacy .xls workbooks are not supported — re-save the "
                "schedule as .xlsx and upload again."
            ),
        )
    raise HTTPException(
        status_code=415,
        detail=(
            "Only PDF and Excel (.xlsx) files are accepted (got "
            f"{content_type or 'unknown content type'})."
        ),
    )


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
        File(description="Insurer quote, credit-limit schedule or policy document (PDF/xlsx)"),
    ],
    engine: Annotated[
        EngineOverride,
        Query(
            description=(
                "PDF extraction engine: 'auto' detects digital vs scanned, "
                "'digital' forces PyMuPDF, 'azure' forces Azure Document "
                "Intelligence OCR. Ignored for Excel uploads."
            ),
        ),
    ] = "auto",
) -> ExtractionResponse:
    settings = get_settings()

    # ── Upload validation ────────────────────────────────────────────────
    filename = file.filename or "upload.pdf"
    file_kind = _resolve_file_kind(filename, file.content_type)

    file_bytes = await _read_capped(file, settings.max_upload_mb * 1024 * 1024)
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    # ── Pipeline ─────────────────────────────────────────────────────────
    try:
        return await run_extraction_pipeline(file_bytes, filename, engine, file_kind)
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
