"""Admin-only audit trail view + export (append-only; see app/core/audit.py)."""

import csv
import io
import json
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse, Response

from app.core import audit
from app.core.auth import require_user

router = APIRouter(prefix="/audit", dependencies=[Depends(require_user)])


@router.get("")
def list_audit(limit: Annotated[int, Query(ge=1, le=5000)] = 500,
               action: str = "") -> dict:
    return {"entries": audit.recent(limit=limit, action=action)}


@router.get("/export")
def export_audit(user: Annotated[dict, Depends(require_user)]) -> Response:
    """Full trail as CSV (metadata only). The export itself is audited."""
    rows = audit.recent(limit=5000)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["timestamp_utc", "actor", "action", "target", "detail"])
    for r in rows:
        writer.writerow([
            datetime.fromtimestamp(r["ts"], UTC).isoformat(timespec="seconds"),
            r["actor"], r["action"], r["target"], r["detail"],
        ])
    audit.record("audit.export", actor=user["email"], count=len(rows))
    return Response(
        content=buf.getvalue(), media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="audit-log.csv"'},
    )


@router.get("/view", response_class=HTMLResponse)
def audit_view(user: Annotated[dict, Depends(require_user)]) -> str:
    rows = audit.recent(limit=500)
    body = []
    for r in rows:
        ts = datetime.fromtimestamp(r["ts"], UTC).strftime("%Y-%m-%d %H:%M")
        try:
            detail = ", ".join(f"{k}={v}" for k, v in json.loads(r["detail"]).items())
        except (ValueError, TypeError):
            detail = ""
        body.append(
            f"<tr><td>{ts}</td><td>{r['actor']}</td><td><b>{r['action']}</b></td>"
            f"<td>{r['target']}</td><td style='color:#555'>{detail}</td></tr>"
        )
    return (
        "<style>body{font:13px system-ui;margin:24px}"
        "table{border-collapse:collapse;width:100%}"
        "td,th{padding:6px 10px;border-bottom:1px solid #eee;text-align:left}"
        "</style><h2>Audit trail</h2>"
        "<p><a href='/audit/export'>Export CSV</a> · append-only, newest first</p>"
        "<table><tr><th>Time (UTC)</th><th>Actor</th><th>Action</th>"
        "<th>Target</th><th>Detail</th></tr>" + "".join(body) + "</table>"
    )
