"""Builds forward operations (payload + captured inverse) and inverts ops for undo."""

from __future__ import annotations

from typing import Any

from . import ordering
from .models import Operation, OpType, Segment, UndoTarget

UPDATABLE = {"start_time_ms", "end_time_ms", "speaker_id", "text"}


class OpError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class OperationFactory:
    """Pure construction of forward ops and undo ops; no I/O."""

    def create(self, chunk_id: str, fields: dict[str, Any], positions: list[str]) -> Operation:
        position = fields.get("position")
        if position is None:
            position = ordering.between(positions[-1] if positions else None, None)
        payload = {
            "chunk_id": chunk_id,
            "position": position,
            "start_time_ms": fields.get("start_time_ms"),
            "end_time_ms": fields.get("end_time_ms"),
            "speaker_id": fields.get("speaker_id"),
            "text": fields.get("text", ""),
        }
        return Operation(OpType.CREATE.value, chunk_id, payload, {"op": "delete", "chunk_id": chunk_id})

    def update(self, chunk_id: str, fields: dict[str, Any], current: Segment | None) -> Operation:
        if current is None:
            raise OpError("UNKNOWN_SEGMENT", f"segment {chunk_id} not found")
        editable = {k: v for k, v in fields.items() if k in UPDATABLE}
        if not editable:
            raise OpError("NO_FIELDS", "update has no editable fields")
        prior = {k: current.to_public().get(k) for k in editable}
        return Operation(
            OpType.UPDATE.value,
            chunk_id,
            {"chunk_id": chunk_id, "fields": editable},
            {"op": "update", "fields": prior},
        )

    def delete(self, chunk_id: str, current: Segment | None) -> Operation:
        if current is None:
            raise OpError("UNKNOWN_SEGMENT", f"segment {chunk_id} not found")
        return Operation(
            OpType.DELETE.value,
            chunk_id,
            {"chunk_id": chunk_id},
            {"op": "create", "row": current.to_public()},
        )

    def move(
        self,
        chunk_id: str,
        current: Segment | None,
        before: str | None,
        after: str | None,
    ) -> Operation:
        if current is None:
            raise OpError("UNKNOWN_SEGMENT", f"segment {chunk_id} not found")
        position = ordering.between(before, after)
        return Operation(
            OpType.MOVE.value,
            chunk_id,
            {"chunk_id": chunk_id, "position": position},
            {"op": "move", "position": current.position},
        )

    def invert(self, target: UndoTarget) -> Operation:
        """Turn the stored inverse of `target` into a fresh forward op (§5.7)."""
        inv = target.inverse
        op = inv.get("op")
        target_seq = target.seq

        match op:
            case "delete":
                return Operation(
                    OpType.DELETE.value,
                    inv["chunk_id"],
                    {"chunk_id": inv["chunk_id"], "undoes_seq": target_seq},
                    {"op": "create", "row": None},
                )
            case "create":
                row = inv["row"]
                payload = {
                    "chunk_id": row["chunk_id"],
                    "position": row.get("position"),
                    "start_time_ms": row.get("start_time_ms"),
                    "end_time_ms": row.get("end_time_ms"),
                    "speaker_id": row.get("speaker_id"),
                    "text": row.get("text"),
                    "undoes_seq": target_seq,
                }
                return Operation(
                    OpType.CREATE.value,
                    row["chunk_id"],
                    payload,
                    {"op": "delete", "chunk_id": row["chunk_id"]},
                )
            case "update":
                return Operation(
                    OpType.UPDATE.value,
                    target.chunk_id,
                    {"chunk_id": target.chunk_id, "fields": inv["fields"], "undoes_seq": target_seq},
                    {"op": "update", "fields": target.payload.get("fields", {})},
                )
            case "move":
                return Operation(
                    OpType.MOVE.value,
                    target.chunk_id,
                    {"chunk_id": target.chunk_id, "position": inv["position"], "undoes_seq": target_seq},
                    {"op": "move", "position": target.payload.get("position")},
                )
            case _:
                raise OpError("BAD_UNDO", f"cannot invert op {op!r}")
