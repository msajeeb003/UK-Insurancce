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

import asyncio
import logging
import secrets
import threading
import time
from collections import deque
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.audit import router as audit_router
from app.api.auth import router as auth_router
from app.api.observability import router as observability_router
from app.api.projects import router as projects_router
from app.api.routes import router
from app.core import auth as auth_core
from app.core import observability as obs
from app.core.auth import COOKIE_NAME, delete_expired_sessions, seed_admin_if_empty
from app.core.config import get_settings
from app.core.startup import is_production, run_startup_checks

obs.configure_logging()          # JSON logs with request id / user id
run_startup_checks()             # prod refuses to boot on an insecure config
obs.init_sentry()                # DSN-gated; no-op when SENTRY_DSN unset
logger = logging.getLogger(__name__)
_PROD = is_production()

_SESSION_CLEANUP_INTERVAL = 3600   # seconds between expired-session sweeps
_RETENTION_INTERVAL = 86400        # seconds between retention purges (daily)
_background_tasks: set[asyncio.Task] = set()

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
    # The interactive docs and OpenAPI schema are internal-only aids — turn
    # them off entirely in production so nothing about the API is public.
    docs_url=None if _PROD else "/docs",
    redoc_url=None if _PROD else "/redoc",
    openapi_url=None if _PROD else "/openapi.json",
)

app.include_router(router)
app.include_router(auth_router)
app.include_router(projects_router)
app.include_router(observability_router)
app.include_router(audit_router)
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="frontend")


@app.middleware("http")
async def request_context(request: Request, call_next) -> Response:
    """Tag each request with a correlation id (echoed in X-Request-Id and
    every log line), and turn an unhandled exception into a clean 500 that is
    logged + sent to Sentry — never a stack trace to the client."""
    rid = request.headers.get("X-Request-Id") or obs.new_request_id()
    obs.request_id_var.set(rid)
    obs.user_id_var.set("-")
    started = time.monotonic()
    try:
        response = await call_next(request)
    except Exception as exc:
        obs.capture(exc, path=request.url.path, method=request.method)
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        response = JSONResponse(status_code=500, content={"detail": "Internal error."})
    took = int((time.monotonic() - started) * 1000)
    response.headers["X-Request-Id"] = rid
    if request.url.path not in ("/healthz", "/readyz") and response.status_code >= 500:
        logger.error("5xx on %s %s", request.method, request.url.path,
                     extra={"extra_fields": {"status": response.status_code,
                                             "duration_ms": took}})
    return response


@app.on_event("startup")
def _startup() -> None:
    # BRD 2.10: no self-registration — first user comes from the environment.
    seed_admin_if_empty()


@app.on_event("startup")
async def _start_session_cleanup() -> None:
    """Purge expired sessions once at startup, then every hour — instead of
    on every auth check. Pure asyncio, no external scheduler."""
    async def loop() -> None:
        while True:
            try:
                delete_expired_sessions()
            except Exception:
                logger.exception("Expired-session cleanup failed")
            await asyncio.sleep(_SESSION_CLEANUP_INTERVAL)

    # Keep a reference so the task is not garbage-collected mid-run.
    task = asyncio.create_task(loop())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


@app.on_event("startup")
async def _start_retention_purge() -> None:
    """Hard-delete projects past RETENTION_DAYS, once at startup then daily.
    No-op when retention is disabled. Idempotent, so running per worker is
    safe; a Railway cron on `python -m app.retention run` works too."""
    from app.retention import purge_expired

    async def loop() -> None:
        while True:
            try:
                if get_settings().retention_days > 0:
                    await asyncio.to_thread(purge_expired)
            except Exception:
                logger.exception("Retention purge failed")
            await asyncio.sleep(_RETENTION_INTERVAL)

    task = asyncio.create_task(loop())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

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


# ── CSRF protection ──────────────────────────────────────────────────────
# Defence-in-depth on top of the SameSite=Lax cookie. State-changing
# requests must carry an X-CSRF-Token header matching the token bound to
# the session. A cross-site attacker's page cannot read the token (it lives
# in the app's JS memory, protected by the same-origin policy) nor set a
# custom header on a simple form post, so a forged request is rejected.
_CSRF_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
# Login has no session/token yet; logout is a harmless CSRF target and
# exempting it avoids locking out a pre-upgrade session.
_CSRF_EXEMPT = {"/auth/login", "/auth/logout"}


@app.middleware("http")
async def csrf_protect(request: Request, call_next) -> Response:
    if request.method in _CSRF_METHODS and request.url.path not in _CSRF_EXEMPT:
        cookie = request.cookies.get(COOKIE_NAME)
        # Only enforce when a session cookie is actually present — an
        # unauthenticated request carries no cookie to abuse and is left to
        # the endpoint's own auth check (401).
        if cookie:
            expected = auth_core.csrf_token_for(cookie)
            supplied = request.headers.get("X-CSRF-Token")
            if not expected or not supplied or not secrets.compare_digest(supplied, expected):
                return JSONResponse(
                    status_code=403,
                    content={"detail": "CSRF check failed — please sign in again."},
                )
    return await call_next(request)


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
