"""Typed domain models for segments, operations, and commit results."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class OpType(str, Enum):
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    MOVE = "move"
    UNDO = "undo"


@dataclass(slots=True)
class Segment:
    chunk_id: str
    start_time_ms: int | None
    end_time_ms: int | None
    speaker_id: str | None
    text: str | None
    position: str | None
    deleted: bool
    updated_seq: int | None
    updated_by: str | None

    def to_public(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "start_time_ms": self.start_time_ms,
            "end_time_ms": self.end_time_ms,
            "speaker_id": self.speaker_id,
            "text": self.text,
            "position": self.position,
            "deleted": self.deleted,
            "updated_seq": self.updated_seq,
            "updated_by": self.updated_by,
        }


@dataclass(slots=True)
class Operation:
    """A forward op ready to commit: op_type plus its payload and captured inverse."""

    op_type: str
    chunk_id: str | None
    payload: dict[str, Any]
    inverse: dict[str, Any]


@dataclass(slots=True)
class CommittedOp:
    seq: int
    actor: str
    client_op_id: str
    op_type: str
    chunk_id: str | None
    payload: dict[str, Any]
    ts: str

    def to_wire(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "actor": self.actor,
            "client_op_id": self.client_op_id,
            "op_type": self.op_type,
            "chunk_id": self.chunk_id,
            "payload": self.payload,
            "ts": self.ts,
        }


@dataclass(slots=True)
class UndoTarget:
    seq: int
    op_type: str
    chunk_id: str | None
    payload: dict[str, Any]
    inverse: dict[str, Any]


@dataclass(slots=True)
class CommitResult:
    seq: int
    duplicate: bool


@dataclass(slots=True)
class Cursor:
    chunk_id: str | None = None
    field: str | None = None
    offset: int | None = None

    def to_wire(self) -> dict[str, Any]:
        return {"chunk_id": self.chunk_id, "field": self.field, "offset": self.offset}


@dataclass(slots=True)
class Project:
    id: str
    title: str | None
    current_seq: int
    snapshot_seq: int
    created_at: str

    def to_public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "current_seq": self.current_seq,
            "snapshot_seq": self.snapshot_seq,
            "created_at": self.created_at,
        }
