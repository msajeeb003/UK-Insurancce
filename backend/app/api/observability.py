"""Health, readiness, client-error intake, and the internal metrics view."""

import time
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from app.core import db
from app.core import observability as obs
from app.core.auth import require_user
from app.core.config import get_settings

router = APIRouter()


@router.get("/healthz")
def healthz() -> dict:
    """Shallow liveness — the process is up. Used by the uptime monitor."""
    return {"status": "ok"}


@router.get("/readyz")
def readyz() -> Response:
    """Deep readiness: DB writable, DATA_DIR writable, LLM provider configured,
    disk headroom. Returns 503 if any dependency is broken."""
    settings = get_settings()
    checks: dict[str, object] = {}

    # DB writable (round-trip a temp table)
    try:
        db.execute("CREATE TABLE IF NOT EXISTS _readyz (x INTEGER)")
        db.execute("INSERT INTO _readyz (x) VALUES (1)")
        db.execute("DELETE FROM _readyz")
        checks["db_writable"] = True
    except Exception as exc:
        checks["db_writable"] = f"error: {type(exc).__name__}"

    # DATA_DIR writable
    try:
        probe = settings.data_path / ".readyz"
        probe.write_text("ok")
        probe.unlink()
        checks["data_dir_writable"] = True
    except Exception as exc:
        checks["data_dir_writable"] = f"error: {type(exc).__name__}"

    # LLM provider configured (cheap — no paid call)
    has_llm = bool(settings.anthropic_api_key.get_secret_value()
                   or settings.openai_api_key.get_secret_value())
    checks["llm_configured"] = has_llm

    # Disk headroom
    free = obs.disk_free_ratio()
    checks["disk_free_ratio"] = round(free, 3)
    disk_ok = free >= settings.disk_free_min_ratio
    if not disk_ok:
        obs.alert(f"disk near full on DATA_DIR: {free:.1%} free")

    ready = (checks["db_writable"] is True
             and checks["data_dir_writable"] is True
             and has_llm and disk_ok)
    return JSONResponse(
        status_code=200 if ready else 503,
        content={"status": "ready" if ready else "not-ready", "checks": checks},
    )


class ClientError(BaseModel):
    """A scrubbed error report from the frontend (same-origin, CSP-friendly)."""

    message: str = Field(max_length=500)
    kind: str = Field(default="error", max_length=40)     # error | unhandledrejection | ...
    where: str = Field(default="", max_length=200)         # url / component
    stack: str = Field(default="", max_length=4000)


@router.post("/client-error")
def client_error(body: ClientError, request: Request) -> dict:
    """Frontend errors funnel here (no third-party SDK in the strict-CSP app);
    the backend scrubs and forwards to Sentry / structured logs centrally."""
    scrubbed = obs.scrub_text(body.message)
    obs.log_event(
        "client_error", kind=body.kind, where=obs.scrub_text(body.where),
        message=scrubbed, stack=obs.scrub_text(body.stack)[:1000],
    )
    obs.capture(
        RuntimeError(f"[frontend:{body.kind}] {scrubbed}"),
        where=body.where,
    )
    return {"ok": True}


# ── Metrics (BRD success measures) ──────────────────────────────────────────

def record_generation(project_id: str, prep_seconds: float | None,
                      generation_seconds: float, fields_total: int,
                      fields_edited: int) -> None:
    """One row per successful generation (called from the export endpoint)."""
    db.execute(
        "INSERT INTO metrics (project_id, created, prep_seconds, "
        "generation_seconds, fields_total, fields_edited, exported) "
        "VALUES (?,?,?,?,?,?,1)",
        (project_id, time.time(), prep_seconds, generation_seconds,
         fields_total, fields_edited),
    )


def _aggregate() -> dict:
    rows = db.query("SELECT * FROM metrics")
    n = len(rows)
    if not n:
        return {"generations": 0}
    prep = [r["prep_seconds"] for r in rows if r["prep_seconds"] is not None]
    gen = [r["generation_seconds"] for r in rows if r["generation_seconds"] is not None]
    total_fields = sum(r["fields_total"] for r in rows)
    total_edited = sum(r["fields_edited"] for r in rows)
    exported = sum(1 for r in rows if r["exported"])
    return {
        "generations": n,
        "avg_prep_minutes": round(sum(prep) / len(prep) / 60, 1) if prep else None,
        "avg_generation_seconds": round(sum(gen) / len(gen), 1) if gen else None,
        # BRD: field edit rate excludes the 2 set fields (they're not
        # extraction attempts) — the frontend already omits them from the count.
        "field_edit_rate_pct": round(100 * total_edited / total_fields, 1) if total_fields else None,
        "exported_without_rebuild_pct": round(100 * exported / n, 1),
    }


@router.get("/metrics")
def metrics(user: Annotated[dict, Depends(require_user)]) -> dict:
    """JSON aggregates of the BRD success measures (auth-only)."""
    return _aggregate()


@router.get("/metrics/view", response_class=HTMLResponse)
def metrics_view(user: Annotated[dict, Depends(require_user)]) -> str:
    """Minimal internal dashboard (auth-only)."""
    a = _aggregate()
    rows = "".join(
        f"<tr><td>{k}</td><td style='text-align:right'><b>{'' if v is None else v}</b></td></tr>"
        for k, v in a.items()
    )
    return (
        "<style>body{font:14px system-ui;max-width:520px;margin:40px auto}"
        "table{width:100%;border-collapse:collapse}td{padding:8px;border-bottom:1px solid #eee}"
        "</style><h2>Success measures (BRD §5)</h2><table>" + rows + "</table>"
    )
