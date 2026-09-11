"""Project storage endpoints (BRD 2.9 / S2): save, list, reopen, delete;
retained documents and downloadable exports.

The project body is the reviewed UI state as one JSON blob — the server
stores it verbatim, never edits it. No versioning in this build.
"""

import json
import shutil

import pymupdf
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from app.core import db
from app.core.auth import require_user
from app.core.config import get_settings

router = APIRouter(dependencies=[Depends(require_user)])

_MAX_STATE_BYTES = 2 * 1024 * 1024


class ProjectState(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    state: dict


@router.get("/projects")
def list_projects() -> dict:
    rows = db.query("SELECT state FROM projects ORDER BY updated DESC")
    return {"projects": [json.loads(r["state"]) for r in rows]}


@router.post("/projects")
def save_project(body: ProjectState) -> dict:
    blob = json.dumps(body.state)
    if len(blob) > _MAX_STATE_BYTES:
        raise HTTPException(status_code=413, detail="Project state too large.")
    db.execute(
        "INSERT INTO projects (id, client_name, updated, state) VALUES (?,?,?,?) "
        "ON CONFLICT(id) DO UPDATE SET client_name=excluded.client_name, "
        "updated=excluded.updated, state=excluded.state",
        (body.id, str(body.state.get("clientName") or ""), db.now(), blob),
    )
    return {"ok": True}


@router.delete("/projects/{project_id}")
def delete_project(project_id: str) -> dict:
    """Deletion on request (BRD 2.11 retention): removes the project, its
    retained documents and its generated exports — atomically, so a crash
    midway can never leave a half-deleted project behind."""
    db.execute_transaction([
        ("DELETE FROM documents WHERE project_id=?", (project_id,)),
        ("DELETE FROM exports WHERE project_id=?", (project_id,)),
        ("DELETE FROM projects WHERE id=?", (project_id,)),
    ])
    folder = get_settings().data_path / "projects" / project_id
    shutil.rmtree(folder, ignore_errors=True)
    return {"ok": True}


@router.get("/projects/{project_id}/exports/{format}")
def download_export(project_id: str, format: str) -> Response:
    """The latest generated file of this format (BRD S2 download links)."""
    row = db.query_one(
        "SELECT filename, stored_path FROM exports WHERE project_id=? AND format=?",
        (project_id, format),
    )
    if row is None:
        raise HTTPException(status_code=404, detail="No export generated yet.")
    try:
        # `with` guarantees the handle is closed even if read() raises —
        # on Windows an un-closed handle keeps the file locked, which would
        # then block the next export (regeneration overwrites this path).
        with open(row["stored_path"], "rb") as f:
            content = f.read()
    except OSError as exc:
        raise HTTPException(status_code=404, detail="Export file missing.") from exc
    media = {
        "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "pdf": "application/pdf",
        "limits-xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }.get(format, "application/octet-stream")
    return Response(
        content=content, media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{row["filename"]}"'},
    )


@router.get("/documents/{document_id}/page/{page}")
def document_page(document_id: str, page: int) -> Response:
    """One page of a retained PDF as an image — S5: clicking a value opens
    the source page. Excel documents have no page image (404)."""
    row = db.query_one(
        "SELECT stored_path FROM documents WHERE id=?", (document_id,)
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    try:
        doc = pymupdf.open(row["stored_path"])
    except Exception as exc:
        raise HTTPException(status_code=404, detail="Not a renderable PDF.") from exc
    try:
        if not 1 <= page <= doc.page_count:
            raise HTTPException(status_code=404, detail="Page out of range.")
        pix = doc[page - 1].get_pixmap(dpi=120)
        png = pix.tobytes("png")
    finally:
        doc.close()
    return Response(content=png, media_type="image/png",
                    headers={"Cache-Control": "private, max-age=3600"})
