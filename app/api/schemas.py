"""Pydantic request/response models for the REST surface."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class CreateProjectRequest(BaseModel):
    title: str | None = None


class ProjectResponse(BaseModel):
    id: str
    title: str | None
    current_seq: int
    snapshot_seq: int
    created_at: str


class SnapshotResponse(BaseModel):
    id: str
    title: str | None
    current_seq: int
    snapshot_seq: int
    segments: list[dict[str, Any]]
