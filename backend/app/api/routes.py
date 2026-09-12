"""
HTTP endpoints.

Error contract: the pipeline raises `PipelineError` subclasses whose
messages are client-safe and whose `status_code` maps directly onto the
HTTP response. Unexpected exceptions become an opaque 502 — details go to
the server log only, never to the client.
"""

import logging
import re
import secrets
import time
from typing import Annotated, Literal

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
)

from app.api.observability import record_generation
from app.core import db
from app.core import observability as obs
from app.core.auth import require_user
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
    "application/vnd.ms-excel",  # legacy .xls
}


@router.get("/health")
async def health() -> dict:
    """Liveness probe + config sanity check (no secrets exposed)."""
    from app.extraction.docling_extractor import docling_available
    from app.llm.router import active_model_label

    settings = get_settings()
    azure = bool(settings.azure_endpoint and settings.azure_key.get_secret_value())
    docling = docling_available()
    return {
        "status": "ok",
        "llm": active_model_label(),  # e.g. "anthropic:claude-haiku-4-5"
        "openai_configured": bool(settings.openai_api_key.get_secret_value()),
        "anthropic_configured": bool(settings.anthropic_api_key.get_secret_value()),
        "azure_configured": azure,
        "docling_installed": docling,
        "scanned_pdf_engine": "azure" if azure else ("docling" if docling else "none"),
    }


@router.get("/insurers")
async def insurers() -> dict:
    """
    The standing insurer list with the debt-collection rule (BRD 2.4).
    Served from config/insurers.json — configuration, not code, so edits
    take effect without a release.
    """
    return {"insurers": get_insurers()}


def _http_from_pipeline_error(exc: PipelineError, context: str) -> HTTPException:
    """PipelineError messages are client-safe by contract; anything
    sensitive was logged where the error was raised."""
    logger.warning("%s: %s", context, exc)
    return HTTPException(status_code=exc.status_code, detail=str(exc))


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


def _store_document(project_id: str, kind: str, filename: str,
                    file_bytes: bytes, page_count: int) -> str:
    """Retain the uploaded document against the project (BRD S4/2.9)."""
    doc_id = secrets.token_hex(12)
    safe = re.sub(r"[^\w.\- ]", "_", filename)[-80:]
    folder = get_settings().data_path / "projects" / project_id / "docs"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{doc_id}_{safe}"
    path.write_bytes(file_bytes)
    db.execute(
        "INSERT INTO documents (id, project_id, kind, filename, stored_path, "
        "page_count, uploaded) VALUES (?,?,?,?,?,?,?)",
        (doc_id, project_id, kind, filename, str(path), page_count, db.now()),
    )
    return doc_id


def _store_export(project_id: str, format: str, filename: str,
                  content: bytes, extension: str) -> None:
    """Keep the latest export downloadable from the project list (BRD S2).
    Regenerating replaces the previous file — no versioning (BRD 2.8)."""
    folder = get_settings().data_path / "projects" / project_id / "exports"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{format}.{extension}"
    path.write_bytes(content)
    db.execute(
        "INSERT INTO exports (project_id, format, filename, stored_path, created) "
        "VALUES (?,?,?,?,?) ON CONFLICT(project_id, format) DO UPDATE SET "
        "filename=excluded.filename, stored_path=excluded.stored_path, "
        "created=excluded.created",
        (project_id, format, filename, str(path), db.now()),
    )


@router.post("/generate-presentation", dependencies=[Depends(require_user)])
async def generate_presentation(
    request: PresentationRequest,
    project_id: Annotated[
        str | None,
        Query(max_length=64, description=(
            "When given, the generated file is also retained against this "
            "project so it stays downloadable from the project list."
        )),
    ] = None,
    format: Annotated[
        ExportFormat,
        Query(description=(
            "'pptx' — editable PowerPoint (Google Slides compatible); "
            "'pdf' — the same presentation as PDF; 'limits-xlsx' — the "
            "buyer credit-limit table as an editable Excel file (BRD 2.6)."
        )),
    ] = "pptx",
    fields_total: Annotated[int, Query(ge=0)] = 0,
    fields_edited: Annotated[int, Query(ge=0)] = 0,
    prep_seconds: Annotated[float | None, Query(ge=0)] = None,
) -> Response:
    """
    Render the BRD 2.8 presentation from the reviewed project state.

    The BRD 2.5 export gate is enforced server-side: a request whose
    `confirmed_fields` is missing any of the four key values gets a 409.
    Regenerating simply replaces the broker's previous download — no
    versioning in this build. Nothing is sent from the system.
    """
    builder, extension, media_type = _EXPORT_BUILDERS[format]
    started = time.monotonic()
    try:
        content = builder(request)
    except PipelineError as exc:
        raise _http_from_pipeline_error(
            exc, f"Export refused for {request.client_name!r}"
        ) from exc
    except Exception as exc:
        obs.capture(exc, path="/generate-presentation", format=format)
        logger.exception("Presentation generation failed for %r", request.client_name)
        raise HTTPException(
            status_code=500,
            detail="Presentation generation failed unexpectedly. Check the server logs.",
        ) from exc

    gen_seconds = round(time.monotonic() - started, 2)
    obs.log_event("generation", project_id=project_id, format=format,
                  duration_ms=int(gen_seconds * 1000), columns=len(request.columns))
    filename = suggested_filename(request, extension)
    if project_id:
        _store_export(project_id, format, filename, content, extension)
        # One metrics row per generation event (pptx = the primary deliverable,
        # so pdf/xlsx of the same project don't double-count).
        if format == "pptx":
            record_generation(project_id, prep_seconds, gen_seconds,
                              fields_total, fields_edited)
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
    if (
        lowered.endswith((".xlsx", ".xlsm", ".xls"))
        or content_type in EXCEL_CONTENT_TYPES
    ):
        return "excel"
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


@router.post("/extract-quote", response_model=ExtractionResponse,
             dependencies=[Depends(require_user)])
async def extract_quote(
    file: Annotated[
        UploadFile,
        File(description="Insurer quote, credit-limit schedule or policy document (PDF/xlsx)"),
    ],
    project_id: Annotated[
        str | None,
        Form(max_length=64, description=(
            "Project to retain this document against (BRD S4). Without it "
            "the document is extracted but not stored."
        )),
    ] = None,
    doc_kind: Annotated[
        Literal["quote", "limits", "expiring"] | None,
        Form(description="Which upload slot the file came from."),
    ] = None,
    engine: Annotated[
        EngineOverride,
        Query(
            description=(
                "PDF extraction engine: 'auto' detects digital vs scanned "
                "(scans use Azure when configured, else Docling), 'digital' "
                "forces PyMuPDF, 'azure' forces Azure Document Intelligence, "
                "'docling' forces the open-source OCR. Ignored for Excel."
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
    started = time.monotonic()
    try:
        result = await run_extraction_pipeline(file_bytes, filename, engine, file_kind)
        if project_id:
            result.meta.document_id = _store_document(
                project_id, doc_kind or "quote", filename,
                file_bytes, result.meta.page_count,
            )
        obs.log_event("extraction", project_id=project_id, kind=file_kind,
                      engine=result.meta.extraction_engine,
                      pages=result.meta.page_count,
                      duration_ms=int((time.monotonic() - started) * 1000))
        return result
    except PipelineError as exc:
        # Expected/handled failure (bad file, no creds) — client-safe message.
        obs.log_event("extraction_failed", kind=file_kind, reason=type(exc).__name__)
        raise _http_from_pipeline_error(
            exc, f"Extraction rejected for {filename}"
        ) from exc
    except Exception as exc:
        # Unknown failure (SDK errors, bugs): opaque to the client.
        obs.capture(exc, path="/extract-quote", kind=file_kind)
        logger.exception("Unexpected extraction failure for %s", filename)
        raise HTTPException(
            status_code=502,
            detail="Extraction failed unexpectedly. Check the server logs.",
        ) from exc
