"""REST endpoints: project bootstrap, snapshot read, health."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from ..services.collaboration import CollaborationService
from .schemas import CreateProjectRequest

router = APIRouter()


def _service(request: Request) -> CollaborationService:
    return request.app.state.collaboration


@router.get("/health")
async def health(request: Request):
    try:
        async with request.app.state.pool.acquire() as conn:
            await conn.execute("SELECT 1")
        return {"status": "ok", "instance": request.app.state.instance_id}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@router.post("/projects", status_code=201)
async def create_project(body: CreateProjectRequest, request: Request):
    project = await _service(request).create_project(body.title)
    return project.to_public()


@router.get("/projects/{project_id}")
async def get_project(project_id: str, request: Request):
    service = _service(request)
    project = await service.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    segments = await service.snapshot(project_id)
    return {
        "id": project.id,
        "title": project.title,
        "current_seq": project.current_seq,
        "snapshot_seq": project.snapshot_seq,
        "segments": [s.to_public() for s in segments],
    }
