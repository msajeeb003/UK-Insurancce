"""
FastAPI application — Insurance Quote Comparison Tool.

Run locally:
    uvicorn app.main:app --reload

Endpoints (see app/api/routes.py):
    GET  /health         liveness + configuration check
    POST /extract-quote  PDF upload -> structured, source-linked JSON
    GET  /               broker frontend (frontend/ directory)
"""

import logging
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

app = FastAPI(
    title="Insurance Quote Extraction API",
    description=(
        "AI Extraction Module for the Insurance Quote Comparison Tool. "
        "Accepts insurer quote PDFs / credit limit schedules and returns "
        "normalized, source-linked structured JSON."
    ),
    version="0.2.0",
)

app.include_router(router)
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="frontend")


@app.middleware("http")
async def security_headers(request: Request, call_next) -> Response:
    """Baseline hardening headers on every response."""
    response: Response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")
