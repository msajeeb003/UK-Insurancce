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

from app.api.auth import router as auth_router
from app.api.projects import router as projects_router
from app.api.routes import router
from app.core.auth import seed_admin_if_empty
from app.core.config import get_settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

# backend/app/main.py -> repo root -> frontend/ (kept fully separate from
# the backend; the server only serves its static files).
FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"

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
app.include_router(auth_router)
app.include_router(projects_router)
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="frontend")


@app.on_event("startup")
def _startup() -> None:
    # BRD 2.10: no self-registration — first user comes from the environment.
    seed_admin_if_empty()

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
# Without cleanup, one bucket per unique IP would accumulate forever (a
# slow memory leak). A periodic sweep drops idle IPs, and a hard ceiling
# caps memory even under an IP-spraying burst. In-memory only — restarting
# the process resets the windows; a shared store (Redis) is a later step.
_rate_sweep_counter = 0
_RATE_SWEEP_EVERY = 100        # run the global sweep once every N limited requests
_MAX_TRACKED_IPS = 10000       # hard ceiling on distinct IPs kept in memory


def _sweep_rate_buckets(now: float) -> None:
    """Remove IP buckets idle for over 60s; if still above the ceiling,
    drop the least-recently-active IPs. Caller must hold `_rate_lock`."""
    idle = [ip for ip, b in _rate_buckets.items() if not b or now - b[-1] > 60]
    for ip in idle:
        del _rate_buckets[ip]
    overflow = len(_rate_buckets) - _MAX_TRACKED_IPS
    if overflow > 0:
        # Oldest last-activity first — those are the safest to forget.
        oldest = sorted(_rate_buckets.items(), key=lambda kv: kv[1][-1])
        for ip, _ in oldest[:overflow]:
            del _rate_buckets[ip]


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
                global _rate_sweep_counter
                _rate_sweep_counter += 1
                if _rate_sweep_counter % _RATE_SWEEP_EVERY == 0:
                    _sweep_rate_buckets(now)
                bucket = _rate_buckets.setdefault(client_ip, deque())
                # Drop this IP's timestamps older than the 60s window.
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
