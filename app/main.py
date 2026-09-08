"""
FastAPI application — Insurance Quote Comparison Tool.

Run locally:
    uvicorn app.main:app --reload

Endpoints (see app/api/routes.py):
    GET  /health                 liveness + configuration check
    GET  /insurers               standing list + debt rule (configuration)
    POST /extract-quote          document upload -> structured JSON
    POST /generate-presentation  reviewed state -> PPTX / PDF / xlsx
    GET  /                       broker frontend (frontend/ directory)
"""

import logging
import threading
import time
from collections import deque
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.core.config import get_settings

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
    version="0.3.0",
)

app.include_router(router)
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="frontend")

# The frontend uses inline style attributes and Google Fonts; scripts are
# strictly same-origin files (no inline handlers anywhere).
CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src https://fonts.gstatic.com; "
    "img-src 'self' data:; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
)


@app.middleware("http")
async def security_headers(request: Request, call_next) -> Response:
    """Baseline hardening headers on every response."""
    response: Response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = CSP
    # Frontend files must revalidate on every load (cheap 304s via ETag) —
    # otherwise brokers keep running a stale app.js after each deployment.
    if request.url.path == "/" or request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


# ── Rate limiting (paid/heavy POST endpoints only) ───────────────────────
_RATE_LIMITED_PATHS = {"/extract-quote", "/generate-presentation"}
_rate_lock = threading.Lock()
_rate_buckets: dict[str, deque] = {}


@app.middleware("http")
async def rate_limit(request: Request, call_next) -> Response:
    """
    Sliding-window per-client-IP limit on the endpoints that cost money
    (OpenAI/Azure calls) or CPU (document rendering). In-memory by design:
    the pilot is a single process for 3-4 internal users (BRD 2.10).
    """
    if request.method == "POST" and request.url.path in _RATE_LIMITED_PATHS:
        limit = get_settings().rate_limit_per_minute
        if limit > 0:
            client_ip = request.client.host if request.client else "unknown"
            now = time.monotonic()
            with _rate_lock:
                bucket = _rate_buckets.setdefault(client_ip, deque())
                while bucket and now - bucket[0] > 60:
                    bucket.popleft()
                if len(bucket) >= limit:
                    return JSONResponse(
                        status_code=429,
                        content={
                            "detail": (
                                f"Rate limit reached ({limit} requests/minute). "
                                "Wait a moment and try again."
                            )
                        },
                    )
                bucket.append(now)
    return await call_next(request)


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")
